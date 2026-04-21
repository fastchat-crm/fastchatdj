"""Vista + acciones dedicadas a sesiones Baileys (WhatsApp Web via Node.js).

URL: /whatsapp/sesiones/baileys/

Este archivo es autonomo para la logica Baileys:
- Todas las acciones POST especificas de Baileys viven aca como funciones.
- `sesionesBaileysView` es la vista Django registrada en urls.py.
- El dispatcher `handle_baileys_action(request, action)` permite que el view
  legacy `sesionesView` delegue aqui sin duplicar codigo.

Si estas trabajando solo con Baileys, en este archivo tenes todo lo que necesitas.
Las acciones comunes (probar_envio_mensaje, change, change_modal, regla_fin_*)
quedan en `sesiones_view.py` porque sirven para ambos proveedores.
"""
from __future__ import annotations

import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse

from core.funciones import log, secure_module

from .models import SesionWhatsApp
from .services import WhatsAppService

logger = logging.getLogger(__name__)


# ============================================================================
# Acciones POST (Baileys)
# ============================================================================

def accion_add(request):
    """Crea (o reusa) una sesion Baileys placeholder pendiente de QR."""
    last_session_id = request.POST.get('last_session_id') or 0
    last_session = SesionWhatsApp.objects.filter(id=last_session_id).first()
    session = last_session or SesionWhatsApp.objects.create(
        estado='pendiente', usuario=request.user,
        session_id=str(uuid.uuid4()), qr_code='', whatsapp_id='',
    )
    session.qr_code = ''
    log(f"Inicio de sesion WhatsApp pendiente (ID: {session.id})", request, "add", obj=session.id)
    return JsonResponse({'error': False, 'qr': session.qr_code, 'session_id': session.id}, safe=False)


def accion_create_session(request):
    """Dispara la creacion del socket Baileys en Node y devuelve el QR."""
    whatsapp_service = WhatsAppService()
    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
    session_id = request.POST['session_id']
    session = SesionWhatsApp.objects.get(id=session_id)
    rotar = (request.POST.get('reset') == '1') or session.estado in ('desconectado', 'error')
    logger.warning("CREATE_SESSION id=%s sessionId=%s estado=%s rotar=%s",
                   session.id, session.session_id, session.estado, rotar)
    if rotar:
        old_uuid = session.session_id
        try:
            close_res = whatsapp_service.close_session(old_uuid)
            logger.warning("CREATE_SESSION close_session(%s) result=%s", old_uuid, close_res)
        except Exception as _ex:
            logger.warning("CREATE_SESSION close_session(%s) excepcion=%s", old_uuid, _ex)
        new_uuid = str(uuid.uuid4())
        session.session_id = new_uuid
        session.qr_code = ''
        session.whatsapp_id = ''
        session.estado = 'pendiente'
        session.error_mensaje = None
        session.save(update_fields=['session_id', 'qr_code', 'whatsapp_id', 'estado', 'error_mensaje'])
        logger.warning("CREATE_SESSION rotado %s → %s (Django id=%s)", old_uuid, new_uuid, session.id)
    result = whatsapp_service.create_session(session, webhook_url)
    logger.warning("CREATE_SESSION create_session result=%s", result)
    if not result.get('success'):
        error_detalle = result.get('error') or 'No se pudo crear la sesion en el servicio Node.js'
        session.estado = 'error'
        session.error_mensaje = error_detalle[:500]
        session.save(update_fields=['estado', 'error_mensaje'])
        log(f"Fallo create_session ID={session.id}: {error_detalle}", request, "create_session", obj=session.id)
        return JsonResponse({'error': True, 'message': error_detalle, 'session_id': session.id}, safe=False)
    session.qr_code = result.get('qr_code') or ''
    session.save(update_fields=['qr_code'])
    log(f"Crear sesion WhatsApp pendiente (ID: {session.id})", request, "create_session", obj=session.id)
    return JsonResponse({'error': False, 'qr': session.qr_code, 'session_id': session.id}, safe=False)


def accion_verificar_conexion(request):
    """Pinguea Node para confirmar que el socket Baileys esta vivo."""
    whatsapp_service = WhatsAppService()
    filtro = SesionWhatsApp.objects.get(pk=int(request.POST['id']))
    if not filtro.es_baileys:
        return JsonResponse({'error': True, 'message': 'Verificar conexion solo aplica para sesiones Baileys. Para Meta usa "Verificar conexion con Meta" en el formulario.'})
    if not filtro.session_id:
        return JsonResponse({'error': True, 'message': 'La sesion no tiene session_id asignado.'})
    result = whatsapp_service.check_session_status(filtro.session_id)
    if not result.get('success'):
        if result.get('not_found') and filtro.estado == 'conectado':
            filtro.estado = 'desconectado'
            filtro.error_mensaje = 'Sesion no existe en el servidor de WhatsApp'
            filtro.save()
            log(f"Verificacion: sesion {filtro.id} no existe en Node — marcada como desconectada", request, "change", obj=filtro.id)
        return JsonResponse({
            'error': True, 'connected': False,
            'message': result.get('error') or 'No se pudo verificar la sesion',
        })
    connected = result.get('connected')
    estado_previo = filtro.estado
    if connected and filtro.estado != 'conectado':
        filtro.estado = 'conectado'
        filtro.error_mensaje = None
        filtro.save()
        log(f"Verificacion: sesion {filtro.id} esta realmente conectada — estado actualizado", request, "change", obj=filtro.id)
    elif not connected and filtro.estado == 'conectado':
        filtro.estado = 'desconectado'
        filtro.error_mensaje = 'Conexion con WhatsApp perdida (detectado por verificacion manual)'
        filtro.save()
        log(f"Verificacion: sesion {filtro.id} reportaba conectada pero el socket esta caido — marcada como desconectada", request, "change", obj=filtro.id)
    return JsonResponse({
        'error': False, 'connected': connected,
        'is_active':    result.get('is_active'),
        'estado':       filtro.estado,
        'estado_previo': estado_previo,
        'last_activity': result.get('last_activity'),
        'message': ('Conexion activa con WhatsApp.' if connected
                    else 'La sesion no tiene conexion real con WhatsApp.'),
    })


