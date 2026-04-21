"""Vista + acciones dedicadas a sesiones Meta Cloud API (Graph API).

URL: /whatsapp/sesiones/meta/

Este archivo es autonomo para la logica Meta:
- Todas las acciones POST especificas de Meta viven aca como funciones.
- `sesionesMetaView` es la vista Django registrada en urls.py.
- El dispatcher `handle_meta_action(request, action)` permite que el view
  legacy `sesionesView` delegue aqui sin duplicar codigo.

Si estas trabajando solo con Meta, en este archivo tenes todo lo que necesitas.

Helpers compartidos: `sesiones_common.py` (hints de error, sincronizador Graph).
"""
from __future__ import annotations

import uuid
import secrets
import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template
from django.urls import reverse

from core.custom_forms import FormError
from core.funciones import addData, log, secure_module, paginador

from crm.models import AgentesIA, PerfilNegocioIA, ReglaFinConversacion, AccionFinConversacion

from .forms import SesionWhatsAppForm, ConfigMetaForm, ConfigInstagramForm, ConfigMessengerForm
from .models import SesionWhatsApp, ConfigMeta, ConfigInstagram, ConfigMessenger
from .services import get_whatsapp_service
from .sesiones_common import (
    hint_error_meta,
    hint_como_texto,
    sincronizar_meta_desde_graph,
    validar_instagram_desde_graph,
    validar_messenger_desde_graph,
    adjuntar_hint_a_response,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Acciones POST (funciones reutilizables — legacy y nueva view las llaman)
# ============================================================================

def accion_add_meta(request, perfil):
    """Crea una nueva sesion Meta (placeholder, sin credenciales todavia)."""
    form = SesionWhatsAppForm(request.POST, request.FILES)
    if not form.is_valid():
        raise FormError(form)
    obj = form.save(commit=False)
    obj.usuario = request.user
    obj.session_id = str(uuid.uuid4())
    obj.proveedor = 'meta'
    obj.estado = 'pendiente'
    obj.save()
    form.save_m2m()
    log(f"Sesion Meta creada: {obj.nombre or obj.id}", request, "add", obj=obj.id)
    return JsonResponse([{'error': False, 'reload': True}], safe=False)


def accion_guardar_config_meta(request):
    """Persiste credenciales Meta a BD. NO llama Graph API — solo guarda.
    La sync con Meta es explicita via `verificar_meta_conexion`."""
    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
    config, _ = ConfigMeta.objects.get_or_create(
        sesion=session,
        defaults={
            'waba_id': '',
            'phone_number_id': '',
            'access_token': '',
            'webhook_verify_token': secrets.token_urlsafe(32),
        },
    )
    form = ConfigMetaForm(request.POST, instance=config)
    if not form.is_valid():
        raise FormError(form)
    obj = form.save()

    if session.proveedor != 'meta':
        session.proveedor = 'meta'
        session.save(update_fields=['proveedor'])

    webhook_url = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
    pendientes = []
    if not obj.waba_id:         pendientes.append('WABA ID')
    if not obj.phone_number_id: pendientes.append('Phone Number ID')
    if not obj.access_token:    pendientes.append('Access Token')

    log(f"Config Meta guardada (solo BD) para sesion {session.id}. Pendientes: {pendientes or 'ninguno'}",
        request, "change", obj=session.id)
    return JsonResponse({
        'error':   False,
        'message': ('Configuracion guardada.' if not pendientes
                    else 'Configuracion guardada. Para sincronizar con Meta falta: ' + ', '.join(pendientes) + '.'),
        'webhook_url':       webhook_url,
        'verify_token':      obj.webhook_verify_token,
        'pendientes':        pendientes,
        'puede_sincronizar': not pendientes,
    })


def accion_regenerar_verify_token(request):
    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
    config = getattr(session, 'config_meta', None)
    if not config:
        return JsonResponse({'error': True, 'message': 'La sesion no tiene configuracion Meta todavia.'})
    config.webhook_verify_token = secrets.token_urlsafe(32)
    config.webhook_verificado_en = None
    config.save(update_fields=['webhook_verify_token', 'webhook_verificado_en'])
    log(f"Verify token regenerado para sesion {session.id}", request, "change", obj=session.id)
    return JsonResponse({
        'error': False,
        'verify_token': config.webhook_verify_token,
        'message': 'Nuevo verify token generado. Actualizalo en Meta Developer Portal.',
    })


def accion_verificar_meta_conexion(request):
    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
    if session.proveedor != 'meta':
        return JsonResponse({'error': True, 'message': 'Esta sesion no usa el proveedor Meta Cloud API.'})
    config = getattr(session, 'config_meta', None)
    if not config:
        return JsonResponse({'error': True, 'message': 'Sesion sin ConfigMeta. Configura WABA ID, phone_number_id y access_token primero.'})
    ok, info = sincronizar_meta_desde_graph(session, config)
    if not ok:
        err_raw = info.get('message') or 'No se pudo verificar con Meta.'
        hint = hint_error_meta(err_raw)
        return JsonResponse({
            'error':          True,
            'message':        str(err_raw) + hint_como_texto(hint),
            'hint':           hint.get('text') or None,
            'hint_link':      hint.get('link') or None,
            'hint_link_label': hint.get('link_label') or None,
            'raw':            err_raw,
        })
    session.refresh_from_db(fields=['numero', 'estado'])
    return JsonResponse({
        'error': False,
        'message': info.get('message'),
        'display_phone_number': info.get('display_phone_number'),
        'quality_rating':       info.get('quality_rating'),
        'messaging_limit_tier': info.get('messaging_limit_tier'),
        'verified_name':        info.get('verified_name'),
        'numero':               session.numero,
        'estado':               session.estado,
    })


def accion_wizard_crear_meta(request, perfil):
    """Wizard de un paso: crea SesionWhatsApp + ConfigMeta en 1 transaccion +
    intenta sincronizar con Graph para popular numero. Pensado para el flujo
    nuevo Meta-only que minimiza fricción al cliente.
    """
    nombre = (request.POST.get('nombre') or '').strip()
    waba_id = (request.POST.get('waba_id') or '').strip()
    phone_number_id = (request.POST.get('phone_number_id') or '').strip()
    access_token = (request.POST.get('access_token') or '').strip()
    app_id = (request.POST.get('app_id') or '').strip()
    app_secret = (request.POST.get('app_secret') or '').strip()
    business_account_id = (request.POST.get('business_account_id') or '').strip()

    if not nombre:
        return JsonResponse({'error': True, 'message': 'Nombre es obligatorio.'})
    if not (waba_id and phone_number_id and access_token):
        return JsonResponse({'error': True, 'message': 'WABA ID, Phone Number ID y Access Token son obligatorios para el wizard.'})

    # Crear sesion + config
    session = SesionWhatsApp.objects.create(
        nombre=nombre,
        proveedor='meta',
        estado='pendiente',
        usuario=request.user,
        session_id=str(uuid.uuid4()),
        qr_code='',
        whatsapp_id='',
    )
    config = ConfigMeta.objects.create(
        sesion=session,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        access_token=access_token,
        app_id=app_id or '',
        app_secret=app_secret or '',
        business_account_id=business_account_id or '',
        webhook_verify_token=secrets.token_urlsafe(32),
    )

    # Sync inmediato con Graph para popular numero/quality
    sync_ok, sync_info = sincronizar_meta_desde_graph(session, config)
    log(f"Wizard Meta crea sesion {session.id} ({nombre}). Sync Graph={sync_ok}",
        request, "add", obj=session.id)

    webhook_url = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))

    if sync_ok:
        session.refresh_from_db(fields=['numero', 'estado'])
        return JsonResponse({
            'error':            False,
            'sincronizado':     True,
            'message':          f'Sesion creada y sincronizada. Numero detectado: {session.numero}.',
            'sesion_id':        session.id,
            'numero':           session.numero,
            'display_phone':    sync_info.get('display_phone_number'),
            'quality_rating':   sync_info.get('quality_rating'),
            'verify_token':     config.webhook_verify_token,
            'webhook_url':      webhook_url,
            'edit_url':         f'/whatsapp/sesiones/meta/?action=change&pk={session.id}',
        })
    err_raw = sync_info.get('message') or 'Sesion creada pero no se pudo verificar con Meta.'
    hint = hint_error_meta(err_raw)
    return JsonResponse({
        'error':            False,  # la sesion SI se creo, solo falto la sync
        'sincronizado':     False,
        'message':          f'Sesion creada (id={session.id}). La validacion con Meta fallo: {err_raw}',
        'sesion_id':        session.id,
        'verify_token':     config.webhook_verify_token,
        'webhook_url':      webhook_url,
        'edit_url':         f'/whatsapp/sesiones/meta/?action=change&pk={session.id}',
        'hint':             hint.get('text') or None,
        'hint_link':        hint.get('link') or None,
        'hint_link_label':  hint.get('link_label') or None,
        'raw':              err_raw,
    })


