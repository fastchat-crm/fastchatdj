"""Alta manual de sesion Meta Cloud API (modo previo a Tech Provider).

Mientras Meta no apruebe el acceso avanzado, el operador del CRM carga a mano
los IDs y el access token de la WABA del cliente. Endpoints:

  POST /whatsapp/meta/manual/validar/   → dry-run: pega Graph y devuelve metadata
  POST /whatsapp/meta/manual/conectar/  → crea SesionWhatsApp + ConfigMeta(alta_manual=True)

Ambos requieren que el usuario este logueado y tengan permiso sobre la URL
(secure_module). Las credenciales App-level (app_id / app_secret) viven en
seguridad.CredencialMetaApp y se usan para validar firma HMAC de webhooks
posteriores — no se piden aca.
"""
from __future__ import annotations

import logging
import secrets
import uuid

import requests
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from meta.urls import build_graph_url

from .models import ConfigMeta, SesionWhatsApp
from .sesiones_common import sincronizar_meta_desde_graph

logger = logging.getLogger(__name__)


def _suscribir_waba_a_app(waba_id: str, access_token: str, timeout: int = 10) -> dict:
    """POST /{waba_id}/subscribed_apps — autoriza la WABA a recibir webhooks
    de la Meta App (la que emitió el access_token).

    Devuelve `{ok: bool, error?: str}`. No lanza excepciones — pensado para
    correrse al final del alta manual sin romper si Meta rechaza.
    """
    if not (waba_id and access_token):
        return {'ok': False, 'error': 'Faltan waba_id o access_token.'}
    try:
        r = requests.post(
            build_graph_url(f'/{waba_id}/subscribed_apps'),
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=timeout,
        )
    except Exception as ex:
        return {'ok': False, 'error': f'No pude llamar Graph: {ex}'}
    if r.status_code != 200:
        try:
            err = r.json().get('error', {}).get('message', r.text[:200])
        except Exception:
            err = r.text[:200]
        return {'ok': False, 'error': err}
    payload = r.json() or {}
    return {'ok': bool(payload.get('success', True)), 'raw': payload}


def _validar_con_graph(waba_id: str, phone_number_id: str, access_token: str,
                       timeout: int = 12) -> dict:
    """Pega Graph con los datos cargados a mano y devuelve metadata o error.

    Devuelve dict con `ok` (bool), `error` (str) si falla, y campos descubiertos:
    `waba_name`, `display_phone_number`, `verified_name`, `quality_rating`.
    """
    out: dict = {'ok': False}
    if not (waba_id and phone_number_id and access_token):
        return {'ok': False, 'error': 'Faltan WABA ID, Phone Number ID o Access Token.'}

    try:
        rw = requests.get(
            build_graph_url(f'/{waba_id}'),
            params={'access_token': access_token, 'fields': 'id,name'},
            timeout=timeout,
        )
    except Exception as ex:
        return {'ok': False, 'error': f'No pude llamar Graph (WABA): {ex}'}
    if rw.status_code != 200:
        try:
            err = rw.json().get('error', {}).get('message', rw.text[:200])
        except Exception:
            err = rw.text[:200]
        return {'ok': False, 'error': f'WABA rechazada por Meta: {err}'}
    waba_data = rw.json() or {}
    out['waba_name'] = waba_data.get('name', '') or ''

    try:
        rp = requests.get(
            build_graph_url(f'/{phone_number_id}'),
            params={'access_token': access_token,
                    'fields': 'display_phone_number,verified_name,quality_rating'},
            timeout=timeout,
        )
    except Exception as ex:
        return {'ok': False, 'error': f'No pude llamar Graph (Phone): {ex}'}
    if rp.status_code != 200:
        try:
            err = rp.json().get('error', {}).get('message', rp.text[:200])
        except Exception:
            err = rp.text[:200]
        return {'ok': False, 'error': f'Phone Number rechazado por Meta: {err}'}
    phone_data = rp.json() or {}
    out['display_phone_number'] = phone_data.get('display_phone_number', '') or ''
    out['verified_name'] = phone_data.get('verified_name', '') or ''
    out['quality_rating'] = (phone_data.get('quality_rating') or 'UNKNOWN').upper()

    out['ok'] = True
    return out


