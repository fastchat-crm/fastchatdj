"""Modulo Conexiones (tablero de sesiones WhatsApp).

Diseño estilo Pancake:
- Tablero con cards de sesiones existentes.
- Boton "Conectar" abre modal unico "Agregar conexion" con sidebar de canales:
  * Desactivado  -> Baileys (legacy, QR).
  * WhatsApp     -> Meta Cloud API via OAuth Embedded Signup.
  * Resto        -> "Proximamente" (placeholder).

Las acciones POST viven aca y son minimas:
- baileys_start      -> crea placeholder + socket Node + devuelve QR.
- baileys_status     -> poll del estado del socket (por si QR expiro).
- disconnect         -> cierra Baileys en Node o marca desconectada Meta.
- delete             -> soft delete (status=False) si esta pendiente o vacia.
"""
from __future__ import annotations

import logging
import uuid

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template
from django.urls import reverse

from core.funciones import addData, log, secure_module

from autenticacion.models import Usuario

from .models import SesionWhatsApp, ConfigBaileys, ConfigMeta, PerfilSesionWhatsApp
from .services import WhatsAppService

import json


def _get_or_create_config_baileys(sesion):
    """Devuelve el ConfigBaileys de la sesion, creandolo si no existe."""
    cb, _ = ConfigBaileys.objects.get_or_create(sesion=sesion)
    return cb

logger = logging.getLogger(__name__)


# ============================================================================
# Acciones POST
# ============================================================================

def _accion_baileys_start(request):
    """Crea (o reusa) una sesion Baileys pendiente, abre socket en Node y
    devuelve el QR base64 para renderizar en el modal.
    """
    svc = WhatsAppService()
    session_id = request.POST.get('session_id') or 0
    sesion = SesionWhatsApp.objects.filter(id=session_id, usuario=request.user).first()
    if not sesion:
        sesion = SesionWhatsApp.objects.create(
            estado='pendiente',
            usuario=request.user,
            session_id=str(uuid.uuid4()),
            proveedor='baileys',
        )
        log(f"Sesion Baileys placeholder creada (ID: {sesion.id})", request, "add", obj=sesion.id)

    cb = _get_or_create_config_baileys(sesion)

    if sesion.estado in ('desconectado', 'error'):
        # Rotar UUID si la sesion ya existia pero estaba muerta
        try:
            svc.close_session(sesion.session_id)
        except Exception:
            pass
        sesion.session_id = str(uuid.uuid4())
        sesion.estado = 'pendiente'
        sesion.save(update_fields=['session_id', 'estado'])
        cb.qr_code = ''
        cb.whatsapp_id = ''
        cb.error_mensaje = None
        cb.desconectado_manualmente = False
        cb.save(update_fields=['qr_code', 'whatsapp_id', 'error_mensaje', 'desconectado_manualmente'])

    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
    result = svc.create_session(sesion, webhook_url)
    if not result.get('success'):
        err = (result.get('error') or 'No se pudo crear la sesion en el servicio Node.js')[:500]
        sesion.estado = 'error'
        sesion.save(update_fields=['estado'])
        cb.error_mensaje = err
        cb.save(update_fields=['error_mensaje'])
        return JsonResponse({'error': True, 'sesion_id': sesion.id, 'message': err})

    cb.qr_code = result.get('qr_code') or ''
    cb.save(update_fields=['qr_code'])
    return JsonResponse({
        'error':     False,
        'sesion_id': sesion.id,
        'qr':        cb.qr_code,
        'estado':    sesion.estado,
    })


def _accion_baileys_status(request):
    """Poll del estado de una sesion Baileys (por si el QR expiro o ya se escaneo)."""
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('sesion_id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'Sesion no encontrada.'})
    cb = getattr(sesion, 'config_baileys', None)
    return JsonResponse({
        'error':     False,
        'estado':    sesion.estado,
        'numero':    sesion.numero or '',
        'qr':        (cb.qr_code if cb else '') or '',
    })


def _accion_disconnect(request):
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'Sesion no encontrada.'})
    if sesion.es_baileys:
        try:
            WhatsAppService().close_session(sesion.session_id)
        except Exception as ex:
            logger.warning("close_session fallo (id=%s): %s", sesion.id, ex)
        cb = _get_or_create_config_baileys(sesion)
        cb.desconectado_manualmente = True
        cb.error_mensaje = None
        cb.save(update_fields=['desconectado_manualmente', 'error_mensaje'])
    sesion.estado = 'desconectado'
    sesion.save(update_fields=['estado'])
    log(f"Sesion {sesion.id} desconectada", request, "change", obj=sesion.id)
    return JsonResponse({'error': False, 'message': 'Sesion desconectada.'})


def _accion_delete(request):
    """Consumido por `eliminarajax` de base.html. En exito devuelve
    `{error:false}`; en error devuelve `[{error:true, message:...}]` (array)
    porque eliminarajax lee `data[0].message` en el path de error.
    """
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse([{'error': True, 'message': 'Sesión no encontrada.'}], safe=False)
    if sesion.es_baileys:
        try:
            WhatsAppService().close_session(sesion.session_id)
        except Exception:
            pass
    sesion.status = False
    sesion.estado = 'desconectado'
    sesion.save(update_fields=['status', 'estado'])
    log(f"Sesion {sesion.id} eliminada", request, "del", obj=sesion.id)
    return JsonResponse({'error': False, 'message': 'Sesión eliminada.'})


