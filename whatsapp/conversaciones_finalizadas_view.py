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
from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp
from .services import WhatsAppService
from .forms import CambiarClasificacionForm
from .conversaciones_view import _control_respuestas, _tokens_conversacion, _estadisticas_conversacion

@login_required
@secure_module
def conversacionesFinalizadasView(request):
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
        action = request.GET['action']
        if action == 'ver_mensajes':
            try:
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
                    'show_date': True,
                    'fecha_inicio': conversacion.fecha_registro.strftime('%d/%m/%Y') if conversacion.fecha_registro else '',
                    'fecha_fin': conversacion.fecha_fin_conversacion.strftime('%d/%m/%Y') if conversacion.fecha_fin_conversacion else '',
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

                    tipo_mensaje = 'texto'
                    if archivo:
                        ct = archivo.content_type or ''
                        if 'image' in ct:
                            tipo_mensaje = 'imagen'
                        elif 'audio' in ct:
                            tipo_mensaje = 'audio'
                        elif 'video' in ct:
                            tipo_mensaje = 'video'
                        else:
                            tipo_mensaje = 'documento'

                    if archivo:
                        file_bytes = archivo.read()
                        response = service.send_media_message(
                            conversacion.sesion.session_id, conversacion.from_number, caption=texto,
                            file_content=file_bytes, filename=archivo.name
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

    filtros = Q(contacto__status=True, status=True,
                contacto__sesion__usuario__id=request.user.id,
                contacto__sesion__status=True)
    url_vars = ''

    if sesion_seleccionada:
        filtros &= Q(contacto__sesion=sesion_seleccionada)
        url_vars += f'&sesion_id={sesion_seleccionada.id}'

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

    data['conversacion_selected'] = conversacion_selected
    data['url_vars'] = url_vars
    data['today'] = timezone.now().date()
    data['criterio'] = criterio
    data['fecha_desde'] = fecha_desde
    data['fecha_hasta'] = fecha_hasta
    data['filtro_sentimiento'] = filtro_sentimiento

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
    return render(request, 'whatsapp/conversaciones/listado_expirado.html', data)