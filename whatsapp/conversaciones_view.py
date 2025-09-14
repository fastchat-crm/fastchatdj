from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from django.template.loader import render_to_string, get_template
from django.utils import timezone
from django.http import JsonResponse

from core.funciones import addData, paginador, secure_module, log
from seguridad.templatetags.templatefunctions import encrypt
from .forms import CambiarClasificacionForm, CambiarNombreContactoForm
from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp
# Importar el servicio en lugar de redis_publish
from .services import WhatsAppService

@login_required
@secure_module
def conversacionesView(request):
    data = {
        'titulo': 'Conversaciones WhatsApp',
        'modulo': 'Conversaciones WhatsApp',
        'ruta': request.path
    }
    addData(request, data)

    # Obtener todas las sesiones activas
    sesiones = SesionWhatsApp.objects.filter(usuario_id=request.user.id, status=True, estado='conectado').order_by('-ultima_conexion')
    data['sesiones'] = sesiones

    # Sesión seleccionada (por defecto la primera)
    sesion_id = request.GET.get('sesion_id')
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
        data['action'] = action = request.GET['action']
        if action == 'ver_mensajes':
            pk = int(request.GET['pk'])
            conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
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
            })
        elif action == 'cambiar-clasificacion':
            try:
                filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
                form = CambiarClasificacionForm(instance=filtro)
                data.update({
                    'form': form,
                    'filtro': filtro,
                })
                template = get_template("whatsapp/conversaciones/form.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})
        elif action == 'cambiar-nombre-contacto':
            try:
                filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
                form = CambiarNombreContactoForm(instance=filtro.contacto)
                data.update({
                    'form': form,
                    'filtro': filtro,
                })
                template = get_template("whatsapp/conversaciones/form.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})

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

                    # Crear instancia del servicio
                    service = WhatsAppService()

                    if archivo:
                        response = service.send_media_message(
                            conversacion.sesion.session_id, conversacion.from_number, caption=texto,
                            file_content=archivo.read(), filename=archivo.name
                        )
                    else:
                        response = service.send_text_message(
                            conversacion.sesion.session_id, conversacion.from_number, texto
                        )

                    if not response.get('success', False):
                        return JsonResponse({
                            'error': True,
                            'message': f"Error al enviar mensaje: {response.get('message', 'Error desconocido')}"
                        })

                    # Determinar tipo de mensaje
                    tipo_mensaje = 'texto'
                    archivo_url = None

                    if archivo:
                        # Determinar tipo basado en el content_type
                        content_type = archivo.content_type
                        if 'image' in content_type:
                            tipo_mensaje = 'imagen'
                        elif 'audio' in content_type:
                            tipo_mensaje = 'audio'
                        elif 'video' in content_type:
                            tipo_mensaje = 'video'
                        else:
                            tipo_mensaje = 'documento'

                        # Si la respuesta incluye una URL del archivo, guardarla
                        archivo_url = response.get('media_url')

                    # Guardamos en BD
                    mensaje = MensajeWhatsApp(
                        mensaje_id_externo=response.get('message_id'),
                        conversacion=conversacion,
                        remitente=conversacion.sesion.numero,
                        mensaje=texto,
                        tipo=tipo_mensaje,
                        archivo_url=archivo_url,
                        fecha=timezone.now(),
                        leido=True,
                        fecha_leido=timezone.now()
                    )
                    #
                    # # Actualizar último mensaje de la conversación
                    # conversacion.ultimo_mensaje = texto
                    # conversacion.fecha_ultimo_mensaje = timezone.now()
                    # conversacion.save()

                    log(f"Mensaje enviado a {conversacion.contacto_numero}", request, "add", obj=conversacion.id)

                    # Devolver el HTML del mensaje para añadirlo al chat
                    return JsonResponse({
                        'error': False,
                        'mensaje_html': render_to_string('whatsapp/conversaciones/mensaje_enviado_partial.html',
                                                        {'mensaje': mensaje},
                                                        request=request)
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
                elif action == 'cambiar-nombre-contacto':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    contacto = filtro.contacto
                    form = CambiarNombreContactoForm(request.POST, instance=contacto, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Nombre de contacto {contacto.__str__()} cambiado para la conversación {filtro.id}", request, "change", obj=filtro.id)
                        res_json.append({'error': False, 'reload': True})
                        messages.success(request, 'Nombre de contacto cambiada correctamente.')
                        return JsonResponse(res_json, safe=False)
                    else:
                        raise NameError(f'Error al guardar la clasificación: {form.errors}')
                elif action == 'marcar-resuelto':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    contacto = filtro.contacto
                    if contacto.sesion.mensaje_despedida:
                        from_number = contacto.from_number
                        session_id = contacto.sesion.session_id
                        # Crear instancia del servicio
                        service = WhatsAppService()
                        result = service.send_text_message(session_id, from_number, contacto.sesion.mensaje_despedida, simularEscritura=True)
                        if not result.get('success'):
                            raise NameError(f'{result.get("error", "Error desconocido")}')
                        filtro.despedida_enviado = True
                    filtro.estado_conversacion = 1
                    filtro.fecha_fin_conversacion = timezone.now()
                    res_json.append({ 'error':False, 'url': f'/whatsapp/conversaciones-finalizadas/' })
                    request.session['contactoId'] = encrypt(filtro.id)
                    filtro.resumir_conversacion()
                    filtro.save(request)
                    log(f"Conversación marcada como resuelta {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse(res_json, safe=False)
                elif action == 'terminar-sin-despedida':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    filtro.estado_conversacion = 1
                    filtro.fecha_fin_conversacion = timezone.now()
                    res_json.append({ 'error':False, 'url': f'/whatsapp/conversaciones-finalizadas/' })
                    request.session['contactoId'] = encrypt(filtro.id)
                    filtro.save(request)
                    log(f"Conversación marcada como resuelta {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse(res_json, safe=False)
                elif action == 'transcribe_audio':
                    service = WhatsAppService()
                    msg = MensajeWhatsApp.objects.select_related('conversacion__contacto__sesion').get(id=request.POST['id'])
                    service.transcribe_audio(msg, 'small', msg.conversacion.contacto.sesion.language.split('-')[0])
                    return JsonResponse({})


        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    # ====================== LISTADO CONVERSACIONES =========================
    criterio = request.GET.get('criterio', '').strip()
    filtros = Q(contacto__status=True, status=True, contacto__sesion__usuario__id=request.user.id, contacto__sesion__status=True, estado_conversacion=0)
    url_vars = ''

    if sesion_seleccionada:
        filtros = filtros & Q(contacto__sesion=sesion_seleccionada)
        url_vars += f'&sesion_id={sesion_seleccionada.id}'

    if criterio:
        filtros = filtros & (Q(contacto__contacto_numero__icontains=criterio) | Q(contacto__contacto_nombre__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio

    data["url_vars"] = url_vars
    data['conversacion_selected'] = conversacion_selected
    data["today"] = timezone.now().date()  # Para comparar fechas en la plantilla

    # Si es una solicitud AJAX para cargar conversaciones
    if request.GET.get('load_conversations'):
        # Obtener las conversaciones
        conversaciones = ConversacionWhatsApp.objects.sin_expirar.filter(filtros)
        data["conversaciones"] = conversaciones
        data["list_count"] = conversaciones.count()
        return JsonResponse({
            'html': render_to_string('whatsapp/conversaciones/conversaciones_partial.html',
                                    {'conversaciones': conversaciones, 'today': timezone.now().date()},
                                    request=request)
        })

    return render(request, 'whatsapp/conversaciones/listado.html', data)
