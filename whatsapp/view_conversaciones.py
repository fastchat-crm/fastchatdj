import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.db.models import Q, Sum
from django.contrib import messages
from django.template.loader import render_to_string, get_template
from django.utils import timezone
from django.http import JsonResponse

from autenticacion.models import Usuario
from core.funciones import addData, paginador, secure_module, log, leer_sesion_id, encrypt_sesion_id, decrypt_sesion_id
from seguridad.templatetags.templatefunctions import encrypt
from .forms import CambiarClasificacionForm, CambiarNombreContactoForm, AsignarAgenteForm
from .funcionesWhatsappConversacion import (
    cambiar_clasificacion_get,
    cambiar_clasificacion_post,
    cambiar_nombre_contacto_get,
    cambiar_nombre_contacto_post,
    historial_cliente_list,
    historial_cliente_mensajes,
    persistir_y_difundir_automatico as _persistir_y_difundir_automatico,
    _bloqueo_reactivar,
    _control_respuestas,
    _estadisticas_conversacion,
    _tokens_conversacion,
    HORAS_VENTANA_REACTIVAR,
)
from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp, SENTIMIENTO_CHOICES, RespuestaRapidaGlobal
from .services import WhatsAppService, get_whatsapp_service
from .permisos_sesion import (
    sesiones_visibles,
    sesiones_vista_completa,
    rol_en_sesion,
    filtro_conversaciones_por_rol,
    puede_ver_conversacion,
    es_vista_completa,
)


def _clientes_de_conversacion(conv):
    """Devuelve los Clientes (CRM) registrados desde ESTA conversación.

    Estricto por conversación: solo matchea conversacion_origen /
    origenes.conversacion = esta conversación. Una conversación puede registrar
    varios clientes (el titular inscribe a otras personas), pero clientes del
    mismo contacto registrados en conversaciones anteriores NO se muestran acá
    — para eso está la ficha completa del CRM.
    """
    from crm.models import Cliente

    cond = Q(conversacion_origen=conv) | Q(origenes__conversacion=conv)

    return list(
        Cliente.objects.filter(cond, status=True)
        .distinct()
        .prefetch_related('origenes__sesion', 'origenes__departamento')
    )


def _prefill_ficha_cliente(conv):
    """Sugiere valores para el alta manual de Cliente a partir de las variables
    capturadas por el flujo del chatbot tradicional + datos del contacto.

    Devuelve (prefill, variables_flujo). Cubre el caso de un cliente que NO
    terminó el flujo: el operador completa la ficha con lo que el bot alcanzó a
    capturar ya precargado.
    """
    from datetime import datetime
    import re

    estado = getattr(conv, 'estado_flujo', None)
    variables_flujo = (getattr(estado, 'variables', None) or {}) if estado else {}

    norm = {}
    for k, v in variables_flujo.items():
        if v in (None, ''):
            continue
        norm[str(k).strip().lower()] = str(v).strip()

    def primero(*claves):
        for c in claves:
            if norm.get(c):
                return norm[c]
        return ''

    def _fecha_iso(valor):
        valor = (valor or '').strip()
        if not valor:
            return ''
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(valor, fmt).date().isoformat()
            except ValueError:
                continue
        return ''

    contacto = getattr(conv, 'contacto', None)
    nombre_contacto = ''
    telefono_contacto = ''
    if contacto:
        nombre_contacto = (getattr(contacto, 'contacto_nombre', '') or '').strip()
        telefono_contacto = (
            (getattr(contacto, 'numero_telefono', '') or '')
            or (getattr(contacto, 'contacto_numero', '') or '')
        ).strip()

    edad_raw = primero('edad', 'driver_age', 'age')
    edad_digitos = ''.join(re.findall(r'\d', edad_raw))[:3]

    prefill = {
        'cedula':           primero('cedula', 'identificacion', 'documento', 'dni', 'ci'),
        'nombres':          primero('nombres', 'nombre', 'nombre_cliente', 'first_name') or nombre_contacto,
        'apellidos':        primero('apellidos', 'apellido', 'last_name'),
        'email':            primero('email', 'correo', 'correo_electronico'),
        'telefono':         primero('telefono', 'celular', 'whatsapp', 'phone') or telefono_contacto,
        'ciudad':           primero('ciudad', 'city'),
        'edad':             edad_digitos,
        'fecha_nacimiento': _fecha_iso(primero('fecha_nacimiento', 'fecha_nac', 'nacimiento')),
        'sexo':             (primero('sexo', 'genero', 'gender')[:1] or '').upper(),
    }
    if prefill['sexo'] not in ('M', 'F'):
        prefill['sexo'] = ''
    return prefill, variables_flujo


def _reenviar_mensaje(request):
    """Reenvía un mensaje saliente que quedó en estado 'fallido'.
    Provider-agnostic: reusa el servicio de la sesión (Baileys o Meta)."""
    try:
        msg_id = int(request.POST.get('id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': True, 'message': 'ID inválido'})

    mensaje = (
        MensajeWhatsApp.objects
        .select_related('conversacion__sesion', 'conversacion__contacto')
        .filter(pk=msg_id).first()
    )
    if not mensaje:
        return JsonResponse({'error': True, 'message': 'Mensaje no encontrado'})

    conversacion = mensaje.conversacion
    sesion = conversacion.sesion
    if not puede_ver_conversacion(request.user, conversacion):
        return JsonResponse({'error': True, 'message': 'No autorizado.'})
    if mensaje.remitente != (sesion.numero or '') or mensaje.estado_envio != 'fallido':
        return JsonResponse({'error': True, 'message': 'Solo se reenvían mensajes salientes fallidos.'})

    from .funcionesWhatsappConversacion import _bloqueo_ventana_meta
    meta_bloqueada, _vence = _bloqueo_ventana_meta(conversacion)
    if meta_bloqueada:
        return JsonResponse({
            'error': True, 'requiere_plantilla': True,
            'message': 'La ventana de 24h de Meta venció. Usa una plantilla aprobada.',
        })

    service = get_whatsapp_service(sesion)
    media_map = {'imagen': 'image', 'audio': 'audio', 'video': 'video', 'documento': 'document'}
    try:
        if mensaje.tipo in media_map and mensaje.archivo:
            mensaje.archivo.open('rb')
            file_bytes = mensaje.archivo.read()
            mensaje.archivo.close()
            response = service.send_media_message(
                sesion.session_id, conversacion.from_number, caption=mensaje.mensaje,
                file_content=file_bytes, filename=mensaje.archivo.name.split('/')[-1],
                media_type=media_map[mensaje.tipo], conversacion_id=conversacion.id,
            )
        else:
            response = service.send_text_message(
                sesion.session_id, conversacion.from_number, mensaje.mensaje,
                conversacion_id=conversacion.id,
            )
    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error al reenviar: {ex}'})

    if not response.get('success', False):
        return JsonResponse({
            'error': True,
            'message': f"No se pudo reenviar: {response.get('error', 'Error desconocido')}",
            'requiere_plantilla': bool(response.get('requiere_plantilla')),
            'cuenta_degradada': bool(response.get('cuenta_degradada')),
        })

    mensaje.mensaje_id_externo = response.get('message_id') or mensaje.mensaje_id_externo
    mensaje.estado_envio = 'enviado'
    mensaje.error_envio = ''
    mensaje.save(update_fields=['mensaje_id_externo', 'estado_envio', 'error_envio'])
    return JsonResponse({
        'error': False,
        'mensaje_html': render_to_string(
            'whatsapp/conversaciones/mensaje_enviado_partial.html',
            {'mensaje': mensaje}, request=request),
    })