def accion_registrar_phone_meta(request):
    """Registra el phone_number_id en Cloud API. Sin esto Meta rechaza envios
    con error 133010 'Account not registered'. Equivale al boton 'Register' del
    Developer Portal — se le pasa un PIN de 6 digitos a eleccion del usuario.
    """
    import requests
    from .services_meta import GRAPH_API_BASE
    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
    if session.proveedor != 'meta':
        return JsonResponse({'error': True, 'message': 'Esta accion solo aplica a sesiones Meta.'})
    config = getattr(session, 'config_meta', None)
    if not config or not config.access_token or not config.phone_number_id:
        return JsonResponse({'error': True, 'message': 'Configura access_token + phone_number_id antes de registrar.'})
    pin = (request.POST.get('pin') or '').strip()
    if not pin or not pin.isdigit() or len(pin) != 6:
        return JsonResponse({'error': True, 'message': 'El PIN debe ser 6 digitos numericos. Elige uno y guardalo — sirve para 2FA del numero.'})
    try:
        r = requests.post(
            f'{GRAPH_API_BASE}/{config.phone_number_id}/register',
            headers={
                'Authorization': f'Bearer {config.access_token}',
                'Content-Type':  'application/json',
            },
            json={'messaging_product': 'whatsapp', 'pin': pin},
            timeout=15,
        )
    except Exception as e:
        return JsonResponse({'error': True, 'message': f'Error de conexion con Meta: {e}'})
    if r.status_code in (200, 201):
        log(f"Phone {config.phone_number_id} registrado en Cloud API (sesion {session.id})",
            request, "change", obj=session.id)
        return JsonResponse({
            'error': False,
            'message': 'Phone Number registrado en Cloud API. Ahora podes enviar mensajes.',
            'pin_guardado': pin[:2] + '****',
        })
    err_raw = f'{r.status_code}: {r.text[:400]}'
    hint = hint_error_meta(err_raw)
    return JsonResponse({
        'error':           True,
        'message':         err_raw + hint_como_texto(hint),
        'hint':            hint.get('text') or None,
        'hint_link':       hint.get('link') or None,
        'hint_link_label': hint.get('link_label') or None,
        'raw':             err_raw,
    })


