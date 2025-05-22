from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from django.template.loader import render_to_string
from django.utils import timezone
from django.http import JsonResponse

from core.funciones import addData, paginador, secure_module, log
from seguridad.templatetags.templatefunctions import encrypt
from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp
# Importar el servicio en lugar de redis_publish
from .services import WhatsAppService

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
                'fecha_inicio': conversacion.fecha_registro.strftime('%d/%m/%Y') or '',
                'fecha_fin': conversacion.fecha_fin_conversacion.strftime('%d/%m/%Y') or '',
            })

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
    criterio = request.GET.get('criterio', '').strip()
    filtros = Q(contacto__status=True, status=True, contacto__sesion__usuario__id=request.user.id, contacto__sesion__status=True)
    url_vars = ''

    if sesion_seleccionada:
        filtros = filtros & Q(contacto__sesion=sesion_seleccionada)
        url_vars += f'&sesion_id={sesion_seleccionada.id}'

    if criterio:
        filtros = filtros & (Q(contacto__contacto_numero__icontains=criterio) | Q(contacto__contacto_nombre__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio

    data['conversacion_selected'] = conversacion_selected
    data["url_vars"] = url_vars
    data["today"] = timezone.now().date()  # Para comparar fechas en la plantilla

    # Si es una solicitud AJAX para cargar conversaciones
    if request.GET.get('load_conversations'):
        conversaciones = ConversacionWhatsApp.objects.expirado.filter(filtros)
        data["conversaciones"] = conversaciones
        data["list_count"] = conversaciones.count()
        return JsonResponse({
            'html': render_to_string('whatsapp/conversaciones/conversaciones_partial.html', {'conversaciones': conversaciones, 'today': timezone.now().date(), 'show_date':True},
                                     request=request)
        })
    return render(request, 'whatsapp/conversaciones/listado_expirado.html', data)