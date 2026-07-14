from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from django.template.loader import render_to_string, get_template
from django.utils import timezone
from django.http import JsonResponse

from core.funciones import addData, paginador, secure_module, log, leer_sesion_id, encrypt_sesion_id, decrypt_sesion_id
from seguridad.templatetags.templatefunctions import encrypt
from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp
from .services import WhatsAppService, get_whatsapp_service
from .permisos_sesion import (
    sesiones_visibles,
    rol_en_sesion,
    filtro_conversaciones_por_rol,
    puede_ver_conversacion,
    es_vista_completa,
)
from .forms import CambiarClasificacionForm
from .funcionesWhatsappConversacion import (
    cambiar_clasificacion_get,
    cambiar_clasificacion_post,
    cambiar_nombre_contacto_get,
    cambiar_nombre_contacto_post,
    historial_cliente_list,
    historial_cliente_mensajes,
    listar_plantillas_meta,
    enviar_plantilla_reconexion,
    _bloqueo_reactivar,
    _bloqueo_ventana_meta,
    _control_respuestas,
    _estadisticas_conversacion,
    _tokens_conversacion,
    reactivar_conversacion,
    HORAS_VENTANA_REACTIVAR,
    HORAS_VENTANA_META_CUSTOMER_SERVICE,
)