def _accion_baileys_verificar(request):
    """Pinguea Node para confirmar que el socket Baileys sigue vivo."""
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion or not sesion.es_baileys:
        return JsonResponse({'error': True, 'message': 'Solo aplica a sesiones Baileys.'})
    svc = WhatsAppService()
    r = svc.check_session_status(sesion.session_id)
    cb = _get_or_create_config_baileys(sesion)
    if not r.get('success'):
        if r.get('not_found') and sesion.estado == 'conectado':
            sesion.estado = 'desconectado'
            sesion.save(update_fields=['estado'])
            cb.error_mensaje = 'Socket no existe en Node.'
            cb.save(update_fields=['error_mensaje'])
        return JsonResponse({'error': True, 'message': r.get('error') or 'No se pudo verificar.'})
    conectado = r.get('connected')
    if conectado and sesion.estado != 'conectado':
        sesion.estado = 'conectado'
        sesion.save(update_fields=['estado'])
        cb.error_mensaje = None
        cb.save(update_fields=['error_mensaje'])
    elif not conectado and sesion.estado == 'conectado':
        sesion.estado = 'desconectado'
        sesion.save(update_fields=['estado'])
        cb.error_mensaje = 'Socket caido (detectado al verificar).'
        cb.save(update_fields=['error_mensaje'])
    return JsonResponse({
        'error': False, 'connected': conectado, 'estado': sesion.estado,
        'message': 'Socket activo.' if conectado else 'Socket no responde.',
    })


def _accion_meta_validar(request):
    """Sincroniza credenciales Meta contra Graph API y popula numero/quality."""
    from .sesiones_common import sincronizar_meta_desde_graph
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion or not sesion.es_meta:
        return JsonResponse({'error': True, 'message': 'Solo aplica a sesiones Meta.'})
    cfg = getattr(sesion, 'config_meta', None)
    if not cfg:
        return JsonResponse({'error': True, 'message': 'Sesion sin ConfigMeta.'})
    ok, info = sincronizar_meta_desde_graph(sesion, cfg)
    if not ok:
        return JsonResponse({'error': True, 'message': info.get('message') or 'Fallo la validacion.'})
    sesion.refresh_from_db()
    cfg.refresh_from_db()
    return JsonResponse({
        'error': False,
        'message': info.get('message'),
        'numero': sesion.numero,
        'estado': sesion.estado,
        # Datos ricos para el modal de revalidación
        'display_phone_number': cfg.display_phone_number or '',
        'verified_name': info.get('verified_name') or '',
        'quality_rating': cfg.quality_rating or 'UNKNOWN',
        'messaging_limit_tier': cfg.get_messaging_limit_tier_display() if cfg.messaging_limit_tier else '',
        'waba_id': cfg.waba_id,
        'phone_number_id': cfg.phone_number_id,
        'ultima_sincronizacion': cfg.ultima_sincronizacion.isoformat() if cfg.ultima_sincronizacion else None,
    })


def _accion_meta_test_credenciales(request):
    """Dry-run against Graph with credentials provided in POST.

    Used by the edit panel of the transport-data modal to verify new
    credentials before persisting them. Does not touch the database.
    """
    from .meta_manual_view import _validar_con_graph
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion or not sesion.es_meta:
        return JsonResponse({'error': True, 'message': 'Only applies to Meta sessions.'})

    waba_id = (request.POST.get('waba_id') or '').strip()
    phone_number_id = (request.POST.get('phone_number_id') or '').strip()
    access_token = (request.POST.get('access_token') or '').strip()
    if not (waba_id and phone_number_id and access_token):
        return JsonResponse({'error': True, 'message': 'WABA ID, Phone Number ID and Access Token are required.'})

    res = _validar_con_graph(waba_id, phone_number_id, access_token)
    if not res.get('ok'):
        return JsonResponse({'error': True, 'message': res.get('error', 'Meta rejected the credentials.')})

    return JsonResponse({
        'error': False,
        'message': 'Meta accepted the credentials.',
        'waba_name': res.get('waba_name', ''),
        'display_phone_number': res.get('display_phone_number', ''),
        'verified_name': res.get('verified_name', ''),
        'quality_rating': res.get('quality_rating', ''),
    })


