from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from django.template.loader import render_to_string, get_template
from django.utils import timezone
from django.http import JsonResponse

from core.funciones import addData, paginador, secure_module, log, leer_sesion_id, encrypt_sesion_id
from seguridad.templatetags.templatefunctions import encrypt
from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp
from .services import WhatsAppService, get_whatsapp_service
from .forms import CambiarClasificacionForm
from .view_conversaciones import _control_respuestas, _tokens_conversacion, _estadisticas_conversacion

HORAS_BLOQUEO_REACTIVAR_FINALIZADA = 20


def _bloqueo_reactivar(conversacion):
    """Bloquea reactivar/enviar mientras la conversacion tenga menos de 20h desde fecha_registro."""
    if not conversacion.fecha_registro:
        return False, None
    disponible = conversacion.fecha_registro + timedelta(hours=HORAS_BLOQUEO_REACTIVAR_FINALIZADA)
    return timezone.now() < disponible, disponible

@login_required
@secure_module
def conversacionesFinalizadasView(request):
    data = {
        'titulo': 'Conversaciones WhatsApp',
        'modulo': 'Conversaciones WhatsApp',
        'ruta': request.path
    }
    addData(request, data)

    # Todas las sesiones del usuario (incluye desconectadas para ver historial).
    sesiones = SesionWhatsApp.objects.filter(usuario_id=request.user.id, status=True).order_by('-ultima_conexion')
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
    if sesion_id:
        sesion_seleccionada = get_object_or_404(SesionWhatsApp, id=sesion_id)
    elif sesiones.exists():
        sesion_seleccionada = sesiones.first()
    else:
        sesion_seleccionada = None

    data['sesion_seleccionada'] = sesion_seleccionada

    # ====================== VER MENSAJES =========================
    if request.method == 'GET' and 'action' in request.GET:
        action = request.GET['action']
        if action == 'ver_mensajes':
            try:
                pk = int(request.GET['pk'])
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                mensajes = MensajeWhatsApp.objects.filter(conversacion=conversacion).order_by('fecha')
                data['conversacion'] = conversacion
                data['mensajes'] = mensajes
                bloqueada, disponible_en = _bloqueo_reactivar(conversacion)
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
                    'reactivar_disponible_en': disponible_en.isoformat() if disponible_en else None,
                    'reactivar_horas_bloqueo': HORAS_BLOQUEO_REACTIVAR_FINALIZADA,
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
        elif action == 'cambiar-clasificacion':
            try:
                filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
                form = CambiarClasificacionForm(instance=filtro)
                ctx = {
                    'form': form,
                    'filtro': filtro,
                    'action': 'cambiar-clasificacion',
                    'ruta': request.path,
                }
                return JsonResponse({
                    "result": True,
                    'data': render_to_string("whatsapp/conversaciones/form.html", ctx, request=request),
                })
            except Exception as ex:
                import traceback
                traceback.print_exc()
                return JsonResponse({"result": False, 'message': str(ex)})
        elif action == 'listar_plantillas_meta':
            try:
                pk = int(request.GET['pk'])
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
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
                if action == 'send':
                    pk = int(request.POST['pk'])
                    texto = request.POST.get('mensaje')
                    archivo = request.FILES.get('archivo')  # Obtener archivo si existe
                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)

                    bloqueada, disponible_en = _bloqueo_reactivar(conversacion)
                    if bloqueada:
                        return JsonResponse({
                            'error': True,
                            'message': f'No se puede enviar mensajes hasta que la conversacion tenga {HORAS_BLOQUEO_REACTIVAR_FINALIZADA}h de creada. Disponible: {disponible_en.strftime("%d/%m/%Y %H:%M")}.',
                        })

                    # Crear instancia del servicio segun proveedor de la sesion
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

                    log(f"Mensaje enviado a {conversacion.contacto_numero}", request, "add", obj=conversacion.id)

                    # Devolver el HTML del mensaje para añadirlo al chat
                    return JsonResponse({
                        'error': False,
                        'mensaje_html': render_to_string('whatsapp/conversaciones/mensaje_enviado_partial.html',
                                                        {'mensaje': mensaje},
                                                        request=request)
                    })
                elif action == 'enviar_plantilla_meta':
                    # Envia plantilla Meta desde una conversacion FINALIZADA.
                    # Si el envio tiene exito, reactiva la conversacion para que
                    # el agente pueda continuar el hilo en la vista activa.
                    import json as _json
                    from .models import PlantillaWhatsApp
                    from dateutil.relativedelta import relativedelta

                    pk = int(request.POST['pk'])
                    plantilla_id = int(request.POST['plantilla_id'])
                    params_cuerpo = _json.loads(request.POST.get('params_cuerpo_json') or '[]')
                    params_header = _json.loads(request.POST.get('params_header_json') or '[]')

                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)

                    bloqueada, disponible_en = _bloqueo_reactivar(conversacion)
                    if bloqueada:
                        return JsonResponse({
                            'error': True,
                            'message': f'No se puede reactivar hasta que la conversacion tenga {HORAS_BLOQUEO_REACTIVAR_FINALIZADA}h de creada. Disponible: {disponible_en.strftime("%d/%m/%Y %H:%M")}.',
                        })

                    sesion = conversacion.sesion
                    if not getattr(sesion, 'es_meta', False):
                        return JsonResponse({'error': True, 'message': 'La sesion no es Meta.'})
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

                    # Render del cuerpo con placeholders sustituidos (para historial)
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

                    # Reactivar conversacion cerrada
                    min_sesion = int(getattr(sesion, 'min_sesion', None) or 10)
                    conversacion.estado_conversacion = 0
                    conversacion.conversacion_finalizada = False
                    conversacion.despedida_enviado = False
                    conversacion.fecha_fin_conversacion = None
                    conversacion.duracion_conversacion = None
                    conversacion.fecha_hora_expira = timezone.now() + relativedelta(minutes=min_sesion)
                    conversacion.save(update_fields=[
                        'estado_conversacion', 'conversacion_finalizada', 'despedida_enviado',
                        'fecha_fin_conversacion', 'duracion_conversacion', 'fecha_hora_expira',
                    ])

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

                    if not conversacion.primer_agente:
                        conversacion.primer_agente = request.user
                        conversacion.save(update_fields=['primer_agente'])

                    log(
                        f"Plantilla Meta '{plantilla.nombre}' enviada y conversacion {conversacion.id} reactivada",
                        request, "add", obj=conversacion.id,
                    )

                    # Llevar al agente a la vista de conversaciones activas
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
                elif action == 'cambiar-clasificacion':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    form = CambiarClasificacionForm(request.POST, instance=filtro, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Clasificación cambiada para la conversación {filtro.id}", request, "edit", obj=filtro.id)
                        res_json.append({'error': False, 'reload': True})
                        messages.success(request, 'Clasificación cambiada correctamente.')
                        return JsonResponse(res_json, safe=False)
                    else:
                        raise NameError(f'Error al guardar la clasificación: {form.errors}')
                elif action == 'marcar-reactivar':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    bloqueada, disponible_en = _bloqueo_reactivar(filtro)
                    if bloqueada:
                        res_json.append({
                            'error': True,
                            'message': f'No se puede reactivar hasta que la conversacion tenga {HORAS_BLOQUEO_REACTIVAR_FINALIZADA}h de creada. Disponible: {disponible_en.strftime("%d/%m/%Y %H:%M")}.',
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
                contacto__sesion__usuario__id=request.user.id,
                contacto__sesion__status=True,
                estado_conversacion=1)
    url_vars = ''

    if sesion_seleccionada:
        filtros &= Q(contacto__sesion=sesion_seleccionada)
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
        conversaciones = ConversacionWhatsApp.objects.expirado.filter(filtros).order_by('-fecha_fin_conversacion')
        return JsonResponse({
            'html': render_to_string(
                'whatsapp/conversaciones/conversaciones_partial.html',
                {'conversaciones': conversaciones, 'today': timezone.now().date(), 'show_date': True},
                request=request
            )
        })
    from .models import PipelineVenta as _PV
    data['pipelines_disponibles'] = (
        _PV.objects.filter(status=True).prefetch_related('etapas').order_by('-es_default', 'nombre')
    )
    return render(request, 'whatsapp/conversaciones/listado_expirado.html', data)