def accion_reconectar(request):
    """Rota el UUID + recrea el socket Baileys (mantiene Django.id intacto)."""
    whatsapp_service = WhatsAppService()
    filtro = SesionWhatsApp.objects.get(pk=int(request.POST['id']))
    if not filtro.es_baileys:
        return JsonResponse({'error': True, 'message': 'Reconectar solo aplica para sesiones Baileys.'})
    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
    logger.warning("RECONECTAR id=%s sessionId=%s estado=%s", filtro.id, filtro.session_id, filtro.estado)
    old_uuid = filtro.session_id
    try:
        close_res = whatsapp_service.close_session(old_uuid)
        logger.warning("RECONECTAR close_session(%s) result=%s", old_uuid, close_res)
    except Exception as _ex:
        logger.warning("RECONECTAR close_session(%s) excepcion=%s", old_uuid, _ex)
    new_uuid = str(uuid.uuid4())
    filtro.session_id = new_uuid
    filtro.qr_code = ''
    filtro.whatsapp_id = ''
    filtro.estado = 'pendiente'
    filtro.error_mensaje = None
    filtro.desconectado_manualmente = False
    filtro.save(update_fields=['session_id', 'qr_code', 'whatsapp_id', 'estado', 'error_mensaje', 'desconectado_manualmente'])
    logger.warning("RECONECTAR rotado %s → %s (Django id=%s)", old_uuid, new_uuid, filtro.id)
    result = whatsapp_service.create_session(filtro, webhook_url)
    logger.warning("RECONECTAR create_session result=%s", result)
    if result.get('success'):
        filtro.estado = 'pendiente'
        filtro.error_mensaje = None
        filtro.desconectado_manualmente = False
        if result.get('qr_code'):
            filtro.qr_code = result['qr_code']
        filtro.save(update_fields=['estado', 'error_mensaje', 'desconectado_manualmente', 'qr_code'])
        log(f"Sesion {filtro.id} reconectada manualmente", request, "change", obj=filtro.id)
        return JsonResponse({'error': False, 'qr': filtro.qr_code or '',
                             'message': 'Reconexion iniciada. Escanea el QR si es necesario.'})
    return JsonResponse({'error': True, 'message': result.get('error') or 'No se pudo reconectar'})


def accion_delete(request):
    """Cierra el socket Baileys en Node y marca la sesion como desconectada
    manualmente (asi el cron no intenta reconectarla automaticamente)."""
    whatsapp_service = WhatsAppService()
    filtro = SesionWhatsApp.objects.get(pk=int(request.POST['id']))
    if not filtro.es_baileys:
        return JsonResponse({'error': True, 'message': 'Desconectar solo aplica para sesiones Baileys. Las sesiones Meta se gestionan desde el panel de Meta.'})
    result = whatsapp_service.close_session(filtro.session_id)
    if 'success' in result and not result['success']:
        raise NameError(result['error'])
    filtro.estado = 'desconectado'
    filtro.error_mensaje = None
    filtro.desconectado_manualmente = True
    filtro.save()
    log(f"Sesion de WhatsApp {filtro.numero} desconectada", request, "del", obj=filtro.id)
    messages.success(request, "Sesion desconectada correctamente.")
    return JsonResponse({"error": False})


# ---------- Dispatcher compartido ----------

_BAILEYS_ACTIONS = {
    'add':                accion_add,
    'create_session':     accion_create_session,
    'verificar_conexion': accion_verificar_conexion,
    'reconectar':         accion_reconectar,
    'delete':             accion_delete,
}


def handle_baileys_action(request, action):
    """Devuelve JsonResponse si la accion es Baileys, None si no es manejada."""
    fn = _BAILEYS_ACTIONS.get(action)
    if not fn:
        return None
    try:
        with transaction.atomic():
            return fn(request)
    except Exception as ex:
        logger.exception("Error en accion Baileys %s: %s", action, ex)
        return JsonResponse([{'error': True, 'message': f'Error: {ex}'}], safe=False)


# ============================================================================
# Vista top-level
# ============================================================================

@login_required
@secure_module
def sesionesBaileysView(request):
    """Vista top-level Baileys. POST Baileys-only se atiende aca; GET filtra
    listado a proveedor=baileys; el resto delega al legacy."""
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action in _BAILEYS_ACTIONS:
            resp = handle_baileys_action(request, action)
            if resp is not None:
                return resp
        # Acciones comunes (probar_envio_mensaje, change, change_modal, regla_fin_*)
        # las maneja el view legacy.
        from .sesiones_view import sesionesView
        return sesionesView(request)

    # GET: pre-filtrar listado a Baileys
    if 'proveedor' not in request.GET:
        request.GET = request.GET.copy()
        request.GET['proveedor'] = 'baileys'
    from .sesiones_view import sesionesView
    return sesionesView(request)