def _accion_meta_actualizar_credenciales(request):
    """Persist new credentials for an existing Meta session.

    Re-validates against Graph, updates ConfigMeta, marks the session as
    connected and re-subscribes the WABA to the Meta App.
    """
    from .meta_manual_view import _validar_con_graph, _suscribir_waba_a_app
    from .sesiones_common import sincronizar_meta_desde_graph
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion or not sesion.es_meta:
        return JsonResponse({'error': True, 'message': 'Only applies to Meta sessions.'})
    cfg = getattr(sesion, 'config_meta', None)
    if not cfg:
        return JsonResponse({'error': True, 'message': 'Session has no ConfigMeta loaded.'})

    waba_id = (request.POST.get('waba_id') or '').strip()
    phone_number_id = (request.POST.get('phone_number_id') or '').strip()
    business_account_id = (request.POST.get('business_account_id') or '').strip()
    display_phone_number = (request.POST.get('display_phone_number') or '').strip()
    access_token = (request.POST.get('access_token') or '').strip()
    if not (waba_id and phone_number_id and access_token):
        return JsonResponse({'error': True, 'message': 'WABA ID, Phone Number ID and Access Token are required.'})

    clash = ConfigMeta.objects.filter(phone_number_id=phone_number_id).exclude(sesion_id=sesion.id).first()
    if clash:
        return JsonResponse({
            'error': True,
            'message': f'Phone Number ID {phone_number_id} is already used by another session.',
        })

    chequeo = _validar_con_graph(waba_id, phone_number_id, access_token)
    if not chequeo.get('ok'):
        return JsonResponse({'error': True, 'message': chequeo.get('error', 'Meta rejected the credentials.')})

    cfg.waba_id = waba_id
    cfg.phone_number_id = phone_number_id
    cfg.business_account_id = business_account_id or None
    cfg.display_phone_number = display_phone_number or chequeo.get('display_phone_number') or cfg.display_phone_number
    cfg.verified_name = chequeo.get('verified_name') or cfg.verified_name
    cfg.quality_rating = chequeo.get('quality_rating') or cfg.quality_rating or 'UNKNOWN'
    cfg.access_token = access_token
    cfg.alta_manual = True
    cfg.save(request)

    sesion.numero = cfg.display_phone_number or sesion.numero
    if sesion.estado != 'conectado':
        sesion.estado = 'conectado'
    sesion.save(request)

    try:
        sincronizar_meta_desde_graph(sesion, cfg)
    except Exception as ex:
        logger.warning("sincronizar_meta_desde_graph failed on credentials update: %s", ex)

    sub_res = _suscribir_waba_a_app(waba_id, access_token)
    log(f"Meta credentials updated for session {sesion.id}", request, "change", obj=sesion.id)

    return JsonResponse({
        'error': False,
        'message': 'Credentials updated and connection re-tested successfully.',
        'estado': sesion.estado,
        'numero': sesion.numero,
        'display_phone_number': cfg.display_phone_number or '',
        'verified_name': cfg.verified_name or '',
        'waba_suscrita': sub_res.get('ok'),
        'waba_suscrita_error': sub_res.get('error') if not sub_res.get('ok') else None,
    })


def _accion_meta_plantilla_prueba(request):
    """Envia una plantilla Meta a un numero como test."""
    from .services import get_whatsapp_service
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion or not sesion.es_meta:
        return JsonResponse({'error': True, 'message': 'Solo aplica a sesiones Meta.'})
    destino = (request.POST.get('destino') or '').strip()
    plantilla = (request.POST.get('plantilla') or 'hello_world').strip()
    idioma = (request.POST.get('idioma') or 'en_US').strip()
    if not destino:
        return JsonResponse({'error': True, 'message': 'Ingresa un numero de destino.'})
    svc = get_whatsapp_service(sesion)
    r = svc.send_template(sesion.session_id, destino, plantilla, idioma=idioma)
    if not r.get('success'):
        return JsonResponse({'error': True, 'message': r.get('error') or 'No se pudo enviar la plantilla.'})
    log(f"Plantilla de prueba '{plantilla}' ({idioma}) enviada desde sesion {sesion.id} a {destino}",
        request, "change", obj=sesion.id)
    return JsonResponse({
        'error': False,
        'message': f'Plantilla "{plantilla}" enviada a +{destino}.',
        'message_id': r.get('message_id'),
    })


def _accion_toggle_activo(request):
    """Activa o pausa la sesión a nivel servicio.

    Cuando `activo=False`:
    - `process_incoming_message` corta de inmediato (no IA, no respuesta).
    - Cron de despedidas, programados, reconexión y campañas filtran fuera
      esta sesión.

    No toca el estado del socket Baileys/Meta — la sesión sigue conectada
    pero no procesa. Útil para suspender el servicio a un cliente sin
    romper la integración ni borrar datos.
    """
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'Sesion no encontrada.'})
    sesion.activo = not bool(sesion.activo)
    sesion.save(update_fields=['activo'])
    accion_log = 'activada' if sesion.activo else 'pausada'
    log(f"Sesion {sesion.id} {accion_log}", request, "change", obj=sesion.id)
    return JsonResponse({
        'error': False,
        'activo': sesion.activo,
        'message': (
            'Sesión activada — vuelve a procesar mensajes y enviar respuestas.'
            if sesion.activo else
            'Sesión pausada — no procesa mensajes ni consume API hasta reactivarla.'
        ),
    })