def accion_guardar_config_instagram(request):
    """Persiste credenciales Instagram a BD. NO llama Graph API. Genera el
    webhook_verify_token la primera vez."""
    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
    config, _ = ConfigInstagram.objects.get_or_create(
        sesion=session,
        defaults={
            'ig_user_id': '', 'page_id': '', 'access_token': '',
            'webhook_verify_token': secrets.token_urlsafe(32),
        },
    )
    form = ConfigInstagramForm(request.POST, instance=config)
    if not form.is_valid():
        raise FormError(form)
    obj = form.save()
    pendientes = []
    if not obj.ig_user_id:   pendientes.append('Instagram User ID')
    if not obj.page_id:      pendientes.append('Page ID linkeada')
    if not obj.access_token: pendientes.append('Page Access Token')
    log(f"Config Instagram guardada para sesion {session.id}. Pendientes: {pendientes or 'ninguno'}",
        request, "change", obj=session.id)
    return JsonResponse({
        'error':           False,
        'message':         ('Configuracion Instagram guardada.' if not pendientes
                            else 'Configuracion guardada. Para validar falta: ' + ', '.join(pendientes) + '.'),
        'verify_token':    obj.webhook_verify_token,
        'pendientes':      pendientes,
        'puede_validar':   not pendientes,
    })


