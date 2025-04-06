# whatsapp/views.py (webhook_handler adaptado a tus modelos)
from django.db.models import Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from django.utils import timezone
import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from fastchatdj.settings import NODE_SECRET_KEY
from .models import SesionWhatsApp, ConversacionWhatsApp, MensajeWhatsApp
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)

@csrf_exempt
def webhook_handler(request):
    if request.headers.get('X-API-Key') != NODE_SECRET_KEY:
        return JsonResponse({'message': 'No autorizado'}, status=401)
    try:
        data = json.loads(request.body)
        session_id = data.get('session_id')
        event_type = data.get('event_type')
        timestamp = data.get('timestamp')
        event_data = data.get('data', {})
        channel_layer = get_channel_layer()

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
                sesion.save()
                async_to_sync(channel_layer.group_send)(
                    f'qrsession_{sesion.id}',
                    {
                        'type': 'update_qrsession',
                        'message': {'type': 'update_qrsession', 'qr_code': sesion.qr_code}
                    }
                )

            elif event_type == 'ready':
                sesion.estado = 'conectado'
                sesion.qr_code = None
                sesion.error_mensaje = None

                # Si hay información del perfil, guardarla
                if event_data.get('profile_picture_base64'):
                    sesion.foto = event_data.get('profile_picture_base64')

                sesion.save()

                logger.info(f"Sesión {session_id} lista y conectada")

            elif event_type == 'authenticated':
                sesion.estado = 'conectado'
                sesion.qr_code = None
                sesion.error_mensaje = None

                # Si hay información del perfil, guardarla
                if event_data.get('profile_picture_base64'):
                    sesion.foto = event_data.get('profile_picture_base64')

                sesion.save()

                logger.info(f"Sesión {session_id} autenticada")

            elif event_type == 'auth_failure':
                sesion.estado = 'error'
                sesion.error_mensaje = f"Error de autenticación: {event_data.get('error', 'Desconocido')}"
                logger.error(f"Error de autenticación en sesión {session_id}: {event_data.get('error')}")
                sesion.save()

            elif event_type == 'disconnected':
                sesion.estado = 'desconectado'
                sesion.error_mensaje = f"Desconectado: {event_data.get('reason', 'Razón desconocida')}"
                logger.info(f"Sesión {session_id} desconectada: {event_data.get('reason')}")
                sesion.save()

            elif event_type == 'profile_update':
                # Evento específico para actualizar el perfil del usuario
                if event_data.get('profile_picture_base64'):
                    sesion.foto = event_data.get('profile_picture_base64')
                    logger.info(f"Foto de perfil actualizada para sesión {session_id}")
                    sesion.save()


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
                MensajeWhatsApp.objects.create(
                    conversacion=conversacion,
                    remitente=sesion.numero if event_type == 'message_sent' else contacto_numero,
                    mensaje=body,
                    tipo=tipo_mensaje,
                    archivo_url=event_data.get('media_url'),
                    fecha=timezone.now(),
                    leido=event_type == 'message_sent',  # Mensajes enviados se marcan como leídos
                    fecha_leido=timezone.now() if event_type == 'message_sent' else None,
                    mensaje_id_externo=message_id  # Guardar el ID externo del mensaje
                )

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

                mensajes = MensajeWhatsApp.objects.filter(
                    conversacion=conversacion
                ).order_by('fecha')

                html = render_to_string('whatsapp/conversaciones/mensajes_partial.html', {
                    'mensajes': mensajes,
                    'conversacion': conversacion
                })

                async_to_sync(channel_layer.group_send)(
                    f'chat_{conversacion.id}',
                    {
                        'type': 'chat_message',
                        'message': {
                            'type': 'new_message',
                            'conversacion_id': str(conversacion.id),
                            'html': html
                        }
                    }
                )
                async_to_sync(channel_layer.group_send)(
                    f'session_{conversacion.sesion_id}',
                    {
                        'type': 'update_session',
                        'message': {'type': 'update_session',}
                    }
                )

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

                    # Buscar conversaciones existentes con este contacto
                    conversaciones = ConversacionWhatsApp.objects.filter(
                        sesion=sesion,
                        contacto_numero=contacto_numero
                    )

                    if conversaciones.exists():
                        # Actualizar conversaciones existentes
                        for conv in conversaciones:
                            actualizado = False
                            if contacto_nombre and (
                                    not conv.contacto_nombre or conv.contacto_nombre != contacto_nombre):
                                conv.contacto_nombre = contacto_nombre
                                actualizado = True
                            if contacto_foto_base64:
                                conv.contacto_foto = contacto_foto_base64
                                actualizado = True

                            if actualizado:
                                conv.save()
                                logger.info(f"Contacto actualizado: {contacto_numero} - {contacto_nombre}")
                    else:
                        # Crear una nueva conversación si no existe
                        try:
                            nueva_conversacion = ConversacionWhatsApp.objects.create(
                                sesion=sesion,
                                contacto_numero=contacto_numero,
                                contacto_nombre=contacto_nombre,
                                contacto_foto=contacto_foto_base64,
                                estado='pendiente',  # O el estado inicial que prefieras
                                ultimo_mensaje='',
                                fecha_ultimo_mensaje=timezone.now()
                            )
                            logger.info(
                                f"Nueva conversación creada para contacto: {contacto_numero} - {contacto_nombre}")
                        except Exception as e:
                            logger.error(f"Error al crear conversación para contacto {contacto_numero}: {str(e)}")

            elif event_type == 'message_deleted':
                # Procesar mensaje eliminado
                message_id = event_data.get('message_id')
                message_id2 = message_id
                msgids = message_id.split('@c.us_')
                if len(msgids) > 1:
                    message_id2 = msgids[1]
                remote_jid = event_data.get('from')
                timestamp = event_data.get('timestamp')

                # Normalizar el número de teléfono
                if '@c.us' in remote_jid:
                    contacto_numero = remote_jid.split('@')[0]
                else:
                    contacto_numero = remote_jid

                try:
                    # Buscar la conversación
                    conversacion = ConversacionWhatsApp.objects.get(
                        sesion=sesion,
                        contacto_numero=contacto_numero
                    )

                    # Buscar el mensaje por su ID externo (si lo guardamos)
                    # Si no guardamos el ID externo, podemos intentar buscarlo por timestamp
                    mensaje = MensajeWhatsApp.objects.filter(
                        Q(mensaje_id_externo=message_id) | Q(mensaje_id_externo=message_id2),
                        conversacion=conversacion
                    ).first()

                    if not mensaje and timestamp:
                        # Intentar buscar por timestamp si no encontramos por ID
                        # Esto es menos preciso pero puede funcionar

                        # Convertir timestamp a datetime
                        fecha_mensaje = datetime.fromtimestamp(timestamp).replace(tzinfo=pytz.UTC)

                        # Buscar mensajes cercanos a esa fecha
                        mensajes_cercanos = MensajeWhatsApp.objects.filter(
                            conversacion=conversacion,
                            fecha__range=(
                                fecha_mensaje - timezone.timedelta(minutes=1),
                                fecha_mensaje + timezone.timedelta(minutes=1)
                            )
                        )

                        if mensajes_cercanos.exists():
                            mensaje = mensajes_cercanos.first()

                    if mensaje:
                        # Marcar el mensaje como eliminado
                        mensaje.eliminado = True
                        mensaje.fecha_eliminacion = timezone.now()
                        mensaje.save()

                        logger.info(f"Mensaje marcado como eliminado: {message_id}")
                    else:
                        logger.warning(f"No se encontró el mensaje a eliminar: {message_id}")

                except ConversacionWhatsApp.DoesNotExist:
                    logger.warning(f"No se encontró la conversación para el mensaje eliminado: {contacto_numero}")
                except Exception as e:
                    logger.error(f"Error al procesar mensaje eliminado: {str(e)}")

            elif event_type == 'message_edited':
                # Procesar mensaje editado
                message_id = event_data.get('message_id') or ''
                message_id2 = message_id
                msgids = message_id.split('@c.us_')
                if len(msgids) > 1:
                    message_id2 = msgids[1]
                remote_jid = event_data.get('from')
                body = event_data.get('body', '')
                timestamp = event_data.get('timestamp')
                edit_timestamp = event_data.get('edit_timestamp')

                # Normalizar el número de teléfono
                if '@c.us' in remote_jid:
                    contacto_numero = remote_jid.split('@')[0]
                else:
                    contacto_numero = remote_jid

                try:
                    # Buscar la conversación
                    conversacion = ConversacionWhatsApp.objects.get(
                        sesion=sesion,
                        contacto_numero=contacto_numero
                    )

                    # Buscar el mensaje por su ID externo
                    mensaje = MensajeWhatsApp.objects.filter(
                        Q(mensaje_id_externo=message_id) | Q(mensaje_id_externo=message_id2),
                        conversacion=conversacion
                    ).first()

                    if not mensaje and timestamp:
                        # Intentar buscar por timestamp si no encontramos por ID

                        # Convertir timestamp a datetime
                        fecha_mensaje = datetime.fromtimestamp(timestamp).replace(tzinfo=pytz.UTC)

                        # Buscar mensajes cercanos a esa fecha
                        mensajes_cercanos = MensajeWhatsApp.objects.filter(
                            conversacion=conversacion,
                            fecha__range=(
                                fecha_mensaje - timezone.timedelta(minutes=1),
                                fecha_mensaje + timezone.timedelta(minutes=1)
                            )
                        )

                        if mensajes_cercanos.exists():
                            mensaje = mensajes_cercanos.first()

                    if mensaje:
                        # Guardar el mensaje original
                        if not mensaje.mensaje_original:
                            mensaje.mensaje_original = mensaje.mensaje

                        # Actualizar el mensaje con el contenido editado
                        mensaje.mensaje = body
                        mensaje.editado = True
                        mensaje.fecha_edicion = timezone.now()
                        mensaje.save()

                        logger.info(f"Mensaje editado: {message_id}")
                    else:
                        logger.warning(f"No se encontró el mensaje a editar: {message_id}")
                except ConversacionWhatsApp.DoesNotExist:
                    logger.warning(f"No se encontró la conversación para el mensaje editado: {contacto_numero}")
                except Exception as e:
                    logger.error(f"Error al procesar mensaje editado: {str(e)}")
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