@login_required
@require_POST
@csrf_protect
def meta_manual_validar(request):
    """Dry-run: valida los IDs + token contra Graph sin persistir nada."""
    waba_id = (request.POST.get('waba_id') or '').strip()
    phone_number_id = (request.POST.get('phone_number_id') or '').strip()
    access_token = (request.POST.get('access_token') or '').strip()

    res = _validar_con_graph(waba_id, phone_number_id, access_token)
    if not res.get('ok'):
        return JsonResponse({'ok': False, 'error': res.get('error', 'Error desconocido')})

    return JsonResponse({
        'ok': True,
        'waba_name': res.get('waba_name', ''),
        'display_phone_number': res.get('display_phone_number', ''),
        'verified_name': res.get('verified_name', ''),
        'quality_rating': res.get('quality_rating', ''),
    })


@login_required
@require_POST
@csrf_protect
def meta_manual_conectar(request):
    """Crea SesionWhatsApp(proveedor='meta') + ConfigMeta(alta_manual=True).

    Valida primero los IDs contra Graph (mismo dry-run que `meta_manual_validar`).
    Si Meta acepta, persiste la sesion como `conectado` y la deja lista para
    enviar/recibir mensajes. Devuelve `sesion_id` para que el front recargue.
    """
    nombre = (request.POST.get('nombre') or '').strip()
    waba_id = (request.POST.get('waba_id') or '').strip()
    phone_number_id = (request.POST.get('phone_number_id') or '').strip()
    business_account_id = (request.POST.get('business_account_id') or '').strip()
    display_phone_number = (request.POST.get('display_phone_number') or '').strip()
    access_token = (request.POST.get('access_token') or '').strip()

    if not (nombre and waba_id and phone_number_id and access_token):
        return JsonResponse({
            'ok': False,
            'error': 'Faltan campos obligatorios: nombre, WABA ID, Phone Number ID y Access Token.',
        })

    # Phone Number ID es UNIQUE en ConfigMeta — chequeo previo amistoso.
    existing = ConfigMeta.objects.filter(phone_number_id=phone_number_id).first()
    if existing:
        return JsonResponse({
            'ok': False,
            'error': f'El Phone Number ID {phone_number_id} ya está conectado en otra sesión.',
            'sesion_id': existing.sesion_id,
        })

    # Dry-run contra Graph.
    chequeo = _validar_con_graph(waba_id, phone_number_id, access_token)
    if not chequeo.get('ok'):
        return JsonResponse({'ok': False, 'error': chequeo.get('error', 'Meta rechazó las credenciales.')})

    display = display_phone_number or chequeo.get('display_phone_number') or ''
    verified_name = chequeo.get('verified_name') or ''

    sesion = SesionWhatsApp.objects.create(
        nombre=nombre,
        proveedor='meta',
        estado='conectado',
        usuario=request.user,
        session_id=str(uuid.uuid4()),
        numero=display,
    )

    config = ConfigMeta.objects.create(
        sesion=sesion,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        business_account_id=business_account_id or None,
        display_phone_number=display or None,
        verified_name=verified_name or None,
        access_token=access_token,
        webhook_verify_token=secrets.token_urlsafe(32),
        quality_rating=chequeo.get('quality_rating') or 'UNKNOWN',
        alta_manual=True,
    )

    # Best-effort: refrescar metadata desde Graph (si falla, ya quedamos OK).
    try:
        sincronizar_meta_desde_graph(sesion, config)
    except Exception as ex:
        logger.warning("sincronizar_meta_desde_graph fallo en alta manual: %s", ex)

    # Auto-suscribir la WABA a la app: sin esto, el webhook a nivel app no
    # recibe eventos de esta WABA específica. Si falla, devolvemos hint para
    # que el operador corra el curl manualmente desde el modal de webhook.
    sub_res = _suscribir_waba_a_app(waba_id, access_token)
    if sub_res.get('ok'):
        logger.info("WABA %s auto-suscrita a la Meta App.", waba_id)

    return JsonResponse({
        'ok': True,
        'sesion_id': sesion.id,
        'nombre': sesion.nombre,
        'display_phone_number': display,
        'verified_name': verified_name,
        'webhook_verify_token': config.webhook_verify_token,
        'waba_suscrita': sub_res.get('ok'),
        'waba_suscrita_error': sub_res.get('error') if not sub_res.get('ok') else None,
    })