def accion_guardar_config_messenger(request):
    """Persiste credenciales Messenger a BD. NO llama Graph API."""
    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
    config, _ = ConfigMessenger.objects.get_or_create(
        sesion=session,
        defaults={
            'page_id': '', 'access_token': '',
            'webhook_verify_token': secrets.token_urlsafe(32),
        },
    )
    form = ConfigMessengerForm(request.POST, instance=config)
    if not form.is_valid():
        raise FormError(form)
    obj = form.save()
    pendientes = []
    if not obj.page_id:      pendientes.append('Page ID')
    if not obj.access_token: pendientes.append('Page Access Token')
    log(f"Config Messenger guardada para sesion {session.id}. Pendientes: {pendientes or 'ninguno'}",
        request, "change", obj=session.id)
    return JsonResponse({
        'error':           False,
        'message':         ('Configuracion Messenger guardada.' if not pendientes
                            else 'Configuracion guardada. Para validar falta: ' + ', '.join(pendientes) + '.'),
        'verify_token':    obj.webhook_verify_token,
        'pendientes':      pendientes,
        'puede_validar':   not pendientes,
    })


def accion_validar_instagram(request):
    """Pinguea Graph API para confirmar que las creds Instagram funcionan."""
    from .models import ConfigInstagram
    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
    cfg_ig = getattr(session, 'config_instagram', None)
    if not cfg_ig:
        return JsonResponse({
            'error': True,
            'message': 'Esta sesion no tiene configuracion Instagram. Configurala primero (ig_user_id + Page Access Token).',
        })
    ok, info = validar_instagram_desde_graph(session, cfg_ig)
    if not ok:
        err_raw = info.get('message') or 'No se pudo validar Instagram.'
        hint = hint_error_meta(err_raw)
        return JsonResponse({
            'error':           True,
            'canal':           'instagram',
            'message':         str(err_raw) + hint_como_texto(hint),
            'hint':            hint.get('text') or None,
            'hint_link':       hint.get('link') or None,
            'hint_link_label': hint.get('link_label') or None,
            'raw':             err_raw,
        })
    return JsonResponse({
        'error':   False,
        'canal':   'instagram',
        'message': info.get('message'),
        'username': info.get('username'),
        'name':     info.get('name'),
        'profile_picture_url': info.get('profile_picture_url'),
    })


def accion_validar_messenger(request):
    """Pinguea Graph API para confirmar que las creds Messenger funcionan."""
    from .models import ConfigMessenger
    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
    cfg_fb = getattr(session, 'config_messenger', None)
    if not cfg_fb:
        return JsonResponse({
            'error': True,
            'message': 'Esta sesion no tiene configuracion Messenger. Configurala primero (page_id + Page Access Token).',
        })
    ok, info = validar_messenger_desde_graph(session, cfg_fb)
    if not ok:
        err_raw = info.get('message') or 'No se pudo validar Messenger.'
        hint = hint_error_meta(err_raw)
        return JsonResponse({
            'error':           True,
            'canal':           'messenger',
            'message':         str(err_raw) + hint_como_texto(hint),
            'hint':            hint.get('text') or None,
            'hint_link':       hint.get('link') or None,
            'hint_link_label': hint.get('link_label') or None,
            'raw':             err_raw,
        })
    return JsonResponse({
        'error':   False,
        'canal':   'messenger',
        'message': info.get('message'),
        'name':     info.get('name'),
        'category': info.get('category'),
        'fan_count': info.get('fan_count'),
        'verification_status': info.get('verification_status'),
    })