def _accion_editar(request):
    """Guarda cambios del modal "Modificar": campos basicos de la sesion.

    Responde en formato array (compatible con `static/js/forms.js`):
    `[{error: bool, message: str, reload?: bool, ...}]`.
    """
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse([{'error': True, 'message': 'Sesion no encontrada.'}], safe=False)
    nombre = (request.POST.get('nombre') or '').strip()
    if not nombre:
        return JsonResponse([{
            'error': True,
            'message': 'El nombre es obligatorio.',
            'form': [{'nombre': 'El nombre es obligatorio.'}],
        }], safe=False)
    sesion.nombre = nombre
    sesion.modo_bot = request.POST.get('modo_bot') or sesion.modo_bot
    sesion.language = request.POST.get('language') or sesion.language
    sesion.zona_horaria = (request.POST.get('zona_horaria') or sesion.zona_horaria).strip()
    sesion.mensaje_bienvenida = (request.POST.get('mensaje_bienvenida') or '').strip() or None
    sesion.mensaje_despedida   = (request.POST.get('mensaje_despedida')   or '').strip() or None
    sesion.mensaje_handoff     = (request.POST.get('mensaje_handoff')     or '').strip() or None
    min_sesion_raw = (request.POST.get('min_sesion') or '').strip()
    if min_sesion_raw:
        if not min_sesion_raw.isdigit():
            return JsonResponse([{
                'error': True,
                'message': 'La duración de la sesión debe ser un número entero de minutos.',
                'form': [{'min_sesion': 'Valor inválido.'}],
            }], safe=False)
        min_sesion_val = int(min_sesion_raw)
        if min_sesion_val < 1 or min_sesion_val > 720:
            return JsonResponse([{
                'error': True,
                'message': 'La duración de la sesión debe estar entre 1 y 720 minutos (12 horas).',
                'form': [{'min_sesion': 'Rango permitido: 1 a 720.'}],
            }], safe=False)
        sesion.min_sesion = min_sesion_val
    # Agente IA (opcional — llega como id o vacio)
    agente_id = request.POST.get('agente_ia') or ''
    if agente_id.isdigit():
        from crm.models import AgentesIA
        agente = AgentesIA.objects.filter(id=int(agente_id), status=True).first()
        sesion.agente_ia = agente
    elif agente_id == '':
        sesion.agente_ia = None
    # Departamentos asociados (M2M) — solo aplica a modo tradicional.
    # Llegan como lista de ids vía multi-select. Si el modo no es tradicional,
    # ignoramos el cambio para no perder asociaciones por error.
    from crm.models import DepartamentoChatBot
    if sesion.modo_bot == 'tradicional':
        ids_post = request.POST.getlist('departamentos') or []
        ids_validos = [int(x) for x in ids_post if x.isdigit()]
        deptos_qs = DepartamentoChatBot.objects.filter(id__in=ids_validos, status=True)
        # Departamento default: debe estar dentro de los seleccionados en el M2M.
        depto_id = request.POST.get('departamento_default') or ''
        depto_default = None
        if depto_id.isdigit():
            depto_default = deptos_qs.filter(id=int(depto_id)).first()
            if depto_default is None:
                return JsonResponse([{
                    'error': True,
                    'message': 'El departamento de entrada debe estar dentro de los seleccionados.',
                }], safe=False)
        sesion.departamento_default = depto_default
        sesion.save()
        sesion.departamentos.set(deptos_qs)
    else:
        sesion.save()
    log(f"Sesion {sesion.id} editada", request, "change", obj=sesion.id)
    return JsonResponse([{
        'error': False,
        'message': 'Cambios guardados.',
        'reload': True,
    }], safe=False)


# ============================================================================
# Menús rápidos por sesión (CRUD + envío)
# ============================================================================

