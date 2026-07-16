from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, OuterRef, Subquery
from django.contrib import messages
from django.template.loader import render_to_string, get_template
from django.utils import timezone
from django.http import JsonResponse

from core.funciones import addData, secure_module, log, leer_sesion_id, encrypt_sesion_id, decrypt_sesion_id
from seguridad.templatetags.templatefunctions import encrypt
from .models import ConversacionWhatsApp, MensajeWhatsApp
from .permisos_sesion import (
    sesiones_visibles,
    rol_en_sesion,
    filtro_conversaciones_por_rol,
    puede_ver_conversacion,
    es_vista_completa,
)
from .funcionesWhatsappConversacion import (
    cambiar_clasificacion_get,
    cambiar_clasificacion_post,
    cambiar_nombre_contacto_get,
    cambiar_nombre_contacto_post,
    historial_cliente_list,
    historial_cliente_mensajes,
    listar_plantillas_meta,
    enviar_plantilla_reconexion,
    _estadisticas_conversacion,
)


@login_required
@secure_module
def conversacionesPendienteReconexionView(request, canal_fijo=None):
    from .view_conversaciones import BRANDING_INBOX_CANAL
    branding = BRANDING_INBOX_CANAL.get(canal_fijo, BRANDING_INBOX_CANAL[None])
    data = {
        'titulo': branding['titulo'],
        'modulo': branding['titulo'],
        'ruta': request.path,
        'canal_fijo': canal_fijo or '',
        'canal_branding': branding,
    }
    addData(request, data)

    sesiones = sesiones_visibles(request.user).order_by('-ultima_conexion')
    if canal_fijo:
        sesiones = sesiones.filter(proveedor=canal_fijo)
    data['sesiones'] = sesiones

    sesion_id = leer_sesion_id(request)
    contactoId = request.session.pop('contactoId', None)
    conversacion_selected = None
    if contactoId:
        try:
            conversacion_selected = ConversacionWhatsApp.objects.get(pk=int(encrypt(contactoId)))
            sesion_id = conversacion_selected.sesion.id
        except Exception as ex:
            raise NameError(f'No se encontró la conversación: {ex}')

    conv_token = (request.GET.get('conv') or '').strip()
    auto_open_conv_id = None
    if conv_token:
        conv_id_pedido = decrypt_sesion_id(conv_token, default=None)
        if conv_id_pedido:
            conv_obj = ConversacionWhatsApp.objects.filter(pk=conv_id_pedido).select_related(
                'contacto', 'contacto__sesion'
            ).first()
            if conv_obj:
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
    data['rol_sesion'] = rol_en_sesion(request.user, sesion_seleccionada)
    data['es_vista_completa'] = es_vista_completa(request.user, sesion_seleccionada)

    if request.method == 'GET' and 'action' in request.GET:
        action = request.GET['action']
        if action == 'ver_mensajes':
            try:
                pk = int(request.GET['pk'])
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                if not puede_ver_conversacion(request.user, conversacion):
                    return JsonResponse({'error': True, 'message': 'Not authorized.'})
                mensajes = MensajeWhatsApp.objects.filter(conversacion=conversacion).order_by('fecha')
                data['conversacion'] = conversacion
                data['mensajes'] = mensajes
                return JsonResponse({
                    'html': render_to_string('whatsapp/conversaciones/mensajes_partial.html', data, request=request),
                    'conversacion_id': conversacion.id,
                    'contacto_nombre': conversacion.contacto_nombre or '',
                    'contacto_numero': conversacion.contacto_numero,
                    'contacto_foto': conversacion.contacto_foto or '',
                    'hashed_id': conversacion.hashed_id or '',
                    'estado_active': conversacion.estado_conversacion == 0,
                    'show_date': True,
                    'fecha_inicio': conversacion.fecha_registro.strftime('%d/%m/%Y') if conversacion.fecha_registro else '',
                    'fecha_fin': conversacion.fecha_fin_conversacion.strftime('%d/%m/%Y') if conversacion.fecha_fin_conversacion else '',
                    'es_meta': bool(getattr(conversacion.sesion, 'es_meta', False)),
                    'pendiente_reconexion': conversacion.pendiente_reconexion,
                    **_estadisticas_conversacion(conversacion),
                })
            except Exception:
                pass
        elif action == 'ver_resumen_conversacion':
            try:
                pk = int(request.GET['pk'])
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                if not puede_ver_conversacion(request.user, conversacion):
                    return JsonResponse({"result": False, 'message': 'No autorizado.'})
                data['conversacion'] = conversacion
                template = get_template("whatsapp/conversaciones/modal_resumen_conversacion.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})
        elif action == 'cambiar-clasificacion':
            return cambiar_clasificacion_get(request)
        elif action == 'cambiar-nombre-contacto':
            return cambiar_nombre_contacto_get(request)
        elif action == 'historial_cliente':
            try:
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['pk']))
                return historial_cliente_list(request, conv)
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'historial_mensajes':
            try:
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['pk']))
                return historial_cliente_mensajes(request, conv)
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'listar_plantillas_meta':
            return listar_plantillas_meta(request)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST['action']
                if action == 'enviar_plantilla_meta':
                    return enviar_plantilla_reconexion(request)
                elif action == 'cambiar-clasificacion':
                    return cambiar_clasificacion_post(request)
                elif action == 'cambiar-nombre-contacto':
                    return cambiar_nombre_contacto_post(request)
                elif action == 'descartar-pendiente':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    if not puede_ver_conversacion(request.user, filtro):
                        return JsonResponse({'error': True, 'message': 'No autorizado.'})
                    filtro.pendiente_reconexion = False
                    filtro.reconectada = False
                    filtro.save(request)
                    log(f"Reconexión pendiente descartada para la conversación {filtro.id}", request, "change", obj=filtro.id)
                    messages.success(request, 'Reconexión pendiente descartada.')
                    return JsonResponse({'error': False, 'reload': True})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    criterio = request.GET.get('criterio', '').strip()
    filtro_clasificacion = request.GET.get('clasificacion', '').strip()
    if filtro_clasificacion and not filtro_clasificacion.isdigit():
        filtro_clasificacion = ''

    filtros = Q(contacto__status=True, status=True,
                contacto__sesion__in=sesiones,
                contacto__sesion__status=True)
    url_vars = ''

    if sesion_seleccionada:
        filtros &= Q(contacto__sesion=sesion_seleccionada)
        filtros &= filtro_conversaciones_por_rol(request.user, sesion_seleccionada)
        url_vars += f'&sesion={encrypt_sesion_id(sesion_seleccionada.id)}'

    if criterio:
        filtros &= Q(contacto__contacto_numero__icontains=criterio) | Q(contacto__contacto_nombre__icontains=criterio)
        url_vars += '&criterio=' + criterio

    if filtro_clasificacion:
        filtros &= Q(clasificacion=filtro_clasificacion)
        url_vars += '&clasificacion=' + filtro_clasificacion

    from .models import ESTADOS_CLASIFICACION
    data['ESTADOS_CLASIFICACION'] = ESTADOS_CLASIFICACION
    data['conversacion_selected'] = conversacion_selected
    data['url_vars'] = url_vars
    data['today'] = timezone.now().date()
    data['criterio'] = criterio
    data['filtro_clasificacion'] = int(filtro_clasificacion) if filtro_clasificacion else ''

    if request.GET.get('load_conversations'):
        conversaciones = (
            ConversacionWhatsApp.objects.pendientes_reconexion
            .filter(filtros)
            .select_related('contacto', 'contacto__sesion', 'asignado_a')
            .order_by('-fecha_fin_conversacion')
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
            conversaciones = conversaciones.annotate(
                sup_ultimo_remitente=Subquery(ultimo_remitente_sup),
                sup_fecha_ultimo=Subquery(ultima_fecha_sup),
            )
        return JsonResponse({
            'html': render_to_string(
                'whatsapp/conversaciones/conversaciones_partial.html',
                {
                    'conversaciones': conversaciones,
                    'today': timezone.now().date(),
                    'show_date': True,
                    'es_vista_completa': mostrar_supervisor,
                    'sesion_numero': sesion_seleccionada.numero if sesion_seleccionada else '',
                },
                request=request
            )
        })

    return render(request, 'whatsapp/conversaciones/listado_pendiente_reconexion.html', data)