def accion_probar_envio_plantilla_meta(request):
    filtro = SesionWhatsApp.objects.get(pk=int(request.POST['id']))
    if not filtro.es_meta:
        return JsonResponse({'error': True, 'message': 'Esta accion solo aplica para sesiones Meta.'})
    config = getattr(filtro, 'config_meta', None)
    if not config or not config.access_token or not config.phone_number_id:
        return JsonResponse({'error': True, 'message': 'La sesion Meta no tiene credenciales completas (access_token / phone_number_id).'})
    numero_destino = (request.POST.get('numero_destino') or '').strip()
    if not numero_destino:
        return JsonResponse({'error': True, 'message': 'Debes ingresar un numero de destino.'})
    plantilla_nombre = (request.POST.get('plantilla_nombre') or 'hello_world').strip()
    idioma = (request.POST.get('idioma') or 'en_US').strip()
    service = get_whatsapp_service(filtro)
    resultado = service.send_template(
        filtro.session_id, numero_destino, plantilla_nombre, idioma=idioma,
    )
    if resultado.get('success'):
        log(f"Plantilla '{plantilla_nombre}' ({idioma}) enviada desde sesion {filtro.id} a {numero_destino}",
            request, "change", obj=filtro.id)
        return JsonResponse({
            'error':      False,
            'message':    f"Plantilla '{plantilla_nombre}' enviada correctamente.",
            'message_id': resultado.get('message_id'),
            'destino':    numero_destino,
            'plantilla':  plantilla_nombre,
            'idioma':     idioma,
        })
    err_raw = resultado.get('error') or 'No se pudo enviar la plantilla.'
    hint = hint_error_meta(err_raw)
    return JsonResponse({
        'error':          True,
        'message':        str(err_raw) + hint_como_texto(hint),
        'hint':           hint.get('text') or None,
        'hint_link':      hint.get('link') or None,
        'hint_link_label': hint.get('link_label') or None,
        'raw':            err_raw,
        'destino':        numero_destino,
    })


# ---------- Dispatcher compartido ----------

_META_ACTIONS = {
    'wizard_crear_meta':             accion_wizard_crear_meta,
    'add_meta':                      accion_add_meta,
    'guardar_config_meta':           lambda r, p: accion_guardar_config_meta(r),
    'guardar_config_instagram':      lambda r, p: accion_guardar_config_instagram(r),
    'guardar_config_messenger':      lambda r, p: accion_guardar_config_messenger(r),
    'regenerar_verify_token':        lambda r, p: accion_regenerar_verify_token(r),
    # Validar cada canal Meta por separado: WA Cloud, IG DM, FB Messenger.
    'verificar_meta_conexion':       lambda r, p: accion_verificar_meta_conexion(r),  # alias historico → WA
    'validar_whatsapp':              lambda r, p: accion_verificar_meta_conexion(r),  # nombre nuevo
    'validar_instagram':             lambda r, p: accion_validar_instagram(r),
    'validar_messenger':             lambda r, p: accion_validar_messenger(r),
    'registrar_phone_meta':          lambda r, p: accion_registrar_phone_meta(r),
    'probar_envio_plantilla_meta':   lambda r, p: accion_probar_envio_plantilla_meta(r),
}


def handle_meta_action(request, action, perfil=None):
    """Devuelve JsonResponse si la accion es Meta, None si no es manejada.
    `perfil` solo lo usa add_meta (ignorado por las demas)."""
    fn = _META_ACTIONS.get(action)
    if not fn:
        return None
    try:
        with transaction.atomic():
            return fn(request, perfil)
    except FormError as ex:
        return JsonResponse([ex.dict_error], safe=False)
    except Exception as ex:
        logger.exception("Error en accion Meta %s: %s", action, ex)
        return JsonResponse([{'error': True, 'message': f'Error: {ex}'}], safe=False)


