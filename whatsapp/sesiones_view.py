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

from .models import SesionWhatsApp, ConfigBaileys
from .services import WhatsAppService


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
    return JsonResponse({
        'error': False,
        'message': info.get('message'),
        'numero': sesion.numero,
        'estado': sesion.estado,
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


def _accion_editar(request):
    """Guarda cambios del modal "Modificar": campos basicos de la sesion."""
    sesion = SesionWhatsApp.objects.filter(id=request.POST.get('id'), usuario=request.user).first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'Sesion no encontrada.'})
    nombre = (request.POST.get('nombre') or '').strip()
    if not nombre:
        return JsonResponse({'error': True, 'message': 'El nombre es obligatorio.'})
    sesion.nombre = nombre
    sesion.modo_bot = request.POST.get('modo_bot') or sesion.modo_bot
    sesion.language = request.POST.get('language') or sesion.language
    sesion.zona_horaria = (request.POST.get('zona_horaria') or sesion.zona_horaria).strip()
    sesion.mensaje_bienvenida = (request.POST.get('mensaje_bienvenida') or '').strip() or None
    sesion.mensaje_despedida   = (request.POST.get('mensaje_despedida')   or '').strip() or None
    sesion.mensaje_handoff     = (request.POST.get('mensaje_handoff')     or '').strip() or None
    # Agente IA (opcional — llega como id o vacio)
    agente_id = request.POST.get('agente_ia') or ''
    if agente_id.isdigit():
        from crm.models import AgentesIA
        agente = AgentesIA.objects.filter(id=int(agente_id), status=True).first()
        sesion.agente_ia = agente
    elif agente_id == '':
        sesion.agente_ia = None
    sesion.save()
    log(f"Sesion {sesion.id} editada", request, "change", obj=sesion.id)
    return JsonResponse({'error': False, 'message': 'Cambios guardados.', 'reload': True})


_ACCIONES = {
    'baileys_start':               _accion_baileys_start,
    'baileys_status':              _accion_baileys_status,
    'baileys_verificar':           _accion_baileys_verificar,
    'disconnect':                  _accion_disconnect,
    'delete':                      _accion_delete,
    'meta_validar':                _accion_meta_validar,
    'meta_plantilla_prueba':       _accion_meta_plantilla_prueba,
    'editar':                      _accion_editar,
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
        from crm.models import AgentesIA, PerfilNegocioIA
        perfil, _ = PerfilNegocioIA.objects.get_or_create(usuario=request.user)
        ctx['agentes_disponibles'] = AgentesIA.objects.filter(perfil=perfil, status=True).order_by('nombre')
        tpl = 'whatsapp/sesiones/_modal_editar.html'

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

    # Flag para mostrar/esconder el boton "Continuar" del panel WhatsApp
    from django.conf import settings
    from .common_meta import get_meta_app_credentials
    _app_id, _app_secret = get_meta_app_credentials()
    data['meta_oauth_listo'] = bool(_app_id and _app_secret and settings.META_CONFIG_ID)

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