def _accion_menu_rapido_listar(request):
    """Lista menús rápidos de una sesión + cataloga sus opciones para el
    chip-bar de /whatsapp/conversaciones/."""
    from .models import MenuRapidoSesion
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('sesion_id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'Sesión no encontrada.'})
    items = list(
        MenuRapidoSesion.objects.filter(sesion=sesion, status=True).order_by('nombre')
        .values('id', 'nombre', 'color', 'cuerpo', 'header', 'footer', 'opciones')
    )
    return JsonResponse({'error': False, 'sesion_id': sesion.id, 'items': items})


def _accion_menu_rapido_guardar(request):
    """Crea o actualiza un menú rápido. Si vino `id`, edita; si no, crea."""
    from .models import MenuRapidoSesion
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('sesion_id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'Sesión no encontrada.'})
    nombre = (request.POST.get('nombre') or '').strip()
    if not nombre:
        return JsonResponse({'error': True, 'message': 'El nombre es obligatorio.'})

    raw_opciones = request.POST.get('opciones') or '[]'
    try:
        import json as _json
        opciones = _json.loads(raw_opciones)
        if not isinstance(opciones, list):
            raise ValueError('Debe ser una lista.')
        # Validar y limpiar cada opción.
        clean = []
        for o in opciones[:10]:  # Meta acepta máx 10 en lista, 3 en buttons
            if not isinstance(o, dict):
                continue
            etq = (o.get('etiqueta') or '').strip()[:24]  # Meta ≤24 chars
            valor = (o.get('valor') or etq).strip()[:256]
            if etq and valor:
                clean.append({'etiqueta': etq, 'valor': valor})
        if not clean:
            return JsonResponse({'error': True, 'message': 'Agregá al menos un botón válido.'})
    except (ValueError, TypeError) as ex:
        return JsonResponse({'error': True, 'message': f'Opciones inválidas: {ex}'})

    menu_id = request.POST.get('id') or ''
    defaults = {
        'sesion':  sesion,
        'nombre':  nombre[:80],
        'color':   (request.POST.get('color') or '#16a34a')[:20],
        'cuerpo':  (request.POST.get('cuerpo') or '').strip()[:1024],
        'header':  (request.POST.get('header') or '').strip()[:60],
        'footer':  (request.POST.get('footer') or '').strip()[:60],
        'opciones': clean,
    }
    if menu_id.isdigit():
        menu = MenuRapidoSesion.objects.filter(id=int(menu_id), sesion=sesion).first()
        if not menu:
            return JsonResponse({'error': True, 'message': 'Menú no encontrado.'})
        for k, v in defaults.items():
            setattr(menu, k, v)
        menu.save()
        creado = False
    else:
        menu = MenuRapidoSesion.objects.create(**defaults)
        creado = True
    log(f"Menú rápido {'creado' if creado else 'actualizado'}: sesion={sesion.id} menu={menu.id}",
        request, "add" if creado else "change", obj=menu.id)
    return JsonResponse({
        'error': False, 'creado': creado, 'menu_id': menu.id,
        'message': 'Menú guardado.',
    })


def _accion_menu_rapido_eliminar(request):
    from .models import MenuRapidoSesion
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('sesion_id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'Sesión no encontrada.'})
    menu = MenuRapidoSesion.objects.filter(id=request.POST.get('id'), sesion=sesion).first()
    if not menu:
        return JsonResponse({'error': True, 'message': 'Menú no encontrado.'})
    menu.status = False
    menu.save()
    log(f"Menú rápido eliminado: {menu.id}", request, "del", obj=menu.id)
    return JsonResponse({'error': False, 'message': 'Menú eliminado.'})


def _accion_menu_rapido_enviar(request):
    """Envía un menú rápido a una conversación activa. Auto-detecta canal:
    Meta → interactive buttons (≤3) o list (>3). Baileys → texto numerado."""
    from datetime import timedelta
    from django.utils import timezone
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from .models import (
        MenuRapidoSesion, ConversacionWhatsApp, MensajeWhatsApp,
    )
    from .services import get_whatsapp_service

    try:
        conv_id = int(request.POST.get('conversacion_id') or 0)
        menu_id = int(request.POST.get('menu_id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': True, 'message': 'IDs inválidos.'})

    conv = ConversacionWhatsApp.objects.select_related(
        'contacto', 'contacto__sesion'
    ).filter(pk=conv_id).first()
    if not conv:
        return JsonResponse({'error': True, 'message': 'Conversación no encontrada.'})
    if conv.conversacion_finalizada:
        return JsonResponse({'error': True, 'message': 'La conversación ya cerró.'})

    sesion = conv.contacto.sesion
    menu = MenuRapidoSesion.objects.filter(pk=menu_id, sesion=sesion, status=True).first()
    if not menu:
        return JsonResponse({'error': True, 'message': 'Menú no pertenece a esta sesión.'})

    opciones = menu.opciones or []
    if not opciones:
        return JsonResponse({'error': True, 'message': 'El menú no tiene opciones.'})

    destino = conv.contacto.from_number
    service = get_whatsapp_service(sesion)
    if sesion.es_baileys and '@' not in destino:
        destino = service.format_phone_number(destino)

    cuerpo = menu.cuerpo or ''
    persistido_text = cuerpo
    ahora = timezone.now()
    success = False
    err = ''

    # Intentar interactive si Meta y service lo soporta.
    if sesion.es_meta and hasattr(service, 'send_interactive_buttons'):
        # Meta: ≤3 → buttons, >3 → list (hasta 10).
        if len(opciones) <= 3:
            buttons = [{'id': o['valor'][:256], 'title': o['etiqueta'][:20]} for o in opciones[:3]]
            r = service.send_interactive_buttons(
                sesion.session_id, destino, cuerpo or '👇 Elige una opción:',
                buttons, header_text=(menu.header or None),
                footer_text=(menu.footer or None), conversacion_id=conv.id,
            )
        else:
            rows = [{'id': o['valor'][:200], 'title': o['etiqueta'][:24]}
                    for o in opciones[:10]]
            r = service.send_interactive_list(
                sesion.session_id, destino,
                cuerpo or '👇 Elige una opción:',
                sections=[{'title': 'Opciones', 'rows': rows}],
                button_text='Ver opciones',
                header_text=(menu.header or None),
                footer_text=(menu.footer or None),
                conversacion_id=conv.id,
            )
        success = bool((r or {}).get('success'))
        err = (r or {}).get('error', '')
        persistido_text = cuerpo + '\n[Opciones: ' + ' · '.join(o['etiqueta'] for o in opciones[:5]) + ']'

    # Fallback texto numerado (Baileys o si fallo Meta).
    if not success:
        lineas = [cuerpo or 'Elige una opción:']
        for i, o in enumerate(opciones, start=1):
            lineas.append(f'{i}. {o["etiqueta"]}')
        texto_plano = '\n'.join(lineas)
        r2 = service.send_text_message(
            sesion.session_id, destino, texto_plano, conversacion_id=conv.id,
        )
        success = bool((r2 or {}).get('success'))
        err = (r2 or {}).get('error', err)
        persistido_text = texto_plano

    if not success:
        return JsonResponse({'error': True, 'message': err or 'No se pudo enviar el menú.'})

    # Persistir como mensaje saliente del agente (no IA).
    msg = MensajeWhatsApp.objects.create(
        conversacion=conv, remitente=sesion.numero, mensaje=persistido_text,
        tipo='texto', fecha=ahora, mensaje_id_externo='',
        leido=True, fecha_leido=ahora, es_automatico=False,
    )
    # Broadcast al websocket del chat.
    try:
        cl = get_channel_layer()
        if cl:
            async_to_sync(cl.group_send)(
                f'chat_{conv.id}',
                {'type': 'whatsapp_message', 'event': 'new_message',
                 'conversation_id': conv.id, 'sender': sesion.numero,
                 'timestamp': ahora.isoformat()},
            )
    except Exception:
        pass

    log(f"Menú rápido '{menu.nombre}' enviado a conv {conv.id}",
        request, "change", obj=conv.id)
    return JsonResponse({
        'error': False, 'message': f'Menú "{menu.nombre}" enviado.',
        'mensaje_id': msg.id,
    })


def _accion_guardar_usuarios(request):
    try:
        pk = int(request.POST['pk'])
        sesion = SesionWhatsApp.objects.get(pk=pk, usuario=request.user)
        ids_usuarios = json.loads(request.POST.get('usuarios', '[]'))
        usuarios_creados = []
        for uid in ids_usuarios:
            usuario = Usuario.objects.get(pk=uid)
            ya_existe = PerfilSesionWhatsApp.objects.filter(sesion=sesion, usuario=usuario, status=True).exists()
            if not ya_existe:
                relacion = PerfilSesionWhatsApp.objects.create(sesion=sesion, usuario=usuario)
                usuarios_creados.append({
                    'id': usuario.id,
                    'id_relacion': relacion.id,
                    'nombre': usuario.full_name(),
                    'documento': usuario.documento,
                    'email': usuario.email,
                    'telcelular': usuario.telcelular,
                    'foto': usuario.foto.url if usuario.foto else '',
                })
        log(f"Usuarios asignados a sesión {sesion.id}", request, "change", obj=sesion.id)
        return JsonResponse({'result': True, 'usuarios': usuarios_creados})
    except Exception as ex:
        return JsonResponse({'result': False, 'message': str(ex)})


def _accion_eliminar_usuario(request):
    try:
        filtro = PerfilSesionWhatsApp.objects.get(pk=int(request.POST['id']))
        filtro.status = False
        filtro.save(request)
        log(f"Usuario removido de sesión {filtro.sesion_id if filtro.sesion_id else '?'}", request, "del", obj=filtro.id)
        return JsonResponse({'error': False})
    except Exception as ex:
        return JsonResponse({'error': True, 'message': str(ex)})


_ACCIONES = {
    'baileys_start':               _accion_baileys_start,
    'baileys_status':              _accion_baileys_status,
    'baileys_verificar':           _accion_baileys_verificar,
    'disconnect':                  _accion_disconnect,
    'delete':                      _accion_delete,
    'meta_validar':                _accion_meta_validar,
    'meta_test_credenciales':      _accion_meta_test_credenciales,
    'meta_actualizar_credenciales': _accion_meta_actualizar_credenciales,
    'meta_plantilla_prueba':       _accion_meta_plantilla_prueba,
    'editar':                      _accion_editar,
    'toggle_activo':               _accion_toggle_activo,
    'menu_rapido_listar':          _accion_menu_rapido_listar,
    'menu_rapido_guardar':         _accion_menu_rapido_guardar,
    'menu_rapido_eliminar':        _accion_menu_rapido_eliminar,
    'menu_rapido_enviar':          _accion_menu_rapido_enviar,
    'guardar_usuarios':            _accion_guardar_usuarios,
    'eliminar_usuario':            _accion_eliminar_usuario,
}


def _get_partial(request, accion):
    """Renderiza un modal secundario (editar / historial / resumen / plantilla)
    y devuelve JSON con el HTML. Lo consume JS via fetch para inyectar el
    contenido al contenedor #conex-detail-modal.
    """
    sesion = SesionWhatsApp.objects.filter(id=request.GET.get('pk'), usuario=request.user).first()
    if not sesion:
        return JsonResponse({'ok': False, 'message': 'Sesion no encontrada.'})

    ctx = {'sesion': sesion, 'request': request}

    if accion == 'editar_modal':
        from crm.models import AgentesIA, PerfilNegocioIA, DepartamentoChatBot
        perfil, _ = PerfilNegocioIA.objects.get_or_create(usuario=request.user)
        ctx['agentes_disponibles'] = AgentesIA.objects.filter(perfil=perfil, status=True).order_by('nombre')
        # Departamentos disponibles para modos 'tradicional' y 'hibrido'.
        # Activos primero, luego por nombre.
        ctx['departamentos_disponibles'] = DepartamentoChatBot.objects.filter(
            status=True
        ).order_by('-es_default', 'nombre')
        ctx['sesion_departamento_ids'] = list(sesion.departamentos.values_list('id', flat=True))
        tpl = 'whatsapp/sesiones/_modal_editar.html'

    elif accion == 'datos_transporte_modal':
        # Read-only: datos técnicos de la conexión separados del editor.
        if sesion.es_meta:
            ctx['config_meta'] = getattr(sesion, 'config_meta', None)
        ctx['config_instagram'] = getattr(sesion, 'config_instagram', None)
        ctx['config_messenger'] = getattr(sesion, 'config_messenger', None)
        tpl = 'whatsapp/sesiones/_modal_datos_transporte.html'

    elif accion == 'historial_modal':
        from django.contrib.admin.models import LogEntry
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(SesionWhatsApp)
        ctx['entries'] = LogEntry.objects.filter(
            content_type=ct, object_id=str(sesion.id),
        ).order_by('-action_time')[:80]
        tpl = 'whatsapp/sesiones/_modal_historial.html'

    elif accion == 'resumen_modal':
        cfg = getattr(sesion, 'config_meta', None)
        checks = []
        if sesion.es_meta:
            checks.append({'nombre': 'Credenciales Cloud API',
                           'ok': bool(cfg and cfg.waba_id and cfg.phone_number_id and cfg.access_token),
                           'detalle': f'WABA {cfg.waba_id} · {cfg.display_phone_number or cfg.phone_number_id}' if cfg and cfg.waba_id else 'Sin credenciales Meta.'})
            checks.append({'nombre': 'Webhook verificado',
                           'ok': bool(cfg and cfg.webhook_verificado_en),
                           'detalle': f'Verificado {cfg.webhook_verificado_en:%Y-%m-%d %H:%M}' if cfg and cfg.webhook_verificado_en else 'Meta aun no valido el verify_token.'})
            checks.append({'nombre': 'Quality rating',
                           'ok': bool(cfg and cfg.quality_rating in ('GREEN', 'YELLOW')),
                           'detalle': cfg.get_quality_rating_display() if cfg else 'Desconocida'})
            from .models import PlantillaWhatsApp
            n_pl = PlantillaWhatsApp.objects.filter(config_meta=cfg, estado_meta='APPROVED', status=True).count() if cfg else 0
            checks.append({'nombre': 'Plantillas aprobadas',
                           'ok': n_pl > 0,
                           'detalle': f'{n_pl} aprobada(s).' if n_pl else 'Sin plantillas aprobadas.'})
        else:
            checks.append({'nombre': 'Socket Baileys',
                           'ok': sesion.estado == 'conectado',
                           'detalle': f'Estado actual: {sesion.get_estado_display()}.'})
        checks.append({'nombre': 'Agente IA',
                       'ok': bool(sesion.agente_ia),
                       'detalle': f'Agente: {sesion.agente_ia.nombre}' if sesion.agente_ia else 'Sin agente — no responde automatico.'})
        checks.append({'nombre': 'Horarios',
                       'ok': sesion.horarios.filter(status=True, activo=True).exists(),
                       'detalle': f'{sesion.horarios.filter(status=True, activo=True).count()} franja(s) activa(s).'})
        checks.append({'nombre': 'Campañas',
                       'ok': sesion.campanas.filter(status=True).exists(),
                       'detalle': f'{sesion.campanas.filter(status=True).count()} creada(s).'})
        total_ok = sum(1 for c in checks if c['ok'])
        ctx['checks'] = checks
        ctx['total_ok'] = total_ok
        ctx['total'] = len(checks)
        ctx['pct'] = int(100 * total_ok / len(checks)) if checks else 0
        tpl = 'whatsapp/sesiones/_modal_resumen.html'

    elif accion == 'plantilla_modal':
        from .models import PlantillaWhatsApp
        cfg = getattr(sesion, 'config_meta', None)
        ctx['plantillas'] = PlantillaWhatsApp.objects.filter(
            config_meta=cfg, estado_meta='APPROVED', status=True,
        ).order_by('nombre') if cfg else []
        tpl = 'whatsapp/sesiones/_modal_plantilla_prueba.html'

    else:
        return JsonResponse({'ok': False, 'message': 'Partial desconocido.'})

    html = get_template(tpl).render(ctx, request)
    return JsonResponse({'ok': True, 'html': html})


# ============================================================================
# View top-level
# ============================================================================

@login_required
@secure_module
def sesionesView(request):
    if request.method == 'POST':
        fn = _ACCIONES.get(request.POST.get('action', ''))
        if not fn:
            return JsonResponse({'error': True, 'message': 'Accion desconocida.'})
        try:
            return fn(request)
        except Exception as ex:
            logger.exception("Error en accion sesiones %s: %s", request.POST.get('action'), ex)
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    # GET partials (modales que se cargan bajo demanda)
    accion_get = request.GET.get('action') or ''
    if accion_get.endswith('_modal'):
        return _get_partial(request, accion_get)

    if accion_get == 'usuarios':
        try:
            pk = int(request.GET.get('id') or 0)
            sesion = SesionWhatsApp.objects.filter(id=pk, usuario=request.user).first()
            if not sesion:
                return JsonResponse({'result': False, 'message': 'Sesión no encontrada.'})
            html = get_template('whatsapp/sesiones/_modal_usuarios.html').render(
                {'sesion': sesion, 'filtro': sesion, 'request': request},
                request,
            )
            return JsonResponse({'result': True, 'data': html})
        except Exception as ex:
            return JsonResponse({'result': False, 'message': str(ex)})

    if accion_get == 'buscarpersonas':
        q = (request.GET.get('q') or '').upper().strip()
        qs = Usuario.objects.filter(status=True, is_active=True).order_by('last_name')
        if q:
            partes = q.split(' ')
            if len(partes) == 1:
                qs = qs.filter(
                    Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(documento__icontains=q)
                ).distinct()[:15]
            elif len(partes) >= 2:
                qs = qs.filter(
                    Q(last_name__icontains=partes[0]) | Q(first_name__icontains=partes[1])
                ).distinct()[:15]
        else:
            qs = qs[:15]
        results = [{
            'id': u.id,
            'text': u.full_name(),
            'documento': u.documento or '',
            'foto': u.foto.url if u.foto else '',
        } for u in qs]
        return JsonResponse({'results': results, 'total_count': len(results)})

    # GET: tablero
    data = {
        'titulo':      'Canales conectados',
        'descripcion': 'Gestiona todas tus integraciones de mensajeria en un solo tablero.',
        'ruta':        request.path,
    }
    addData(request, data)

    criterio = (request.GET.get('criterio') or '').strip()
    filtros = Q(status=True, usuario=request.user)
    if criterio:
        filtros &= (Q(nombre__icontains=criterio) | Q(numero__icontains=criterio))

    sesiones = SesionWhatsApp.objects.filter(filtros).select_related('config_meta').order_by('-fecha_registro')
    data['sesiones'] = sesiones
    data['total']    = sesiones.count()

    stats = sesiones.aggregate(
        conectadas=Count('id', filter=Q(estado='conectado')),
        pendientes=Count('id', filter=Q(estado='pendiente')),
        desconectadas=Count('id', filter=Q(estado='desconectado')),
        errores=Count('id', filter=Q(estado='error')),
    )
    data['stats'] = stats
    data['criterio'] = criterio

    # Flag para mostrar/esconder el boton "Continuar" del panel WhatsApp.
    # Tres modos posibles:
    #   - 'oauth'   → Tech Provider activo + config_id cargado → popup Embedded Signup
    #   - 'manual'  → sin Tech Provider → form de carga manual de WABA + Phone + token
    #   - 'sin_credenciales' → falta app_id/app_secret → mostrar alert para ir al form
    from .common_meta import get_meta_app_credentials
    from seguridad.models import Configuracion as _Conf, CredencialMetaApp as _Cred
    _app_id, _app_secret = get_meta_app_credentials()
    _confi = _Conf.get_instancia()
    _cred = _Cred.objects.filter(configuracion=_confi).first() if _confi and _confi.pk else None
    _es_tp = bool(_cred and _cred.es_tech_provider)
    if not (_app_id and _app_secret):
        data['meta_modo'] = 'sin_credenciales'
    elif _es_tp:
        data['meta_modo'] = 'oauth'
    else:
        data['meta_modo'] = 'manual'
    data['meta_oauth_listo'] = (data['meta_modo'] == 'oauth')
    data['meta_manual_listo'] = (data['meta_modo'] == 'manual')
    # Deep-links a Meta Business: si tenemos business_id cargado, lo
    # inyectamos como query param para que Meta abra directo el contexto
    # correcto (sin pasar por el selector de Business).
    data['meta_business_id'] = (_cred.business_id if _cred else '') or ''

    # Canales activos: controlan visibilidad del sidebar + paneles del modal
    # "Agregar conexion". Se administran en /seguridad/configuracion/.
    from seguridad.models import Configuracion
    confi = Configuracion.get_instancia()
    data['canales_activos'] = {
        'whatsapp_qr':  bool(getattr(confi, 'canal_whatsapp_qr_activo', True)),
        'whatsapp_api': bool(getattr(confi, 'canal_whatsapp_api_activo', True)),
        'instagram':    bool(getattr(confi, 'canal_instagram_activo', False)),
        'messenger':    bool(getattr(confi, 'canal_messenger_activo', False)),
        'tiktok':       bool(getattr(confi, 'canal_tiktok_activo', False)),
    }

    # Partial card refresh (AJAX poll desde el tablero)
    if request.GET.get('partial') == 'card':
        sesion_id = request.GET.get('id')
        sesion = sesiones.filter(id=sesion_id).first()
        if not sesion:
            return JsonResponse({'error': True})
        html = get_template('whatsapp/sesiones/_card.html').render({'sesion': sesion}, request)
        return JsonResponse({'error': False, 'estado': sesion.estado, 'html': html})

    return render(request, 'whatsapp/sesiones/tablero.html', data)