# ============================================================================
# GET: listado filtrado + resumen Meta
# ============================================================================

@login_required
@secure_module
def sesionesMetaView(request):
    """Vista top-level Meta. Inyecta filtro proveedor=meta y si la accion POST
    es Meta la despacha aca mismo. Si no, delega al legacy sesionesView."""
    # POST: si la accion es Meta, atendemos directo
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action in _META_ACTIONS:
            perfil, _ = PerfilNegocioIA.objects.get_or_create(usuario=request.user)
            resp = handle_meta_action(request, action, perfil)
            if resp is not None:
                return resp
        # Si la accion no es Meta (ej. probar_envio_mensaje comun), delegamos
        from .sesiones_view import sesionesView
        return sesionesView(request)

    # GET: listado filtrado por proveedor=meta + acciones GET Meta-especificas
    if request.GET.get('action') == 'resumen_meta':
        return _render_resumen_meta(request)

    # Pre-filtrar el GET al listado legacy
    if 'proveedor' not in request.GET:
        request.GET = request.GET.copy()
        request.GET['proveedor'] = 'meta'
    from .sesiones_view import sesionesView
    return sesionesView(request)


@login_required
@secure_module
def sesionesMetaWizardView(request):
    """Wizard 3-pasos para crear una sesion Meta nueva sin pasar por el form
    completo. Renderiza un template standalone con steps navegables; el submit
    final usa la accion 'wizard_crear_meta'."""
    data = {
        'titulo':      'Wizard Meta Cloud API',
        'descripcion': 'Crear sesion Meta paso a paso',
        'ruta':        request.path,
        'webhook_url': request.build_absolute_uri(reverse('whatsapp_meta_webhook')),
    }
    addData(request, data)
    return render(request, 'whatsapp/sesiones/meta_wizard.html', data)