@login_required
@require_POST
@csrf_protect
def meta_registrar_numero(request, sesion_id):
    """Registra el número en Cloud API (POST /{phone_number_id}/register).

    Un número recién cargado en Cloud API queda en estado PENDING y todo envío
    falla con (#133010) Account not registered. Este endpoint lo registra con
    el PIN de verificación en dos pasos (6 dígitos). Tras un registro OK, Meta
    pasa el número a CONNECTED y los envíos funcionan.

    POST /whatsapp/sesiones/<sesion_id>/registrar-numero/
    Body: pin=<6 dígitos>
    """
    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'Sesión no encontrada o no es Meta.'})

    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'ok': False, 'error': 'La sesión no tiene ConfigMeta.'})
    if not (config.access_token and config.phone_number_id):
        return JsonResponse({'ok': False, 'error': 'Falta access_token o phone_number_id en la sesión.'})

    pin = (request.POST.get('pin') or '').strip()
    if not (pin.isdigit() and len(pin) == 6):
        return JsonResponse({'ok': False, 'error': 'El PIN debe ser de 6 dígitos.'})

    try:
        r = requests.post(
            build_graph_url(f'/{config.phone_number_id}/register'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            json={'messaging_product': 'whatsapp', 'pin': pin},
            timeout=15,
        )
    except Exception as ex:
        return JsonResponse({'ok': False, 'error': f'No pude llamar a Graph: {ex}'})

    if r.status_code != 200:
        try:
            err = r.json().get('error', {}).get('message', r.text[:300])
        except Exception:
            err = r.text[:300]
        return JsonResponse({'ok': False, 'error': f'Meta rechazó el registro: {err}'})

    # Best-effort: refrescar metadata (status pasa a CONNECTED) desde Graph.
    try:
        sincronizar_meta_desde_graph(sesion, config)
    except Exception as ex:
        logger.warning("sincronizar_meta_desde_graph falló tras registro: %s", ex)

    logger.info("Número registrado en Cloud API: phone_number_id=%s (sesión %s)",
                config.phone_number_id, sesion.id)
    return JsonResponse({'ok': True, 'message': 'Número registrado en Cloud API. Ya podés enviar mensajes.'})


@login_required
@require_POST
@csrf_protect
def meta_test_message(request, sesion_id):
    """Envía un mensaje de eco/prueba desde una sesión Meta a un número destino.

    POST /whatsapp/meta/test-message/<sesion_id>/
    Body: numero=<E164 sin +>, mensaje=<texto>

    Restricción WhatsApp: si el destinatario no escribió en las últimas 24h,
    Meta solo acepta plantillas pre-aprobadas. Para texto plano, el destinatario
    debe haber iniciado conversación dentro de la ventana de 24h.
    """
    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'Sesión no encontrada o no es Meta.'})

    numero = (request.POST.get('numero') or '').strip()
    mensaje = (request.POST.get('mensaje') or '').strip()
    if not numero or not mensaje:
        return JsonResponse({'ok': False, 'error': 'Faltan número destino o mensaje.'})
    # Limpiar el numero: solo dígitos
    numero_limpio = ''.join(ch for ch in numero if ch.isdigit())
    if len(numero_limpio) < 7:
        return JsonResponse({'ok': False, 'error': 'Número inválido.'})

    from .services import get_whatsapp_service
    service = get_whatsapp_service(sesion)
    res = service.send_text_message(sesion.session_id, numero_limpio, mensaje)

    if res.get('success'):
        return JsonResponse({
            'ok': True,
            'message_id': res.get('message_id') or res.get('messages', [{}])[0].get('id', ''),
            'numero': numero_limpio,
        })
    return JsonResponse({
        'ok': False,
        'error': res.get('error') or res.get('message') or 'Meta rechazó el envío.',
        'detalle': res,
    })
