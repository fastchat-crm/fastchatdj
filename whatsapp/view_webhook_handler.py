# whatsapp/views.py (webhook_handler adaptado a tus modelos)
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from django.utils import timezone
import logging
from .models import SesionWhatsApp, ConversacionWhatsApp, MensajeWhatsApp

logger = logging.getLogger(__name__)

@csrf_exempt
def webhook_handler(request):
    try:
        data = json.loads(request.body)
        session_id = data.get('session_id')
        event_type = data.get('event_type')
        timestamp = data.get('timestamp')
        event_data = data.get('data', {})

        # Registrar el evento en el log
        logger.info(f"Webhook recibido: {event_type} para sesión {session_id}")

        try:
            sesion = SesionWhatsApp.objects.get(session_id=session_id)

            # Actualizar la última conexión
            sesion.ultima_conexion = timezone.now()

            # Procesar según el tipo de evento
            if event_type == 'qr_code':
                sesion.qr_code = event_data.get('qr_code')
                sesion.estado = 'pendiente'
                logger.info(f"QR Code actualizado para sesión {session_id}")

            elif event_type == 'ready':
                sesion.estado = 'conectado'
                sesion.qr_code = None
                sesion.error_mensaje = None

                # Si hay información del perfil, guardarla
                if event_data.get('profile_picture_base64'):
                    sesion.foto = event_data.get('profile_picture_base64')

                logger.info(f"Sesión {session_id} lista y conectada")

            elif event_type == 'authenticated':
                sesion.estado = 'conectado'
                sesion.qr_code = None
                sesion.error_mensaje = None

                # Si hay información del perfil, guardarla
                if event_data.get('profile_picture_base64'):
                    sesion.foto = event_data.get('profile_picture_base64')

                logger.info(f"Sesión {session_id} autenticada")

            elif event_type == 'auth_failure':
                sesion.estado = 'error'
                sesion.error_mensaje = f"Error de autenticación: {event_data.get('error', 'Desconocido')}"
                logger.error(f"Error de autenticación en sesión {session_id}: {event_data.get('error')}")

            elif event_type == 'disconnected':
                sesion.estado = 'desconectado'
                sesion.error_mensaje = f"Desconectado: {event_data.get('reason', 'Razón desconocida')}"
                logger.info(f"Sesión {session_id} desconectada: {event_data.get('reason')}")

            elif event_type == 'profile_update':
                # Evento específico para actualizar el perfil del usuario
                if event_data.get('profile_picture_base64'):
                    sesion.foto = event_data.get('profile_picture_base64')
                    logger.info(f"Foto de perfil actualizada para sesión {session_id}")

            elif event_type == 'message' or event_type == 'message_sent':
                # Procesar mensaje recibido o enviado
                message_id = event_data.get('message_id')
                remote_jid = event_data.get('from') if event_type == 'message' else event_data.get('to')
                body = event_data.get('body', '')
                has_media = event_data.get('has_media', False)
                message_type = event_data.get('type', 'texto')
                message_timestamp = event_data.get('timestamp')

                # Obtener el nombre del contacto si está disponible
                contact_name = event_data.get('sender_name', '')

                # Normalizar el número de teléfono (quitar @c.us si existe)
                if '@c.us' in remote_jid:
                    contacto_numero = remote_jid.split('@')[0]
                else:
                    contacto_numero = remote_jid

                # Buscar o crear conversación
                conversacion, created = ConversacionWhatsApp.objects.get_or_create(
                    sesion=sesion,
                    contacto_numero=contacto_numero,
                    defaults={
                        'contacto_nombre': contact_name,  # Guardar el nombre al crear
                        'estado': 'activo',
                        'ultimo_mensaje': body,
                        'fecha_ultimo_mensaje': timezone.now()
                    }
                )

                # Si la conversación ya existía pero no tenía nombre, actualizarlo
                if not created and not conversacion.contacto_nombre and contact_name:
                    conversacion.contacto_nombre = contact_name

                # Actualizar último mensaje
                conversacion.ultimo_mensaje = body
                conversacion.fecha_ultimo_mensaje = timezone.now()
                conversacion.save()

                # Determinar tipo de mensaje para nuestro modelo
                tipo_mensaje = 'texto'
                if message_type == 'image':
                    tipo_mensaje = 'imagen'
                elif message_type == 'audio':
                    tipo_mensaje = 'audio'
                elif message_type == 'video':
                    tipo_mensaje = 'video'
                elif message_type == 'document':
                    tipo_mensaje = 'documento'
                elif message_type == 'location':
                    tipo_mensaje = 'ubicacion'
                elif message_type == 'contact':
                    tipo_mensaje = 'contacto'
                elif message_type == 'sticker':
                    tipo_mensaje = 'sticker'

                # Crear mensaje
                msgwp = MensajeWhatsApp.objects.filter(conversacion=conversacion, message_id=message_id).first() or MensajeWhatsApp(
                    message_id=message_id
                )
                msgwp.conversacion = conversacion
                msgwp.remitente = sesion.numero if event_type == 'message_sent' else contacto_numero
                msgwp.mensaje = body
                msgwp.tipo = tipo_mensaje
                msgwp.archivo_url = event_data.get('media_url')
                msgwp.fecha = timezone.now()
                msgwp.leido = event_type == 'message_sent'
                msgwp.fecha_leido = timezone.now() if event_type == 'message_sent' else None
                msgwp.save()

                logger.info(f"Mensaje {'enviado' if event_type == 'message_sent' else 'recibido'} en conversación con {contacto_numero}")
                # Actualizar foto y nombre del remitente si están disponibles
                sender_name = event_data.get('sender_name')
                sender_profile_picture_base64 = event_data.get('sender_profile_picture_base64')

                if (sender_name or sender_profile_picture_base64) and conversacion:
                    actualizado = False
                    if sender_name and (
                            not conversacion.contacto_nombre or conversacion.contacto_nombre != sender_name):
                        conversacion.contacto_nombre = sender_name
                        actualizado = True
                    if sender_profile_picture_base64:
                        conversacion.contacto_foto = sender_profile_picture_base64
                        actualizado = True

                    if actualizado:
                        conversacion.save()
                        logger.info(f"Información de contacto actualizada para {contacto_numero}")

            # También podemos añadir un evento específico para actualizar contactos
            # Añadir este caso en tu webhook_handler
            elif event_type == 'contact_update':
                contacto_numero = event_data.get('number')
                contacto_nombre = event_data.get('name')
                contacto_foto_base64 = event_data.get('profile_picture_base64')

                if contacto_numero:
                    # Normalizar el número
                    if '@c.us' in contacto_numero:
                        contacto_numero = contacto_numero.split('@')[0]

                    # Actualizar todas las conversaciones con este contacto
                    conversaciones = ConversacionWhatsApp.objects.filter(
                        sesion=sesion,
                        contacto_numero=contacto_numero
                    )

                    for conv in conversaciones:
                        actualizado = False
                        if contacto_nombre and (not conv.contacto_nombre or conv.contacto_nombre != contacto_nombre):
                            conv.contacto_nombre = contacto_nombre
                            actualizado = True
                        if contacto_foto_base64:
                            conv.contacto_foto = contacto_foto_base64
                            actualizado = True

                        if actualizado:
                            conv.save()
                            logger.info(f"Contacto actualizado: {contacto_numero} - {contacto_nombre}")

            # Resto del código para manejar mensajes y otros eventos...

            # Guardar los cambios en la sesión
            sesion.save()

            return JsonResponse({'success': True})

        except SesionWhatsApp.DoesNotExist:
            logger.error(f"Sesión no encontrada: {session_id}")
            return JsonResponse({'success': False, 'error': 'Sesión no encontrada'}, status=404)

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'JSON inválido'}, status=400)
    except Exception as e:
        logger.error(f"Error en webhook_handler: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)