def _editar_eliminar_mensaje(request, action):
    """Edita o elimina (revoke) un mensaje saliente. Solo sesiones Baileys —
    Meta Cloud API no expone editar/eliminar."""
    try:
        msg_id = int(request.POST.get('id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': True, 'message': 'ID inválido'})
    mensaje = (
        MensajeWhatsApp.objects
        .select_related('conversacion__sesion', 'conversacion__contacto')
        .filter(pk=msg_id).first()
    )
    if not mensaje:
        return JsonResponse({'error': True, 'message': 'Mensaje no encontrado'})
    conversacion = mensaje.conversacion
    sesion = conversacion.sesion
    if not puede_ver_conversacion(request.user, conversacion):
        return JsonResponse({'error': True, 'message': 'No autorizado.'})
    if not getattr(sesion, 'es_baileys', False):
        return JsonResponse({'error': True, 'message': 'Editar/eliminar solo está disponible en sesiones Baileys. Meta no lo permite.'})
    if mensaje.remitente != (sesion.numero or ''):
        return JsonResponse({'error': True, 'message': 'Solo se editan/eliminan mensajes propios (salientes).'})
    if mensaje.eliminado:
        return JsonResponse({'error': True, 'message': 'El mensaje ya fue eliminado.'})
    if not mensaje.mensaje_id_externo:
        return JsonResponse({'error': True, 'message': 'El mensaje no tiene id externo de WhatsApp — no se puede modificar.'})

    service = get_whatsapp_service(sesion)
    if action == 'editar_mensaje':
        nuevo = (request.POST.get('texto') or '').strip()
        if not nuevo:
            return JsonResponse({'error': True, 'message': 'El nuevo texto no puede estar vacío.'})
        resp = service.edit_message(sesion.session_id, conversacion.from_number, mensaje.mensaje_id_externo, nuevo)
        if not resp.get('success'):
            return JsonResponse({'error': True, 'message': resp.get('error', 'No se pudo editar.')})
        mensaje.mensaje = nuevo
        mensaje.editado = True
        mensaje.save(update_fields=['mensaje', 'editado'])
    else:
        resp = service.delete_message(sesion.session_id, conversacion.from_number, mensaje.mensaje_id_externo)
        if not resp.get('success'):
            return JsonResponse({'error': True, 'message': resp.get('error', 'No se pudo eliminar.')})
        mensaje.eliminado = True
        mensaje.save(update_fields=['eliminado'])

    return JsonResponse({
        'error': False,
        'mensaje_html': render_to_string(
            'whatsapp/conversaciones/mensaje_enviado_partial.html',
            {'mensaje': mensaje}, request=request),
    })