@login_required
@secure_module
def conversacionesFinalizadasView(request):
    data = {
        'titulo': 'Conversaciones WhatsApp',
        'modulo': 'Conversaciones WhatsApp',
        'ruta': request.path
    }
    addData(request, data)

    # Sesiones visibles del usuario (status=True). Incluye pausadas para que el
    # selector y el filtro respeten la sesión marcada en request.session.
    sesiones = sesiones_visibles(request.user).order_by('-ultima_conexion')
    data['sesiones'] = sesiones

    # Sesión seleccionada (por defecto la primera)
    sesion_id = leer_sesion_id(request)
    contactoId = request.session.pop('contactoId', None)
    conversacion_selected = None
    if contactoId:
        try:
            conversacion_selected = ConversacionWhatsApp.objects.get(pk=int(encrypt(contactoId)))
            sesion_id = conversacion_selected.sesion.id
        except Exception as ex:
            raise NameError(f'No se encontró la conversación: {ex}')

    # Soporte deep-link `?conv=<token>` (correo del asesor) — auto-abre la
    # conv en modo solo-lectura. Esta vista es la rama "ya cerró", aceptamos
    # cualquier estado finalized.
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

    # ====================== VER MENSAJES =========================
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
                bloqueada, vence_en = _bloqueo_reactivar(conversacion)
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
                    'reactivar_bloqueada': bloqueada,
                    'reactivar_vence_en': vence_en.isoformat() if vence_en else None,
                    'reactivar_horas_ventana': HORAS_VENTANA_REACTIVAR,
                    'clasificacion_id': conversacion.clasificacion,
                    'clasificacion_label': conversacion.get_clasificacion_display(),
                    'clasificacion_color': conversacion.get_estado_color_clasificacion(),
                    'fecha_fin_full': conversacion.fecha_fin_conversacion.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_fin_conversacion else '',
                    **_estadisticas_conversacion(conversacion),
                })
            except Exception as ex:
                pass
        elif action == 'ver_resumen_conversacion':
            try:
                pk = int(request.GET['pk'])
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                data['conversacion'] = conversacion
                template = get_template("whatsapp/conversaciones/modal_resumen_conversacion.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})
        elif action == 'ficha_cliente':
            try:
                from .view_conversaciones import _clientes_de_conversacion
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['id']))
                clientes = _clientes_de_conversacion(conv)
                ctx = {'clientes': clientes, 'conv': conv}
                template = get_template('whatsapp/conversaciones/_modal_ficha_cliente.html')
                return JsonResponse({'result': True, 'data': template.render(ctx, request)})
            except Exception as ex:
                return JsonResponse({'result': False, 'message': str(ex)})
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


    # ====================== ENVIAR MENSAJE =========================
    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST['action']
                res_json= []
                if action == 'send':
                    pk = int(request.POST['pk'])
                    texto = request.POST.get('mensaje')
                    archivo = request.FILES.get('archivo')
                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                    if not puede_ver_conversacion(request.user, conversacion):
                        return JsonResponse({'error': True, 'message': 'Not authorized.'})

                    bloqueada_meta, vence_meta = _bloqueo_ventana_meta(conversacion)
                    if bloqueada_meta:
                        msg = (
                            f'No se puede enviar texto libre: la ventana de '
                            f'{HORAS_VENTANA_META_CUSTOMER_SERVICE}h desde el último '
                            f'mensaje del cliente'
                        )
                        if vence_meta:
                            msg += f' (venció el {vence_meta.strftime("%d/%m/%Y %H:%M")})'
                        msg += '. Usá una *plantilla aprobada* para retomar la conversación.'
                        return JsonResponse({
                            'error': True,
                            'requiere_plantilla': True,
                            'message': msg,
                        })

                    service = get_whatsapp_service(conversacion.sesion)

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

                    if not response.get('success', False):
                        return JsonResponse({
                            'error': True,
                            'message': f"Error al enviar mensaje: {response.get('error', 'Error desconocido')}"
                        })

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
                    if archivo:
                        from django.core.files.base import ContentFile
                        mensaje.archivo.save(archivo.name, ContentFile(file_bytes), save=False)
                    mensaje.save()

                    reactivar_conversacion(conversacion)
                    campos = []
                    if not conversacion.primer_agente:
                        conversacion.primer_agente = request.user
                        campos.append('primer_agente')
                    if conversacion.ai_activo:
                        conversacion.ai_activo = False
                        campos.append('ai_activo')
                    if campos:
                        conversacion.save(update_fields=campos)

                    log(
                        f"Mensaje enviado y conversacion {conversacion.id} reactivada (a {conversacion.contacto_numero})",
                        request, "add", obj=conversacion.id,
                    )

                    request.session['contactoId'] = encrypt(conversacion.id)
                    return JsonResponse({
                        'error': False,
                        'reactivada': True,
                        'url': '/whatsapp/conversaciones/',
                        'mensaje_html': render_to_string(
                            'whatsapp/conversaciones/mensaje_enviado_partial.html',
                            {'mensaje': mensaje}, request=request,
                        ),
                    })
                elif action == 'enviar_plantilla_meta':
                    return enviar_plantilla_reconexion(request)
                elif action == 'log-wa-web':
                    conv = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
                    if not puede_ver_conversacion(request.user, conv):
                        return JsonResponse({'error': True, 'message': 'No autorizado.'})
                    log(f"Abrió WhatsApp Web para {conv.contacto_numero} desde finalizadas",
                        request, "view", obj=conv.id)
                    from .trazas import registrar as _traza_reg
                    _traza_reg(
                        etapa='webhook_recibido', sesion=conv.sesion, conversacion=conv,
                        numero=conv.contacto_numero, nivel='info',
                        detalle={'accion': 'whatsapp_web_abierto',
                                 'usuario': request.user.get_full_name() or request.user.username},
                    )
                    return JsonResponse({'error': False})
                elif action == 'cambiar-clasificacion':
                    return cambiar_clasificacion_post(request)
                elif action == 'cambiar-nombre-contacto':
                    return cambiar_nombre_contacto_post(request)
                elif action == 'marcar-reactivar':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    bloqueada, vence_en = _bloqueo_reactivar(filtro)
                    if bloqueada:
                        res_json.append({
                            'error': True,
                            'message': f'No se puede reactivar: la ventana de {HORAS_VENTANA_REACTIVAR}h desde la creación venció el {vence_en.strftime("%d/%m/%Y %H:%M")}.',
                        })
                        return JsonResponse(res_json, safe=False)
                    filtro.estado_conversacion = 0
                    filtro.fecha_fin_conversacion = None
                    filtro.despedida_enviado = False
                    filtro.conversacion_finalizada = False
                    filtro.fecha_hora_expira = None
                    filtro.duracion_conversacion = None
                    filtro.save(request)
                    request.session['contactoId'] = encrypt(filtro.id)
                    res_json.append({'error': False, 'url': '/whatsapp/conversaciones/'})
                    log(f"Conversación marcada como reactivada {filtro.id}", request, "change", obj=filtro.id)
                    messages.success(request, f'Conversación reactivada correctamente.')
                    return JsonResponse(res_json, safe=False)
        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    # ====================== LISTADO CONVERSACIONES =========================
    criterio    = request.GET.get('criterio', '').strip()
    fecha_desde = request.GET.get('fecha_desde', '').strip()
    fecha_hasta = request.GET.get('fecha_hasta', '').strip()
    filtro_sentimiento = request.GET.get('sentimiento', '').strip()
    filtro_clasificacion = request.GET.get('clasificacion', '').strip()

    filtros = Q(contacto__status=True, status=True,
                contacto__sesion__in=sesiones_visibles(request.user),
                contacto__sesion__status=True,
                estado_conversacion=1)
    url_vars = ''

    if sesion_seleccionada:
        filtros &= Q(contacto__sesion=sesion_seleccionada)
        filtros &= filtro_conversaciones_por_rol(request.user, sesion_seleccionada)
        url_vars += f'&sesion={encrypt_sesion_id(sesion_seleccionada.id)}'

    if criterio:
        filtros &= Q(contacto__contacto_numero__icontains=criterio) | Q(contacto__contacto_nombre__icontains=criterio)
        url_vars += '&criterio=' + criterio

    if fecha_desde:
        filtros &= Q(fecha_fin_conversacion__date__gte=fecha_desde)
        url_vars += '&fecha_desde=' + fecha_desde

    if fecha_hasta:
        filtros &= Q(fecha_fin_conversacion__date__lte=fecha_hasta)
        url_vars += '&fecha_hasta=' + fecha_hasta

    if filtro_sentimiento:
        filtros &= Q(sentimiento=filtro_sentimiento)
        url_vars += '&sentimiento=' + filtro_sentimiento

    if filtro_clasificacion:
        filtros &= Q(clasificacion=filtro_clasificacion)
        url_vars += '&clasificacion=' + filtro_clasificacion

    from .models import ESTADOS_CLASIFICACION
    data['ESTADOS_CLASIFICACION'] = ESTADOS_CLASIFICACION
    data['conversacion_selected'] = conversacion_selected
    data['url_vars'] = url_vars
    data['today'] = timezone.now().date()
    data['criterio'] = criterio
    data['fecha_desde'] = fecha_desde
    data['fecha_hasta'] = fecha_hasta
    data['filtro_sentimiento'] = filtro_sentimiento
    data['filtro_clasificacion'] = int(filtro_clasificacion) if filtro_clasificacion else ''

    # Si es una solicitud AJAX para cargar conversaciones
    if request.GET.get('load_conversations'):
        from django.db.models import OuterRef, Subquery
        conversaciones = (
            ConversacionWhatsApp.objects.expirado
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
    from .models import PipelineVenta as _PV
    data['pipelines_disponibles'] = (
        _PV.objects.filter(status=True).prefetch_related('etapas').order_by('-es_default', 'nombre')
    )
    return render(request, 'whatsapp/conversaciones/listado_expirado.html', data)