def _render_resumen_meta(request):
    """Panel "salud de la sesion Meta" — checks rapidos del estado integral."""
    try:
        instance = SesionWhatsApp.objects.get(id=request.GET['pk'], usuario=request.user)
    except SesionWhatsApp.DoesNotExist:
        return JsonResponse({'result': False, 'message': 'Sesion no encontrada'})
    if instance.proveedor != 'meta':
        return JsonResponse({'result': False, 'message': 'Esta vista solo aplica a sesiones Meta.'})

    cfg = getattr(instance, 'config_meta', None)
    cfg_ig = getattr(instance, 'config_instagram', None)
    cfg_fb = getattr(instance, 'config_messenger', None)
    checks = []

    # ── Section: WhatsApp Cloud ──
    checks.append({
        'nombre': '🟢 WhatsApp · Credenciales Cloud API',
        'ok':     bool(cfg and cfg.waba_id and cfg.phone_number_id and cfg.access_token),
        'detalle': (f'WABA: {cfg.waba_id} · Phone: {cfg.display_phone_number or cfg.phone_number_id}'
                    if cfg and cfg.waba_id else 'Sin WABA/Phone Number ID/Access Token configurados.'),
        'accion_url': f'/whatsapp/sesiones/meta/?action=change_modal&pk={instance.id}',
        'accion_label': 'Configurar credenciales',
    })
    checks.append({
        'nombre': 'Webhook Meta verificado',
        'ok':     bool(cfg and cfg.webhook_verificado_en),
        'detalle': (f'Verificado el {cfg.webhook_verificado_en:%Y-%m-%d %H:%M}'
                    if cfg and cfg.webhook_verificado_en
                    else 'El callback en Meta Developer Portal aun no valido el verify_token.'),
        'accion_url': 'https://developers.facebook.com/apps',
        'accion_label': 'Abrir Meta Developer',
    })
    checks.append({
        'nombre': 'App Secret configurado (firma HMAC)',
        'ok':     bool(cfg and cfg.app_secret),
        'detalle': ('Valida la autenticidad de cada webhook entrante.'
                    if cfg and cfg.app_secret
                    else 'Sin app_secret: los webhooks se aceptan sin validacion HMAC.'),
        'accion_url': f'/whatsapp/sesiones/meta/?action=change_modal&pk={instance.id}',
        'accion_label': 'Editar sesion',
    })
    checks.append({
        'nombre': 'Quality rating',
        'ok':     bool(cfg and cfg.quality_rating in ('GREEN', 'YELLOW')),
        'detalle': f'Meta reporta: {cfg.get_quality_rating_display() if cfg else "Desconocida"}',
        'accion_url': None, 'accion_label': None,
    })
    checks.append({
        'nombre': 'Agente IA asignado',
        'ok':     bool(instance.agente_ia),
        'detalle': (f'Agente: {instance.agente_ia.nombre}' if instance.agente_ia
                    else 'Sin agente IA: las conversaciones no se responden automaticamente.'),
        'accion_url': f'/whatsapp/sesiones/meta/?action=change_modal&pk={instance.id}',
        'accion_label': 'Asignar agente',
    })
    from .models import PlantillaWhatsApp
    plantillas_ok = PlantillaWhatsApp.objects.filter(
        config_meta=cfg, estado_meta='APPROVED', status=True,
    ).count() if cfg else 0
    checks.append({
        'nombre': 'Plantillas aprobadas por Meta',
        'ok':     plantillas_ok > 0,
        'detalle': (f'{plantillas_ok} plantilla(s) aprobadas.' if plantillas_ok
                    else 'Sin plantillas aprobadas: no podras iniciar conversaciones fuera de la ventana de 24h.'),
        'accion_url':   f'/whatsapp/plantillas/?sesion={instance.id}',
        'accion_label': 'Gestionar plantillas',
    })
    horarios_n = instance.horarios.filter(status=True, activo=True).count()
    checks.append({
        'nombre': 'Horarios de atencion',
        'ok':     horarios_n > 0,
        'detalle': (f'{horarios_n} franja(s) horaria(s) activa(s).' if horarios_n
                    else 'Sin horarios: la sesion responde 24/7.'),
        'accion_url':   f'/whatsapp/horarios/?sesion={instance.id}',
        'accion_label': 'Configurar horarios',
    })
    checks.append({
        'nombre': 'Pixel Meta (CAPI) para atribucion Ads',
        'ok':     bool(instance.pixel_meta_id),
        'detalle': (f'Pixel: {instance.pixel_meta.nombre}' if instance.pixel_meta_id
                    else 'Sin pixel vinculado: no se reportaran conversiones a Meta Ads.'),
        'accion_url':   '/admin/whatsapp/pixelmeta/',
        'accion_label': 'Crear/vincular pixel',
    })
    campanas_n = instance.campanas.filter(status=True).count()
    checks.append({
        'nombre': 'Campanas creadas',
        'ok':     campanas_n > 0,
        'detalle': (f'{campanas_n} campana(s) creada(s) en esta sesion.' if campanas_n
                    else 'Aun no has creado campanas para esta sesion.'),
        'accion_url':   f'/whatsapp/campanas/?sesion={instance.id}',
        'accion_label': 'Ver campanas',
    })
    checks.append({
        'nombre': 'Asignacion automatica (round-robin)',
        'ok':     bool(instance.auto_asignar_round_robin),
        'detalle': ('Activado: nuevas conversaciones se asignan a agentes disponibles.'
                    if instance.auto_asignar_round_robin
                    else 'Desactivado: las conversaciones requieren asignacion manual.'),
        'accion_url':   f'/whatsapp/sesiones/meta/?action=change_modal&pk={instance.id}',
        'accion_label': 'Activar',
    })

    # ── Section: Instagram DM ──
    checks.append({
        'nombre': '📷 Instagram · Credenciales',
        'ok':     bool(cfg_ig and cfg_ig.ig_user_id and cfg_ig.page_id and cfg_ig.access_token),
        'detalle': (f'IGSID: {cfg_ig.ig_user_id} · @{cfg_ig.username or "(sin username)"}'
                    if cfg_ig and cfg_ig.ig_user_id
                    else 'Sin IG configurado. Solo aplica si tu negocio tambien usa IG DM.'),
        'accion_url':   f'/whatsapp/sesiones/meta/?action=change_modal&pk={instance.id}',
        'accion_label': 'Configurar Instagram',
    })
    checks.append({
        'nombre': '📷 Instagram · Webhook verificado',
        'ok':     bool(cfg_ig and cfg_ig.webhook_verificado_en),
        'detalle': (f'Verificado el {cfg_ig.webhook_verificado_en:%Y-%m-%d %H:%M}'
                    if cfg_ig and cfg_ig.webhook_verificado_en
                    else 'Sin webhook IG verificado. Configura URL y verify_token en Meta Developer Portal.'),
        'accion_url':   'https://developers.facebook.com/apps',
        'accion_label': 'Abrir Developer Portal',
    })
    checks.append({
        'nombre': '📷 Instagram · Ultima validacion contra Graph',
        'ok':     bool(cfg_ig and cfg_ig.ultima_sincronizacion),
        'detalle': (f'Validado el {cfg_ig.ultima_sincronizacion:%Y-%m-%d %H:%M}'
                    if cfg_ig and cfg_ig.ultima_sincronizacion
                    else 'Sin validar. Usa el boton "Validar Instagram" en el form de la sesion.'),
        'accion_url':   f'/whatsapp/sesiones/meta/?action=change&pk={instance.id}',
        'accion_label': 'Ir a validar',
    })

    # ── Section: Facebook Messenger ──
    checks.append({
        'nombre': '💬 Messenger · Credenciales',
        'ok':     bool(cfg_fb and cfg_fb.page_id and cfg_fb.access_token),
        'detalle': (f'Page: {cfg_fb.page_name or cfg_fb.page_id}'
                    if cfg_fb and cfg_fb.page_id
                    else 'Sin Messenger configurado. Solo aplica si tu negocio tambien recibe DMs en FB Page.'),
        'accion_url':   f'/whatsapp/sesiones/meta/?action=change_modal&pk={instance.id}',
        'accion_label': 'Configurar Messenger',
    })
    checks.append({
        'nombre': '💬 Messenger · Webhook verificado',
        'ok':     bool(cfg_fb and cfg_fb.webhook_verificado_en),
        'detalle': (f'Verificado el {cfg_fb.webhook_verificado_en:%Y-%m-%d %H:%M}'
                    if cfg_fb and cfg_fb.webhook_verificado_en
                    else 'Sin webhook Messenger verificado. Configura URL y verify_token y suscribi la Page al webhook.'),
        'accion_url':   'https://developers.facebook.com/apps',
        'accion_label': 'Abrir Developer Portal',
    })
    checks.append({
        'nombre': '💬 Messenger · Ultima validacion contra Graph',
        'ok':     bool(cfg_fb and cfg_fb.ultima_sincronizacion),
        'detalle': (f'Validado el {cfg_fb.ultima_sincronizacion:%Y-%m-%d %H:%M}'
                    if cfg_fb and cfg_fb.ultima_sincronizacion
                    else 'Sin validar. Usa el boton "Validar Facebook" en el form de la sesion.'),
        'accion_url':   f'/whatsapp/sesiones/meta/?action=change&pk={instance.id}',
        'accion_label': 'Ir a validar',
    })

    total_ok = sum(1 for c in checks if c['ok'])
    data = {
        'titulo': 'Sesiones Meta',
        'descripcion': 'Resumen Meta',
        'ruta': request.path,
    }
    addData(request, data)
    data['sesion'] = instance
    data['config_meta'] = cfg
    data['checks'] = checks
    data['total_ok'] = total_ok
    data['total_checks'] = len(checks)
    data['completitud_pct'] = int(100 * total_ok / len(checks)) if checks else 0
    data['webhook_url'] = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
    template = get_template("whatsapp/sesiones/resumen_meta.html")
    return JsonResponse({"result": True, 'data': template.render(data)})