def _gestionar_atencion(request, action):
    """Estados de inbox (abierta/pendiente/resuelta) y snooze (posponer)."""
    from .models import ESTADOS_ATENCION
    try:
        pk = int(request.POST.get('pk') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': True, 'message': 'ID inválido'})
    conversacion = ConversacionWhatsApp.objects.filter(pk=pk).select_related('contacto__sesion').first()
    if not conversacion:
        return JsonResponse({'error': True, 'message': 'Conversación no encontrada'})
    if not puede_ver_conversacion(request.user, conversacion):
        return JsonResponse({'error': True, 'message': 'No autorizado.'})

    if action == 'cambiar_estado_atencion':
        estado = (request.POST.get('estado') or '').strip()
        validos = {v for v, _ in ESTADOS_ATENCION}
        if estado not in validos:
            return JsonResponse({'error': True, 'message': 'Estado inválido'})
        conversacion.estado_atencion = estado
        conversacion.save(update_fields=['estado_atencion'])
        return JsonResponse({'error': False, 'estado_atencion': estado})

    if action == 'posponer_conversacion':
        try:
            minutos = int(request.POST.get('minutos') or 60)
        except (TypeError, ValueError):
            minutos = 60
        minutos = max(1, min(minutos, 60 * 24 * 14))
        conversacion.snooze_hasta = timezone.now() + timezone.timedelta(minutes=minutos)
        conversacion.estado_atencion = 'pendiente'
        conversacion.save(update_fields=['snooze_hasta', 'estado_atencion'])
        return JsonResponse({'error': False, 'snooze_hasta': conversacion.snooze_hasta.isoformat()})

    # reabrir_conversacion
    conversacion.snooze_hasta = None
    conversacion.estado_atencion = 'abierta'
    conversacion.save(update_fields=['snooze_hasta', 'estado_atencion'])
    return JsonResponse({'error': False})


BRANDING_INBOX_CANAL = {
    None: {
        'titulo': 'Conversaciones WhatsApp',
        'nombre': 'WhatsApp',
        'icono': 'fab fa-whatsapp',
        'url_sesiones': '/whatsapp/sesiones/',
        'url_conversaciones': '/whatsapp/conversaciones/',
        'url_finalizadas': '/whatsapp/conversaciones-finalizadas/',
        'url_pendientes': '/whatsapp/conversaciones-pendiente-reconexion/',
        'tiene_pendientes': True,
        'vacio_titulo': 'Aún no hay sesiones de WhatsApp',
        'vacio_texto': 'Para ver conversaciones primero necesitás conectar al menos una sesión de WhatsApp.',
        'vacio_boton': 'Crear o conectar una sesión',
    },
    'instagram': {
        'titulo': 'Conversaciones Instagram',
        'nombre': 'Instagram',
        'icono': 'fab fa-instagram',
        'url_sesiones': '/instagram/sesiones/',
        'url_conversaciones': '/instagram/conversaciones/',
        'url_finalizadas': '/instagram/conversaciones-finalizadas/',
        'url_pendientes': '/instagram/conversaciones-pendiente-reconexion/',
        'tiene_pendientes': True,
        'vacio_titulo': 'Aún no hay sesiones de Instagram',
        'vacio_texto': 'Para ver conversaciones primero necesitás conectar al menos una cuenta de Instagram.',
        'vacio_boton': 'Conectar cuenta de Instagram',
    },
    'messenger': {
        'titulo': 'Conversaciones Messenger',
        'nombre': 'Facebook',
        'icono': 'fab fa-facebook',
        'url_sesiones': '/facebook/sesiones/',
        'url_conversaciones': '/facebook/conversaciones/',
        'url_finalizadas': '/facebook/conversaciones-finalizadas/',
        'url_pendientes': '',
        'tiene_pendientes': False,
        'vacio_titulo': 'Aún no hay páginas de Facebook',
        'vacio_texto': 'Para ver conversaciones primero necesitás conectar al menos una página de Facebook.',
        'vacio_boton': 'Conectar página de Facebook',
    },
    'tiktok': {
        'titulo': 'Conversaciones TikTok',
        'nombre': 'TikTok',
        'icono': 'fab fa-tiktok',
        'url_sesiones': '/tiktok/sesiones/',
        'url_conversaciones': '/tiktok/conversaciones/',
        'url_finalizadas': '/tiktok/conversaciones-finalizadas/',
        'url_pendientes': '',
        'tiene_pendientes': False,
        'vacio_titulo': 'Aún no hay sesiones de TikTok',
        'vacio_texto': 'Para ver conversaciones primero necesitás registrar al menos una cuenta de TikTok.',
        'vacio_boton': 'Registrar cuenta de TikTok',
    },
}


PROVEEDORES_WHATSAPP = ('baileys', 'meta')


def canal_conversacion_permitido(sesion, canal_fijo):
    """True si la sesión pertenece al canal del inbox actual. Sin canal_fijo
    (inbox WhatsApp) solo se aceptan proveedores WhatsApp — evita que
    conversaciones de Messenger/Instagram/TikTok se abran en el inbox de
    WhatsApp y viceversa (localStorage/contactoId compartidos entre canales)."""
    proveedor = getattr(sesion, 'proveedor', '') or ''
    if canal_fijo:
        return proveedor == canal_fijo
    return proveedor in PROVEEDORES_WHATSAPP


@login_required
@secure_module
def conversacionesView(request, canal_fijo=None, template='whatsapp/conversaciones/listado.html'):
    branding = BRANDING_INBOX_CANAL.get(canal_fijo, BRANDING_INBOX_CANAL[None])
    titulo = branding['titulo']
    data = {
        'titulo': titulo,
        'modulo': titulo,
        'ruta': request.path,
        'canal_fijo': canal_fijo or '',
        'canal_branding': branding,
    }
    addData(request, data)

    # Todas las sesiones visibles para el usuario (dueño, participante o superuser).
    # Con canal_fijo (wrappers /instagram/ y /tiktok/) el inbox queda acotado a
    # las sesiones de ese proveedor — mismo layout y acciones que WhatsApp.
    sesiones = sesiones_visibles(request.user).order_by('-ultima_conexion')
    if canal_fijo:
        sesiones = sesiones.filter(proveedor=canal_fijo)
    else:
        sesiones = sesiones.filter(proveedor__in=PROVEEDORES_WHATSAPP)
    data['sesiones'] = sesiones

    # Sesión seleccionada (por defecto la primera)
    sesion_id = leer_sesion_id(request)
    contactoId = request.session.pop('contactoId', None)
    conversacion_selected = None
    if contactoId:
        try:
            conversacion_selected = ConversacionWhatsApp.objects.get(pk=int(encrypt(contactoId)))
            if canal_conversacion_permitido(conversacion_selected.sesion, canal_fijo):
                sesion_id = conversacion_selected.sesion.id
            else:
                conversacion_selected = None
        except Exception as ex:
            raise NameError(f'No se encontró la conversación: {ex}')

    # Soporte deep-link `?conv=<token>` (usado por el correo del asesor de
    # cotización). Si la conversación está finalizada → redirigir a la página
    # de finalizadas con el mismo token. Si está activa → la marcamos para
    # auto-abrir vía JS y forzamos la sesión correcta en el combo.
    conv_token = (request.GET.get('conv') or '').strip()
    auto_open_conv_id = None
    if conv_token:
        conv_id_pedido = decrypt_sesion_id(conv_token, default=None)
        if conv_id_pedido:
            conv_obj = ConversacionWhatsApp.objects.filter(pk=conv_id_pedido).select_related(
                'contacto', 'contacto__sesion'
            ).first()
            if conv_obj and canal_conversacion_permitido(conv_obj.sesion, canal_fijo):
                if conv_obj.conversacion_finalizada:
                    return redirect(f"{branding['url_finalizadas']}?conv={conv_token}")
                auto_open_conv_id = conv_obj.id
                if conv_obj.contacto and conv_obj.contacto.sesion:
                    sesion_id = conv_obj.contacto.sesion.id
    if sesion_id:
        sesion_seleccionada = sesiones.filter(id=sesion_id).first()
        if not sesion_seleccionada and sesiones.exists():
            sesion_seleccionada = sesiones.first()
    elif sesiones.exists():
        sesion_seleccionada = sesiones.first()
    else:
        sesion_seleccionada = None

    data['sesion_seleccionada'] = sesion_seleccionada
    data['auto_open_conv_id'] = auto_open_conv_id
    rol_sesion = rol_en_sesion(request.user, sesion_seleccionada)
    data['rol_sesion'] = rol_sesion
    data['es_vista_completa'] = es_vista_completa(request.user, sesion_seleccionada)

    # ====================== VER MENSAJES =========================
    if request.method == 'GET' and 'action' in request.GET:
        data['action'] = action = request.GET['action']
        if action == 'ver_mensajes':
            try:
                pk = int(request.GET['pk'])
            except (KeyError, ValueError):
                return JsonResponse({'error': True, 'message': 'Parámetro pk inválido.'})
            conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
            if not puede_ver_conversacion(request.user, conversacion):
                return JsonResponse({'error': True, 'message': 'Not authorized.'})
            if not canal_conversacion_permitido(conversacion.sesion, canal_fijo):
                return JsonResponse({'error': True, 'canal_invalido': True,
                                     'message': 'La conversación no pertenece a este canal.'})
            mensajes = MensajeWhatsApp.objects.filter(conversacion=conversacion).order_by('fecha')
            data['conversacion'] = conversacion
            data['mensajes'] = mensajes
            # Atribución: si la conv tiene referral (Click-to-WhatsApp ad),
            # mandamos un payload compacto al frontend para mostrar un badge
            # en el chat header. El operador ve de qué anuncio vino el lead.
            referral_data = None
            if conversacion.referral_payload_json or conversacion.ad_id or conversacion.campaign_id:
                referral_data = {
                    'headline': conversacion.referral_headline or '',
                    'body':     (conversacion.referral_body or '')[:300],
                    'source_url': conversacion.referral_source_url or '',
                    'source_type': conversacion.referral_source_type or '',
                    'media_type': conversacion.referral_medium or '',
                    'ad_id':       conversacion.ad_id or '',
                    'adset_id':    conversacion.adset_id or '',
                    'campaign_id': conversacion.campaign_id or '',
                    'ctwa_clid':   conversacion.ctwa_clid or '',
                    'ad_name':       '',
                    'campaign_name': '',
                    'adset_name':    '',
                }
                # Resolver nombres legibles vía Marketing API (cache-first).
                # Best-effort: cualquier fallo no rompe la apertura del chat.
                if conversacion.ad_id:
                    try:
                        from .services_ads import resolver_anuncio
                        _cfg = getattr(conversacion.sesion, 'config_meta', None)
                        _cache = resolver_anuncio(_cfg, conversacion.ad_id)
                        if _cache:
                            referral_data['ad_name'] = _cache.ad_name or ''
                            referral_data['campaign_name'] = _cache.campaign_name or ''
                            referral_data['adset_name'] = _cache.adset_name or ''
                    except Exception:
                        logging.getLogger(__name__).exception('Error resolviendo anuncio CTWA')
            return JsonResponse({
                'html': render_to_string('whatsapp/conversaciones/mensajes_partial.html', data, request=request),
                'conversacion_id': conversacion.id,
                'contacto_nombre': conversacion.contacto_nombre or '',
                'contacto_numero': conversacion.contacto_numero,
                # get_foto_gris() devuelve: la foto real si existe; si no,
                # el PNG con la inicial del nombre; si no hay nombre, el
                # default. Así nunca usamos el avatar genérico cuando hay
                # información mínima del contacto.
                'contacto_foto': conversacion.contacto.get_foto_gris(),
                'hashed_id': conversacion.hashed_id or '',
                'estado_active': conversacion.estado_conversacion == 0,
                'ai_activo': conversacion.ai_activo,
                'asignado_a': conversacion.asignado_a.get_full_name() if conversacion.asignado_a else '',
                'asignado_foto': conversacion.asignado_a.get_foto_gris() if conversacion.asignado_a else '',
                'nota_interna': conversacion.nota_interna or '',
                'fecha_asignacion': conversacion.fecha_asignacion.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_asignacion else '',
                'fecha_inicio': conversacion.fecha_registro.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_registro else '',
                'bloquear_cierre': conversacion.bloquear_cierre,
                'es_meta': bool(getattr(conversacion.sesion, 'es_meta', False)),
                'vence_meta': conversacion.vence_meta_en.isoformat() if conversacion.vence_meta_en else None,
                'meta_bloqueada': conversacion.vence_meta_expirada,
                'es_tradicional': (conversacion.sesion.modo_bot or '') == 'tradicional',
                'referral': referral_data,
                'clasificacion_id': conversacion.clasificacion,
                'clasificacion_label': conversacion.get_clasificacion_display(),
                'clasificacion_color': conversacion.get_estado_color_clasificacion(),
                **_estadisticas_conversacion(conversacion),
            })
        elif action == 'ver_estadisticas':
            try:
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['pk']))
                if not puede_ver_conversacion(request.user, conversacion):
                    return JsonResponse({'error': True, 'message': 'No autorizado.'})
                return JsonResponse({'error': False, **_estadisticas_conversacion(conversacion)})
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'cambiar-clasificacion':
            return cambiar_clasificacion_get(request)
        elif action == 'cambiar-nombre-contacto':
            return cambiar_nombre_contacto_get(request)
        elif action == 'asignar-conversacion':
            try:
                filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
                if not puede_ver_conversacion(request.user, filtro):
                    return JsonResponse({"result": False, 'message': 'No autorizado.'})
                form = AsignarAgenteForm(instance=filtro)
                data.update({'form': form, 'filtro': filtro})
                template = get_template("whatsapp/conversaciones/form.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})
        elif action == 'historial_cliente':
            try:
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['pk']))
                if not puede_ver_conversacion(request.user, conv):
                    return JsonResponse({'error': True, 'message': 'No autorizado.'})
                return historial_cliente_list(request, conv)
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'ficha_cliente':
            try:
                from crm.models import CLIENTE_SEXO_CHOICES
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['id']))
                if not puede_ver_conversacion(request.user, conv):
                    return JsonResponse({'result': False, 'message': 'No autorizado.'})
                clientes = _clientes_de_conversacion(conv)
                prefill, variables_flujo = _prefill_ficha_cliente(conv)
                ctx = {
                    'clientes': clientes,
                    'conv': conv,
                    'prefill': prefill,
                    'variables_flujo': variables_flujo,
                    'sexo_choices': CLIENTE_SEXO_CHOICES,
                    'permitir_registro_manual': True,
                }
                template = get_template('whatsapp/conversaciones/_modal_ficha_cliente.html')
                return JsonResponse({'result': True, 'data': template.render(ctx, request)})
            except Exception as ex:
                return JsonResponse({'result': False, 'message': str(ex)})
        elif action == 'logs-notificaciones':
            try:
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['id']))
                if not puede_ver_conversacion(request.user, conv):
                    return JsonResponse({'error': True, 'message': 'No autorizado.'})
                from crm.models import LogNotificacionAsignacion
                logs = (
                    LogNotificacionAsignacion.objects
                    .filter(conversacion=conv, status=True)
                    .select_related('agente')[:50]
                )
                template = get_template('whatsapp/conversaciones/_modal_logs_notif.html')
                return JsonResponse({'result': True, 'data': template.render({
                    'logs': logs,
                    'titulo_scope': f'Avisos de asignación de la conversación #{conv.id}',
                    'mostrar_conversacion': False,
                })})
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'historial_mensajes':
            try:
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['pk']))
                if not puede_ver_conversacion(request.user, conv):
                    return JsonResponse({'error': True, 'message': 'No autorizado.'})
                return historial_cliente_mensajes(request, conv)
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'consultar_datos_red':
            from .funcionesWhatsappConversacion import consultar_datos_red
            return consultar_datos_red(request, canal_fijo=canal_fijo)
        elif action == 'listar_plantillas_meta':
            # Devuelve plantillas APPROVED de la sesion Meta de la conversacion.
            # Se usa para poblar el panel en el composer cuando sesion.es_meta.
            try:
                pk = int(request.GET['pk'])
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                if not puede_ver_conversacion(request.user, conversacion):
                    return JsonResponse({'error': True, 'message': 'No autorizado.'})
                sesion = conversacion.sesion
                if not getattr(sesion, 'es_meta', False):
                    return JsonResponse({'error': False, 'plantillas': [], 'motivo': 'sesion_no_meta'})
                config = getattr(sesion, 'config_meta', None)
                if not config:
                    return JsonResponse({'error': False, 'plantillas': [], 'motivo': 'sin_config_meta'})
                plantillas = (
                    config.plantillas.filter(status=True, estado_meta='APPROVED')
                    .order_by('nombre', 'idioma')
                )
                def _preview(body, max_chars=140):
                    body = (body or '').strip()
                    return (body[:max_chars] + '…') if len(body) > max_chars else body
                data_plantillas = [{
                    'id':        p.id,
                    'nombre':    p.nombre,
                    'idioma':    p.idioma,
                    'categoria': p.categoria,
                    'cuerpo':    p.cuerpo or '',
                    'preview':   _preview(p.cuerpo),
                    'footer':    p.footer or '',
                    'header_tipo':     p.header_tipo,
                    'header_contenido': p.header_contenido or '',
                    'variables': p.variables_json or [],
                    'botones':   p.botones_json or [],
                    'veces_enviada': p.veces_enviada,
                } for p in plantillas]
                return JsonResponse({'error': False, 'plantillas': data_plantillas})
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})

    # ====================== ENVIAR MENSAJE =========================
    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST['action']
                res_json= []

                # Guard IDOR: las acciones que operan sobre una conversación por
                # pk/id deben verificar que el usuario puede verla. Sin esto, un
                # usuario de otro tenant pasaba un pk ajeno y cerraba/reasignaba/
                # renombraba/pausaba conversaciones de otra empresa.
                ACCIONES_CONV = {
                    'asignar-conversacion', 'toggle-bot', 'toggle-bloquear-cierre',
                    'reiniciar-flujo', 'marcar-resuelto', 'terminar-sin-despedida',
                    'enviar_plantilla_meta',
                }
                if action in ACCIONES_CONV:
                    _pk_conv = request.POST.get('pk') or request.POST.get('id')
                    try:
                        _conv_guard = ConversacionWhatsApp.objects.get(pk=int(_pk_conv))
                    except (TypeError, ValueError, ConversacionWhatsApp.DoesNotExist):
                        return JsonResponse({'error': True, 'message': 'Conversación no encontrada.'})
                    if not puede_ver_conversacion(request.user, _conv_guard):
                        return JsonResponse({'error': True, 'message': 'No autorizado.'})

                if action == 'send':
                    pk = int(request.POST['pk'])
                    texto = request.POST.get('mensaje')
                    archivo = request.FILES.get('archivo')  # Obtener archivo si existe
                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                    if not puede_ver_conversacion(request.user, conversacion):
                        return JsonResponse({'error': True, 'message': 'Not authorized.'})

                    from .funcionesWhatsappConversacion import _bloqueo_ventana_meta
                    meta_bloqueada, _vence_meta = _bloqueo_ventana_meta(conversacion)
                    if meta_bloqueada:
                        return JsonResponse({
                            'error': True,
                            'requiere_plantilla': True,
                            'message': 'La ventana de 24 horas de Meta venció. Para retomar la conversación debes enviar una plantilla aprobada.',
                        })

                    # Crear instancia del servicio segun proveedor de la sesion
                    service = get_whatsapp_service(conversacion.sesion)

                    # Determinar tipo antes de leer el archivo.
                    # `tipo_mensaje` es el valor interno (ES) que guardamos en BD.
                    # `media_type` es el valor canonico (EN) que ambos servicios aceptan.
                    tipo_mensaje = 'texto'
                    media_type = None
                    if archivo:
                        ct = archivo.content_type or ''
                        if 'image' in ct:
                            tipo_mensaje, media_type = 'imagen', 'image'
                        elif 'audio' in ct:
                            tipo_mensaje, media_type = 'audio', 'audio'
                        elif 'video' in ct:
                            tipo_mensaje, media_type = 'video', 'video'
                        else:
                            tipo_mensaje, media_type = 'documento', 'document'

                    import time as _time
                    _t0_envio = _time.monotonic()
                    if archivo:
                        file_bytes = archivo.read()
                        response = service.send_media_message(
                            conversacion.sesion.session_id, conversacion.from_number, caption=texto,
                            file_content=file_bytes, filename=archivo.name, media_type=media_type,
                            conversacion_id=conversacion.id,
                        )
                    else:
                        response = service.send_text_message(
                            conversacion.sesion.session_id, conversacion.from_number, texto,
                            conversacion_id=conversacion.id,
                        )
                    _dur_envio_ms = int((_time.monotonic() - _t0_envio) * 1000)

                    # Trazabilidad de envíos desde el panel: fallo o lentitud
                    # (>5s) quedan en /whatsapp/trazas/ con proveedor, duración
                    # y error crudo del servicio — sin esto "no se envió" o
                    # "demoró" no es diagnosticable en producción.
                    if not response.get('success', False) or _dur_envio_ms > 5000:
                        from .trazas import registrar as _traza_envio
                        _traza_envio(
                            etapa='error_general',
                            sesion=conversacion.sesion, conversacion=conversacion,
                            numero=conversacion.contacto_numero,
                            nivel='error' if not response.get('success', False) else 'warning',
                            latencia_ms=_dur_envio_ms,
                            detalle={
                                'accion': 'send_panel',
                                'proveedor': getattr(conversacion.sesion, 'proveedor', ''),
                                'tipo': tipo_mensaje,
                                'duracion_ms': _dur_envio_ms,
                                'error': response.get('error') or '',
                                'status': response.get('status') or '',
                            },
                        )

                    if not response.get('success', False):
                        # Precondiciones (ventana 24h / cuenta degradada): no se
                        # persiste, el frontend abre el panel de plantillas.
                        if response.get('requiere_plantilla') or response.get('cuenta_degradada'):
                            return JsonResponse({
                                'error': True,
                                'message': f"Error al enviar mensaje: {response.get('error', 'Error desconocido')}",
                                'requiere_plantilla': bool(response.get('requiere_plantilla')),
                                'cuenta_degradada': bool(response.get('cuenta_degradada')),
                            })
                        # Falla genérica (red caída, timeout del proveedor, etc.):
                        # guardamos el mensaje como 'fallido' para que el agente
                        # pueda reenviarlo de un click desde el chat.
                        mensaje = MensajeWhatsApp(
                            conversacion=conversacion,
                            remitente=conversacion.sesion.numero,
                            mensaje=texto,
                            tipo=tipo_mensaje,
                            fecha=timezone.now(),
                            leido=True,
                            fecha_leido=timezone.now(),
                            agente=request.user,
                            ia_generado=False,
                            estado_envio='fallido',
                            error_envio=str(response.get('error', 'Fallo de envío'))[:500],
                        )
                        if archivo:
                            from django.core.files.base import ContentFile
                            mensaje.archivo.save(archivo.name, ContentFile(file_bytes), save=False)
                        mensaje.save()
                        return JsonResponse({
                            'error': False,
                            'fallido': True,
                            'message': f"No se pudo enviar: {response.get('error', 'Error')}. Quedó como fallido — puedes reenviarlo.",
                            'mensaje_html': render_to_string(
                                'whatsapp/conversaciones/mensaje_enviado_partial.html',
                                {'mensaje': mensaje}, request=request),
                        })

                    # Guardamos en BD
                    mensaje = MensajeWhatsApp(
                        mensaje_id_externo=response.get('message_id'),
                        conversacion=conversacion,
                        remitente=conversacion.sesion.numero,
                        mensaje=texto,
                        tipo=tipo_mensaje,
                        archivo_url=response.get('media_url'),
                        fecha=timezone.now(),
                        leido=True,
                        fecha_leido=timezone.now(),
                        agente=request.user,
                        ia_generado=False,
                    )
                    # Guardar archivo localmente para tener URL definitiva
                    if archivo:
                        from django.core.files.base import ContentFile
                        mensaje.archivo.save(archivo.name, ContentFile(file_bytes), save=False)
                    mensaje.save()

                    # Registrar primer agente y pausar bot/flujo: si un humano
                    # responde desde plataforma, ni la IA ni el chatbot
                    # tradicional deben volver a contestar (ai_activo gatea
                    # ambos en procesar_mensaje).
                    campos = []
                    if not conversacion.primer_agente:
                        conversacion.primer_agente = request.user
                        campos.append('primer_agente')
                    if conversacion.ai_activo:
                        conversacion.ai_activo = False
                        campos.append('ai_activo')
                    if campos:
                        conversacion.save(update_fields=campos)

                    log(f"Mensaje enviado a {conversacion.contacto_numero}", request, "add", obj=conversacion.id)

                    # Devolver el HTML del mensaje para añadirlo al chat
                    return JsonResponse({
                        'error': False,
                        'mensaje_html': render_to_string('whatsapp/conversaciones/mensaje_enviado_partial.html',
                                                        {'mensaje': mensaje},
                                                        request=request)
                    })
                elif action == 'reenviar_mensaje':
                    return _reenviar_mensaje(request)
                elif action == 'tomar-conversacion':
                    # El primer asesor que toca "Tomar" se queda con la
                    # conversación. UPDATE condicional = atómico: ante dos
                    # clicks simultáneos solo uno gana.
                    pk = int(request.POST['pk'])
                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                    if rol_en_sesion(request.user, conversacion.sesion) not in ('superuser', 'supervisor', 'asesor'):
                        return JsonResponse({'error': True, 'message': 'No autorizado.'})
                    actualizadas = ConversacionWhatsApp.objects.filter(
                        pk=pk, asignado_a__isnull=True, estado_conversacion=0,
                    ).update(
                        asignado_a=request.user,
                        fecha_asignacion=timezone.now(),
                        ai_activo=False,
                    )
                    conversacion.refresh_from_db()
                    if not actualizadas:
                        nombre = (conversacion.asignado_a.get_full_name() or conversacion.asignado_a.username) if conversacion.asignado_a else ''
                        return JsonResponse({
                            'error': True,
                            'tomada_por': nombre,
                            'message': f'Ya la tomó {nombre}.' if nombre else 'La conversación ya no está disponible.',
                        })
                    if not conversacion.primer_agente_id:
                        conversacion.primer_agente = request.user
                        conversacion.save(update_fields=['primer_agente'])
                    from .models import HistorialAsignacion
                    HistorialAsignacion.objects.create(
                        conversacion=conversacion,
                        asignado_a=request.user,
                        asignado_por=request.user,
                        nota='Tomada por el asesor desde el panel.',
                    )
                    from crm.helpers_asignacion import _marcar_ultima_asignacion
                    _marcar_ultima_asignacion(request.user)
                    log(f"Conversación {conversacion.id} tomada por el asesor", request, "change", obj=conversacion.id)
                    # Presentación automática al cliente (mismo patrón que el
                    # mensaje de handoff de asignar-conversacion).
                    try:
                        nombre_asesor = request.user.get_full_name() or request.user.username
                        texto_presentacion = f'Hola 👋 Soy {nombre_asesor}, tu asesor y te guiaré en este proceso.'
                        service_tomar = get_whatsapp_service(conversacion.sesion)
                        respuesta_pres = service_tomar.send_text_message(
                            conversacion.sesion.session_id,
                            conversacion.contacto.from_number,
                            texto_presentacion,
                            conversacion_id=conversacion.id,
                            simularEscritura=True,
                        )
                        if respuesta_pres.get('success'):
                            _persistir_y_difundir_automatico(conversacion, texto_presentacion)
                    except Exception:
                        logging.getLogger(__name__).exception(
                            'No pude enviar la presentación del asesor conv#%s', conversacion.id)
                    try:
                        from asgiref.sync import async_to_sync
                        from channels.layers import get_channel_layer
                        async_to_sync(get_channel_layer().group_send)(
                            f"whatsapp_sessionroom_{conversacion.sesion.id}",
                            {'type': 'whatsapp_event', 'conversation_id': conversacion.id, 'from_me': True},
                        )
                    except Exception:
                        logging.getLogger(__name__).exception(
                            'No pude difundir la toma de la conv#%s', conversacion.id)
                    return JsonResponse({
                        'error': False,
                        'message': 'Conversación asignada a ti.',
                        'asignado_nombre': request.user.get_full_name() or request.user.username,
                    })
                elif action in ('cambiar_estado_atencion', 'posponer_conversacion', 'reabrir_conversacion'):
                    return _gestionar_atencion(request, action)
                elif action in ('editar_mensaje', 'eliminar_mensaje'):
                    return _editar_eliminar_mensaje(request, action)
                elif action == 'enviar_plantilla_meta':
                    # Envia una plantilla Meta pre-aprobada. Util cuando la
                    # ventana 24h expiro o para reenganchar conversaciones.
                    import json as _json
                    from .models import PlantillaWhatsApp
                    pk = int(request.POST['pk'])
                    plantilla_id = int(request.POST['plantilla_id'])
                    params_cuerpo = _json.loads(request.POST.get('params_cuerpo_json') or '[]')
                    params_header = _json.loads(request.POST.get('params_header_json') or '[]')

                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                    sesion = conversacion.sesion
                    if not getattr(sesion, 'es_meta', False):
                        return JsonResponse({'error': True, 'message': 'La sesion no es Meta — usa el envio normal.'})
                    config = getattr(sesion, 'config_meta', None)
                    if not config:
                        return JsonResponse({'error': True, 'message': 'Configuracion Meta no encontrada.'})
                    plantilla = PlantillaWhatsApp.objects.filter(
                        pk=plantilla_id, config_meta=config, status=True, estado_meta='APPROVED'
                    ).first()
                    if not plantilla:
                        return JsonResponse({'error': True, 'message': 'Plantilla no disponible o no aprobada.'})

                    service = get_whatsapp_service(sesion)
                    response = service.send_template(
                        sesion.session_id, conversacion.from_number,
                        plantilla_nombre=plantilla.nombre,
                        idioma=plantilla.idioma,
                        parametros_cuerpo=params_cuerpo if params_cuerpo else None,
                        parametros_header=params_header if params_header else None,
                        conversacion_id=conversacion.id,
                    )
                    if not response.get('success'):
                        return JsonResponse({
                            'error': True,
                            'message': f"Error al enviar plantilla: {response.get('error', 'Error desconocido')}",
                        })

                    # Renderizar cuerpo con los params sustituidos para el historial local
                    def _render_cuerpo(body, params):
                        if not body:
                            return ''
                        out = body
                        for idx, val in enumerate(params or [], start=1):
                            out = out.replace('{{' + str(idx) + '}}', str(val))
                        return out
                    texto_final = _render_cuerpo(plantilla.cuerpo, params_cuerpo)
                    if plantilla.footer:
                        texto_final = f"{texto_final}\n\n_{plantilla.footer}_"

                    mensaje = MensajeWhatsApp(
                        mensaje_id_externo=response.get('message_id'),
                        conversacion=conversacion,
                        remitente=sesion.numero,
                        mensaje=texto_final,
                        tipo='texto',
                        fecha=timezone.now(),
                        leido=True,
                        fecha_leido=timezone.now(),
                        agente=request.user,
                        ia_generado=False,
                    )
                    mensaje.save()

                    # El contador veces_enviada + ultimo_envio lo actualiza
                    # MetaWhatsAppService.send_template via F('veces_enviada')+1.
                    campos_plantilla = []
                    if not conversacion.primer_agente:
                        conversacion.primer_agente = request.user
                        campos_plantilla.append('primer_agente')
                    if conversacion.ai_activo:
                        conversacion.ai_activo = False
                        campos_plantilla.append('ai_activo')
                    if campos_plantilla:
                        conversacion.save(update_fields=campos_plantilla)

                    from .funcionesWhatsappConversacion import _registrar_envio_plantilla
                    _registrar_envio_plantilla(
                        request, sesion, conversacion, plantilla, mensaje, origen='chat',
                    )

                    log(f"Plantilla Meta '{plantilla.nombre}' enviada a {conversacion.contacto_numero}",
                        request, "add", obj=conversacion.id)

                    return JsonResponse({
                        'error': False,
                        'mensaje_html': render_to_string(
                            'whatsapp/conversaciones/mensaje_enviado_partial.html',
                            {'mensaje': mensaje}, request=request,
                        ),
                    })
                elif action == 'cambiar-clasificacion':
                    return cambiar_clasificacion_post(request)
                elif action == 'aplicar_datos_red':
                    from .funcionesWhatsappConversacion import aplicar_datos_red
                    return aplicar_datos_red(request, canal_fijo=canal_fijo)
                elif action == 'cambiar-nombre-contacto':
                    return cambiar_nombre_contacto_post(request)
                elif action == 'asignar-conversacion':
                    filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
                    # Marcar fecha_asignacion y pausar bot antes de pasar al form
                    if request.POST.get('asignado_a'):
                        filtro.fecha_asignacion = timezone.now()
                        filtro.ai_activo = False   # auto-pausar bot al asignar humano
                    else:
                        filtro.fecha_asignacion = None
                        filtro.ai_activo = True    # reactivar bot si se desasigna
                    form = AsignarAgenteForm(request.POST, instance=filtro, request=request)
                    if form.is_valid():
                        filtro = form.save()
                        asignado = filtro.asignado_a
                        log(f"Conversación {filtro.id} asignada a {asignado}", request, "change", obj=filtro.id)
                        # Registrar en historial de asignaciones
                        try:
                            from .models import HistorialAsignacion
                            HistorialAsignacion.objects.create(
                                conversacion=filtro,
                                asignado_a=asignado,
                                asignado_por=request.user,
                                nota=filtro.nota_interna or '',
                            )
                        except Exception:
                            pass
                        if asignado:
                            try:
                                from crm.helpers_asignacion import notificar_agente_asignado
                                notificar_agente_asignado(
                                    filtro, asignado,
                                    motivo='manual',
                                    asignador=request.user,
                                )
                            except Exception:
                                import logging as _lg
                                _lg.getLogger(__name__).exception(
                                    'No se pudo notificar al agente asignado conv=%s', filtro.id,
                                )
                        nombre_asignado = asignado.get_full_name() if asignado else ''
                        # Mensaje de handoff al cliente (si la sesión tiene mensaje configurado)
                        if asignado:
                            try:
                                sesion = filtro.contacto.sesion
                                handoff_msg = getattr(sesion, 'mensaje_handoff', None)
                                if not handoff_msg:
                                    handoff_msg = f'Hola, te atenderá {nombre_asignado}. En breve te contactamos.'
                                service = get_whatsapp_service(sesion)
                                respuesta_handoff = service.send_text_message(
                                    sesion.session_id,
                                    filtro.contacto.from_number,
                                    handoff_msg,
                                    conversacion_id=filtro.id,
                                    simularEscritura=True,
                                )
                                if respuesta_handoff.get('success'):
                                    _persistir_y_difundir_automatico(filtro, handoff_msg)
                            except Exception:
                                logging.getLogger(__name__).exception(
                                    'Fallo el mensaje de handoff conv#%s', filtro.id)
                        # JS para actualizar header sin recargar
                        if nombre_asignado:
                            js = (
                                f"$('#asignado-nombre').text({repr(nombre_asignado)});"
                                f"$('#asignado-container').removeClass('d-none');"
                                f"actualizarBotUI(false);"
                                f"bootstrap.Modal.getInstance(document.getElementById('modalDetalle'))?.hide();"
                                f"alertaSuccess('Conversación asignada a {nombre_asignado}. Bot pausado.');"
                            )
                        else:
                            js = (
                                "$('#asignado-container').addClass('d-none');"
                                "actualizarBotUI(true);"
                                "bootstrap.Modal.getInstance(document.getElementById('modalDetalle'))?.hide();"
                                "alertaSuccess('Asignación eliminada. Bot reactivado.');"
                            )
                        res_json.append({
                            'error': False,
                            'reload': False,
                            'function_js': js,
                        })
                        return JsonResponse(res_json, safe=False)
                    else:
                        raise NameError(f'Error al asignar: {form.errors}')
                elif action == 'toggle-bot':
                    filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    filtro.ai_activo = not filtro.ai_activo
                    filtro.save(request)
                    estado = 'activado' if filtro.ai_activo else 'pausado'
                    log(f"Bot {estado} para conversación {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse({'error': False, 'ai_activo': filtro.ai_activo})
                elif action == 'toggle-bloquear-cierre':
                    filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    filtro.bloquear_cierre = not filtro.bloquear_cierre
                    filtro.save(update_fields=['bloquear_cierre'])
                    estado = 'bloqueado' if filtro.bloquear_cierre else 'desbloqueado'
                    log(f"Cierre automático {estado} para conversación {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse({'error': False, 'bloquear_cierre': filtro.bloquear_cierre})
                elif action == 'reiniciar-flujo':
                    # Solo aplica a sesiones con chatbot tradicional. Limpia el
                    # estado del flujo, vuelve al nodo_inicio del depto y dispara
                    # el primer mensaje hacia el cliente.
                    from crm.motor_flujo_chatbot import reiniciar_flujo_tradicional
                    filtro = ConversacionWhatsApp.objects.select_related(
                        'sesion', 'contacto'
                    ).get(pk=int(request.POST['id']))
                    if (filtro.sesion.modo_bot or '') != 'tradicional':
                        return JsonResponse({
                            'error': True,
                            'message': 'Esta acción solo aplica a sesiones con chatbot tradicional.',
                        })
                    resultado = reiniciar_flujo_tradicional(filtro)
                    if resultado.error:
                        return JsonResponse({'error': True, 'message': resultado.error})
                    n_respuestas = len(resultado.respuestas or [])
                    log(f"Flujo reiniciado manualmente en conversación {filtro.id} "
                        f"({n_respuestas} mensajes enviados)",
                        request, "change", obj=filtro.id)
                    return JsonResponse({
                        'error': False,
                        'message': f'Flujo reiniciado. {n_respuestas} mensaje(s) enviado(s) al cliente.',
                        'respuestas_enviadas': n_respuestas,
                    })
                elif action == 'marcar-resuelto':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    # cerrar() ya no levanta excepción si la despedida falla
                    # — cierra igual y deja traza fin_conversacion con nivel
                    # 'error'. Esto evita que un fallo de envío (ventana 24h
                    # Meta, Node caído, etc.) bloquee el cierre manual.
                    filtro.cerrar(enviar_despedida=True)
                    filtro.refresh_from_db(fields=['despedida_enviado'])
                    msg_extra = '' if filtro.despedida_enviado else \
                        ' Despedida no enviada — revisá /whatsapp/trazas/ filtrando fin_conversacion.'
                    res_json.append({
                        'error': False,
                        'url': branding['url_finalizadas'],
                        'message': f'Conversación cerrada.{msg_extra}',
                        'despedida_enviada': filtro.despedida_enviado,
                    })
                    request.session['contactoId'] = encrypt(filtro.id)
                    log(f"Conversación marcada como resuelta {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse(res_json, safe=False)
                elif action == 'terminar-sin-despedida':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    filtro.cerrar(enviar_despedida=False)
                    res_json.append({'error': False, 'url': branding['url_finalizadas']})
                    request.session['contactoId'] = encrypt(filtro.id)
                    log(f"Conversación marcada como resuelta {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse(res_json, safe=False)
                elif action == 'transcribe_audio':
                    # transcribe_audio es provider-agnostic: solo procesa el archivo local
                    # con whisper, no habla con Node ni Meta. Usar WhatsAppService directo
                    # esta OK aqui (el dispatcher no aplica porque MetaWhatsAppService
                    # delega esta misma funcion a WhatsAppService internamente).
                    # Candado anti-doble-click: los re-render del chat por WS
                    # pierden el spinner y el usuario volvia a pulsar, encolando
                    # transcripciones duplicadas del mismo audio.
                    from django.core.cache import cache as _cache
                    msg_id_tr = int(request.POST['id'])
                    lock_tr = f'transcribiendo_{msg_id_tr}'
                    if _cache.get(lock_tr):
                        return JsonResponse({'error': True, 'en_proceso': True,
                                             'message': 'La transcripción ya está en proceso. Aparecerá sola al terminar.'})
                    _cache.set(lock_tr, True, 300)
                    service = WhatsAppService()
                    msg = MensajeWhatsApp.objects.select_related('conversacion__contacto__sesion').get(id=msg_id_tr)
                    if not puede_ver_conversacion(request.user, msg.conversacion):
                        return JsonResponse({'error': True, 'message': 'No autorizado.'})
                    service.transcribe_audio(msg, 'small', msg.conversacion.contacto.sesion.language.split('-')[0])
                    return JsonResponse({})

                elif action == 'feedback-mensaje':
                    from crm.models import FeedbackMensajeBot
                    msg_id = int(request.POST['mensaje_id'])
                    es_correcto = request.POST.get('es_correcto') == '1'
                    correccion = request.POST.get('correccion', '').strip()
                    pregunta = request.POST.get('pregunta', '').strip()

                    msg = MensajeWhatsApp.objects.select_related(
                        'conversacion__contacto__sesion__agente_ia'
                    ).get(pk=msg_id)

                    if not puede_ver_conversacion(request.user, msg.conversacion):
                        return JsonResponse({'error': True, 'message': 'No autorizado.'})

                    # Crear o actualizar feedback
                    feedback, _ = FeedbackMensajeBot.objects.update_or_create(
                        mensaje=msg,
                        defaults={
                            'es_correcto': es_correcto,
                            'correccion': correccion,
                            'pregunta_original': pregunta,
                            'agente': msg.conversacion.sesion.agente_ia,
                            'usuario': request.user,
                            'procesado_vectorstore': False,
                        }
                    )

                    # Si es incorrecto y hay corrección → crear FAQ aprobada + FAISS
                    if not es_correcto and correccion and pregunta:
                        agente = msg.conversacion.sesion.agente_ia
                        if agente:
                            # 1. Crear FaqAgente directamente aprobada (el humano ya validó)
                            try:
                                from crm.models import FaqAgente
                                from django.utils import timezone as _tz
                                ya_existe = FaqAgente.objects.filter(
                                    agente=agente, pregunta__iexact=pregunta.strip(),
                                ).first()
                                if ya_existe:
                                    ya_existe.respuesta = correccion.strip()[:4000]
                                    ya_existe.estado = 'aprobada'
                                    ya_existe.origen = 'feedback'
                                    ya_existe.mensaje_origen = msg
                                    ya_existe.fecha_aprobacion = _tz.now()
                                    ya_existe.usuario_aprobacion = request.user
                                    ya_existe.save()
                                else:
                                    FaqAgente.objects.create(
                                        agente=agente,
                                        pregunta=pregunta.strip()[:2000],
                                        respuesta=correccion.strip()[:4000],
                                        origen='feedback',
                                        estado='aprobada',
                                        conversacion_origen=msg.conversacion,
                                        mensaje_origen=msg,
                                        fecha_aprobacion=_tz.now(),
                                        usuario_aprobacion=request.user,
                                    )
                            except Exception as ex:
                                log(f"Error creando FaqAgente desde feedback: {ex}", request, "error")

                            # 2. Agregar al FAISS si está configurado (compatibilidad)
                            if agente.vectorstore_path and agente.apikey.filter(estado=True).exists():
                                apikey_obj = (
                                    agente.apikey.filter(estado=True, proveedor__in=(2, 3, 5)).first()
                                    or agente.apikey.filter(estado=True).first()
                                )
                                try:
                                    from agents_ai.vectorstore_manager import VectorStoreManager
                                    import os
                                    from django.conf import settings
                                    storage = os.path.join(settings.MEDIA_ROOT, 'vectorstores')
                                    vs_abs = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path)
                                    vsm = VectorStoreManager(
                                        storage, apikey_obj.proveedor, apikey_obj.descripcion,
                                        base_url=(getattr(apikey_obj, 'base_url', '') or None)
                                    )
                                    vsm.add_correction(vs_abs, pregunta, correccion)
                                    feedback.procesado_vectorstore = True
                                    feedback.save(update_fields=['procesado_vectorstore'])
                                    from agents_ai.consultor.retrieval import invalidate_vectorstore_cache
                                    invalidate_vectorstore_cache(vs_abs)
                                except Exception as ex:
                                    log(f"Error al agregar corrección al vectorstore: {ex}", request, "error")

                    return JsonResponse({
                        'error': False,
                        'procesado_vectorstore': feedback.procesado_vectorstore,
                        'mensaje': 'Feedback guardado' + (' y agregado al vectorstore ✓' if feedback.procesado_vectorstore else ''),
                    })

                elif action == 'crear_cliente_manual':
                    # Alta manual de la ficha del cliente desde la conversación,
                    # para el caso en que el cliente no terminó el flujo del
                    # chatbot tradicional. Reusa cliente_upsert (misma lógica de
                    # origen + ClienteOrigen que el flujo automático).
                    conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.POST['id']))
                    if not puede_ver_conversacion(request.user, conv):
                        return JsonResponse({'error': True, 'message': 'No autorizado.'})
                    cedula = (request.POST.get('cedula') or '').strip()
                    if not cedula:
                        return JsonResponse({'error': True, 'message': 'La cédula / identificación es obligatoria.'})
                    variables = {
                        'cedula':           cedula,
                        'nombres':          (request.POST.get('nombres') or '').strip(),
                        'apellidos':        (request.POST.get('apellidos') or '').strip(),
                        'email':            (request.POST.get('email') or '').strip(),
                        'telefono':         (request.POST.get('telefono') or '').strip(),
                        'ciudad':           (request.POST.get('ciudad') or '').strip(),
                        'edad':             (request.POST.get('edad') or '').strip(),
                        'fecha_nacimiento': (request.POST.get('fecha_nacimiento') or '').strip(),
                        'sexo':             (request.POST.get('sexo') or '').strip(),
                        'notas':            (request.POST.get('notas') or '').strip(),
                        'canal_origen':     'manual',
                    }
                    from crm.funciones_cliente import cliente_upsert
                    resultado = cliente_upsert(conv, variables, {'canal_origen': 'manual'})
                    if resultado.get('etiqueta') != 'ok':
                        return JsonResponse({
                            'error': True,
                            'message': resultado.get('error') or 'No se pudo registrar el cliente.',
                        })
                    body = resultado.get('body') or {}
                    creado = bool(body.get('cliente_creado'))
                    log(f"Cliente {'registrado' if creado else 'actualizado'} manualmente "
                        f"desde conversación {conv.id} (cédula {cedula})",
                        request, "add" if creado else "change", obj=conv.id)
                    return JsonResponse({
                        'error': False,
                        'creado': creado,
                        'cliente_id': body.get('cliente_id'),
                        'message': 'Cliente registrado correctamente.' if creado
                                   else 'Ya existía un cliente con esa cédula; se actualizó la ficha.',
                    })


        except Exception as ex:
            # forms.js espera array para recorrer con forEach — envolver en lista.
            return JsonResponse([{'error': True, 'message': str(ex)}], safe=False)

    # ====================== LISTADO CONVERSACIONES =========================
    criterio = request.GET.get('criterio', '').strip()
    filtro_clasificacion = request.GET.get('clasificacion', '')
    filtro_sin_responder = request.GET.get('sin_responder', '')
    filtro_mis_conv = request.GET.get('mis_conv', '')
    filtro_asesor = request.GET.get('asesor', '')
    filtro_por_caducar = request.GET.get('por_caducar', '')

    # `sesiones` ya viene acotado por canal_fijo (wrappers /instagram/ y
    # /tiktok/): sin esto, con canal sin sesiones (sesion_seleccionada=None)
    # el listado mostraba conversaciones de TODOS los canales.
    filtros = Q(
        contacto__status=True, status=True,
        contacto__sesion__in=sesiones,
        contacto__sesion__status=True,
        estado_conversacion=0
    )
    url_vars = ''

    if sesion_seleccionada:
        filtros = filtros & Q(contacto__sesion=sesion_seleccionada)
        filtros = filtros & filtro_conversaciones_por_rol(request.user, sesion_seleccionada)
        url_vars += f'&sesion={encrypt_sesion_id(sesion_seleccionada.id)}'

    if criterio:
        filtros = filtros & (Q(contacto__contacto_numero__icontains=criterio) | Q(contacto__contacto_nombre__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio

    if filtro_clasificacion:
        filtros = filtros & Q(clasificacion=filtro_clasificacion)
        data["filtro_clasificacion"] = int(filtro_clasificacion)
        url_vars += f'&clasificacion={filtro_clasificacion}'

    if filtro_sin_responder:
        # Último mensaje es del cliente (remitente != numero de sesión)
        filtros = filtros & ~Q(mensajes__remitente=models.F('contacto__sesion__numero')) & Q(mensajes__isnull=False)
        # Más preciso: anotar el last mensaje y verificar
        from django.db.models import Max, Subquery, OuterRef
        ultimo_msg = MensajeWhatsApp.objects.filter(
            conversacion=OuterRef('pk')
        ).order_by('-fecha').values('remitente')[:1]
        filtros = filtros & ~Q(mensajes__isnull=True)
        data["filtro_sin_responder"] = True
        url_vars += '&sin_responder=1'

    if filtro_mis_conv:
        filtros = filtros & Q(asignado_a=request.user)
        data["filtro_mis_conv"] = True
        url_vars += '&mis_conv=1'

    if filtro_asesor:
        try:
            data["filtro_asesor"] = int(filtro_asesor)
            filtros = filtros & Q(asignado_a_id=data["filtro_asesor"])
            url_vars += f'&asesor={data["filtro_asesor"]}'
        except (TypeError, ValueError):
            filtro_asesor = ''

    if filtro_por_caducar:
        # El filtrado real se aplica en el branch load_conversations sobre la
        # anotación fecha_ultimo_entrante (ventana Meta de 24h).
        data["filtro_por_caducar"] = True
        url_vars += '&por_caducar=1'

    data["url_vars"] = url_vars
    data['conversacion_selected'] = conversacion_selected
    data["today"] = timezone.now().date()
    data["SENTIMIENTO_CHOICES"] = SENTIMIENTO_CHOICES
    from .models import ESTADOS_CLASIFICACION
    data["ESTADOS_CLASIFICACION"] = ESTADOS_CLASIFICACION

    # Conteo de conversaciones sin leer (para badge en header), acotado al
    # canal del inbox cuando hay canal_fijo.
    badge_scope = Q(contacto__sesion__in=sesiones) & (
        Q(contacto__sesion__in=sesiones_vista_completa(request.user))
        | Q(asignado_a=request.user)
    )
    data["total_sin_leer"] = ConversacionWhatsApp.objects.filter(
        badge_scope,
        contacto__status=True, status=True,
        estado_conversacion=0,
        mensajes__leido=False,
        mensajes__remitente=models.F('contacto__contacto_numero')
    ).distinct().count()

    # Contadores de abiertas / finalizadas para las pestañas. Mismo alcance
    # de visibilidad que el badge de no-leídos, pero acotado a la sesión
    # seleccionada (es lo que el operador está mirando).
    contadores_scope = badge_scope & Q(contacto__status=True, status=True)
    if sesion_seleccionada:
        contadores_scope = contadores_scope & Q(contacto__sesion=sesion_seleccionada)
    data["total_abiertas"] = ConversacionWhatsApp.objects.filter(
        contadores_scope, estado_conversacion=0,
    ).distinct().count()
    data["total_finalizadas"] = ConversacionWhatsApp.objects.filter(
        contadores_scope, estado_conversacion=1,
    ).distinct().count()

    # Dropdown "Asesor": solo para quien tiene vista completa de la sesión.
    # Los candidatos salen de PerfilSesionWhatsApp (quién atiende la sesión).
    data["mostrar_filtro_asesor"] = es_vista_completa(request.user, sesion_seleccionada)
    data["asesores_filtro"] = []
    if data["mostrar_filtro_asesor"]:
        from .models import PerfilSesionWhatsApp
        perfiles = PerfilSesionWhatsApp.objects.filter(
            status=True, usuario__is_active=True,
        ).select_related('usuario')
        if sesion_seleccionada:
            perfiles = perfiles.filter(sesion=sesion_seleccionada)
        else:
            perfiles = perfiles.filter(sesion__in=sesiones)
        vistos = set()
        for p in perfiles.order_by('usuario__first_name', 'usuario__last_name'):
            if p.usuario_id in vistos:
                continue
            vistos.add(p.usuario_id)
            data["asesores_filtro"].append({
                'id': p.usuario_id,
                'nombre': p.usuario.get_full_name() or p.usuario.username,
            })

    # Si es una solicitud AJAX para cargar conversaciones
    if request.GET.get('load_conversations'):
        from django.db import models as django_models
        from django.db.models import OuterRef, Subquery
        # select_related sobre los FK que el partial usa (foto, nombre,
        # numero de la sesión, foto del contacto). Sin esto, el render del
        # partial dispara N+1 queries por cada item del listado.
        from django.db.models import Count, Q as _Q_nl, F as _F_nl
        qs = (
            ConversacionWhatsApp.objects.sin_expirar
            .filter(filtros)
            .select_related(
                'contacto',
                'contacto__sesion',
                'contacto__sesion__config_meta',
                'contacto__sesion__config_baileys',
                'asignado_a',
            )
            # Cuenta de no-leídos por SQL (evita 1 COUNT por tarjeta del inbox).
            # El template la consume vía `mensajes_no_leidos`.
            .annotate(_no_leidos_ann=Count(
                'mensajes',
                filter=_Q_nl(mensajes__leido=False,
                             mensajes__remitente=_F_nl('contacto__contacto_numero')),
            ))
            .distinct()
        )

        # Filtro "sin responder": antes iteraba toda la lista en Python y
        # hacía 1 query por conv para traer el último mensaje (N+1 enorme).
        # Ahora usamos Subquery para resolverlo en un solo SQL.
        if filtro_sin_responder:
            ultimo_remitente = (
                MensajeWhatsApp.objects
                .filter(conversacion=OuterRef('pk'))
                .order_by('-fecha')
                .values('remitente')[:1]
            )
            numero_sesion = SesionWhatsApp.objects.filter(
                pk=OuterRef('contacto__sesion_id')
            ).values('numero')[:1]
            qs = qs.annotate(
                _ultimo_remitente=Subquery(ultimo_remitente),
                _numero_sesion=Subquery(numero_sesion),
            ).exclude(_ultimo_remitente__isnull=True).exclude(
                _ultimo_remitente=django_models.F('_numero_sesion')
            )

        mostrar_supervisor = es_vista_completa(request.user, sesion_seleccionada)
        if mostrar_supervisor:
            ultimo_remitente_sup = (
                MensajeWhatsApp.objects
                .filter(conversacion=OuterRef('pk'))
                .order_by('-fecha')
                .values('remitente')[:1]
            )
            ultima_fecha_sup = (
                MensajeWhatsApp.objects
                .filter(conversacion=OuterRef('pk'))
                .order_by('-fecha')
                .values('fecha')[:1]
            )
            qs = qs.annotate(
                sup_ultimo_remitente=Subquery(ultimo_remitente_sup),
                sup_fecha_ultimo=Subquery(ultima_fecha_sup),
            )

        ultima_fecha_entrante = (
            MensajeWhatsApp.objects
            .filter(conversacion=OuterRef('pk'))
            .exclude(remitente=OuterRef('contacto__sesion__numero'))
            .order_by('-fecha')
            .values('fecha')[:1]
        )
        qs = qs.annotate(
            fecha_ultimo_entrante=Subquery(ultima_fecha_entrante),
        )

        from datetime import timedelta as _td
        ahora_ts = timezone.now()

        # "Por caducar": ventana Meta de 24h con menos de 6h restantes.
        # vence = fecha_ultimo_entrante + 24h → quedan <6h cuando el último
        # entrante tiene entre 18h y 24h de antigüedad. Solo aplica a Meta
        # (Baileys no tiene ventana de servicio).
        if filtro_por_caducar:
            qs = qs.filter(
                contacto__sesion__proveedor='meta',
                fecha_ultimo_entrante__gt=ahora_ts - _td(hours=24),
                fecha_ultimo_entrante__lte=ahora_ts - _td(hours=18),
            )

        # Orden: última actividad primero. Se ordena por el dato vivo del
        # contacto (el mismo que muestra el "hace X min" de la card) y no por
        # el snapshot `order`, que quedó desactualizado en conversaciones
        # creadas antes del fix de procesar_mensaje.
        qs = qs.order_by(
            django_models.F('contacto__fecha_ultimo_mensaje').desc(nulls_last=True),
            '-id',
        )

        conv_list = list(qs)
        for _c in conv_list:
            if getattr(_c, 'atendida_por_meta', False) and getattr(_c, 'fecha_ultimo_entrante', None):
                _c.vence_meta_en = _c.fecha_ultimo_entrante + _td(hours=24)
                _c.vence_meta_expirada = _c.vence_meta_en <= ahora_ts
            else:
                _c.vence_meta_en = None
                _c.vence_meta_expirada = False

        return JsonResponse({
            'html': render_to_string('whatsapp/conversaciones/conversaciones_partial.html',
                                    {
                                        'conversaciones': conv_list,
                                        'today': ahora_ts.date(),
                                        'now': ahora_ts,
                                        'es_vista_completa': mostrar_supervisor,
                                        'sesion_numero': sesion_seleccionada.numero if sesion_seleccionada else '',
                                    },
                                    request=request),
            'listado_count':     len(conv_list),
            'total_abiertas':    data.get('total_abiertas', 0),
            'total_finalizadas': data.get('total_finalizadas', 0),
        })

    # Pipelines disponibles para el modal "Asignar a pipeline"
    from .models import PipelineVenta as _PV
    data['pipelines_disponibles'] = (
        _PV.objects.filter(status=True).prefetch_related('etapas').order_by('-es_default', 'nombre')
    )
    # Respuestas rápidas globales (invocables con /atajo en el composer).
    data['atajos_globales'] = list(
        RespuestaRapidaGlobal.objects.filter(status=True)
        .values('atajo', 'titulo', 'cuerpo')
    )
    return render(request, template, data)
