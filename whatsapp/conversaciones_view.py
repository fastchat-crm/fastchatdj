from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from django.template.loader import render_to_string
from django.utils import timezone
from django.http import JsonResponse

from core.funciones import addData, paginador, secure_module, log
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
                'contacto_foto': conversacion.contacto_foto or ''
            })

    # ====================== ENVIAR MENSAJE =========================
    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST['action']
                if action == 'send':
                    pk = int(request.POST['pk'])
                    texto = request.POST.get('mensaje')
                    archivo = request.FILES.get('archivo')  # Obtener archivo si existe
                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)

                    # Crear instancia del servicio
                    service = WhatsAppService()

                    # Enviar mensaje usando el servicio
                    response = service.send_message(
                        conversacion.sesion.session_id,  # Usar session_id en lugar de número
                        conversacion.contacto_numero,
                        texto,
                        archivo
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
        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    # ====================== LISTADO CONVERSACIONES =========================
    criterio = request.GET.get('criterio', '').strip()
    filtros = Q(status=True, sesion__usuario__id=request.user.id)
    url_vars = ''

    if sesion_seleccionada:
        filtros = filtros & Q(sesion=sesion_seleccionada)
        url_vars += f'&sesion_id={sesion_seleccionada.id}'

    if criterio:
        filtros = filtros & (Q(contacto_numero__icontains=criterio) | Q(contacto_nombre__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio

    # Obtener las conversaciones
    conversaciones = ConversacionWhatsApp.objects.filter(filtros).order_by('tiene_mensaje', '-fecha_ultimo_mensaje')
    data["conversaciones"] = conversaciones
    data["list_count"] = conversaciones.count()
    data["url_vars"] = url_vars
    data["today"] = timezone.now().date()  # Para comparar fechas en la plantilla

    # Si es una solicitud AJAX para cargar conversaciones
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.GET.get('load_conversations'):
        return JsonResponse({
            'html': render_to_string('whatsapp/conversaciones/conversaciones_partial.html',
                                    {'conversaciones': conversaciones, 'today': timezone.now().date()},
                                    request=request)
        })

    return render(request, 'whatsapp/conversaciones/listado.html', data)