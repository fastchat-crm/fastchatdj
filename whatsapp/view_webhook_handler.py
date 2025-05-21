# whatsapp/views.py (webhook_handler)
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from django.utils import timezone
import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import base64
import os
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.conf import settings

from core.funciones_adicionales import get_image_as_base64
from .models import (
    SesionWhatsApp,
    ConversacionWhatsApp, Contacto,
    MensajeWhatsApp,
    EstadisticasConversacion
)
from .services import WhatsAppService

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def webhook_handler(request):
    """
    Manejador de webhooks para eventos de WhatsApp
    """
    # Verificar la clave API
    whatsapp_service = WhatsAppService()
    try:
        # Parsear los datos recibidos

        data = json.loads(request.body)
        event_type = data.get('type')
        event_data = data.get('data', {})
        session_id = event_data.get('sessionId')
        msgerror = ''

        # Obtener la sesión
        try:
            session = SesionWhatsApp.objects.get(session_id=session_id)
        except SesionWhatsApp.DoesNotExist:
            logger.error(f"Sesión no encontrada: {session_id}")
            whatsapp_service.close_session(session_id)
            return JsonResponse({'message': 'Sesión no encontrada'}, status=404)

        # Obtener el channel layer para notificaciones en tiempo real
        channel_layer = get_channel_layer()

        # Procesar el evento según su tipo
        if event_type == 'qr_code':
            # Actualizar el código QR en la sesión
            session.qr_code = event_data.get('qrCode')
            session.estado = 'pendiente'
            session.save()

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'qr_code',
                    'session_id': session.id,
                    'qr_code': session.qr_code
                }
            )

            logger.info(f"Código QR actualizado para la sesión {session_id}")

        elif event_type == 'ready':
            guardar = True
            # Guardar información del usuario si está disponible
            if 'user' in event_data:
                user_info = event_data.get('user', {})
                if 'userImage' in event_data and event_data.get('userImage'):
                    session.foto = f'data:image/jpg;base64,{get_image_as_base64(event_data.get("userImage"))}'
                if 'id' in user_info:
                    numero_list = []
                    for x in user_info['id']:
                        if not x.isdigit():
                            break
                        numero_list.append(x)
                    numero = "".join(numero_list)
                    whatsapp_id = user_info['id']
                    if session.numero and session.numero != numero:
                        guardar = False
                        msgerror = 'No puede registrar otra cuenta de whatsapp en esta sesión'
                    if guardar:
                        session.numero = numero
                        session.whatsapp_id = whatsapp_id
                        if not session.nombre:
                            session.nombre = user_info.get('pushName') or user_info.get('verifiedBizName') or user_info.get('name') or user_info.get('notify') or user_info.get('verifiedName') or ''

            if guardar:
                session.estado = 'conectado'
                session.ultima_conexion = timezone.now()
                session.error_mensaje = None
                session.save()

                # Notificar a través de WebSockets
                async_to_sync(channel_layer.group_send)(
                    f"whatsapp_session_{session.id}",
                    {
                        'type': 'whatsapp_event',
                        'event': 'ready',
                        'session_id': session.id
                    }
                )

                logger.info(f"Sesión {session_id} conectada correctamente")
            else:
                async_to_sync(channel_layer.group_send)(
                    f"whatsapp_session_{session.id}",
                    {
                        'type': 'whatsapp_event',
                        'event': 'error',
                        'session_id': session.id,
                        'msgerror': msgerror
                    }
                )
                whatsapp_service.close_session(session.session_id)

        elif event_type == 'authenticated':
            # Actualizar el estado de la sesión
            session.estado = 'conectado'
            session.ultima_conexion = timezone.now()
            session.error_mensaje = None
            session.save()

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'authenticated',
                    'session_id': session.id
                }
            )

            logger.info(f"Sesión {session_id} autenticada")

        elif event_type == 'contacts_list':
            contacts_list = json.loads(session.contacts_list or '[]')
            new_contacts_list = []
            ids = [x["id"] for x in event_data.get('contacts_list') or []]
            numbers = ["".join([y for y in x["id"] if y.isdigit()]) for x in event_data.get('contacts_list') or []]
            for c in contacts_list:
                if not c["id"] in ids:
                    if numbers and c.get("contacto_numero") and c['contacto_numero'] in numbers:
                        continue
                    new_contacts_list.append(c)
            contacts_list = new_contacts_list + event_data.get('contacts_list') or []
            new_contacts_list = []
            for i, c in enumerate(contacts_list):
                contacts_list[i]['contacto_numero'] = contacto_numero = "".join([y for y in (c.get('id') or '') if y.isdigit()])
                if contacto_numero:
                    new_contacts_list.append(contacts_list[i])
            session.contacts_list = json.dumps(new_contacts_list)
            session.contacts_length = len(new_contacts_list)
            session.save()

        elif event_type == 'auth_failure':
            # Actualizar el estado de la sesión
            session.estado = 'error'
            session.error_mensaje = "Error de autenticación"
            session.save()

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'auth_failure',
                    'session_id': session.id,
                    'error': session.error_mensaje,
                    'msgerror': msgerror
                }
            )

            logger.error(f"Error de autenticación en la sesión {session_id}")

        elif event_type == 'disconnected':
            # Actualizar el estado de la sesión
            session.estado = 'desconectado'
            session.save()

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'disconnected',
                    'session_id': session.id,
                    'reason': event_data.get('reason', 'unknown'),
                    'msgerror': msgerror
                }
            )

            logger.info(f"Sesión {session_id} desconectada")

        elif event_type == 'message':
            # Procesar mensaje entrante
            if event_data.get('message') and event_data['message'].get('protocolMessage') and event_data['message']['protocolMessage'].get('type') == 'MESSAGE_EDIT':
                process_edited_message(session, event_data['message']['protocolMessage'], event_data['from'], channel_layer)
            elif event_data.get('message') and event_data['message'].get('editedMessage') and event_data['message']['editedMessage']['message']['protocolMessage'].get('type') == 'MESSAGE_EDIT':
                process_edited_message(session, event_data['message']['editedMessage']['message']['protocolMessage'], event_data['from'], channel_layer)
            elif event_data.get('message') and event_data['message'].get('protocolMessage') and event_data['message']['protocolMessage'].get('type') == 'REVOKE':
                process_deleted_message(session, event_data, channel_layer)
            elif event_data.get('fromMe'):
                process_sent_message(session, event_data, channel_layer)
            else:
                process_incoming_message(session, event_data, channel_layer)

        elif event_type == 'message_sent':
            # Procesar mensaje enviado
            process_sent_message(session, event_data, channel_layer)

        elif event_type == 'message_deleted':
            # Procesar mensaje eliminado
            process_deleted_message(session, event_data, channel_layer)

        # elif event_type == 'contact_update':
        #     # Procesar actualización de contacto
        #     process_contact_update(session, event_data, channel_layer)

        elif event_type == 'profile_update':
            # Procesar actualización de perfil
            process_profile_update(session, event_data, channel_layer)

        # Responder con éxito
        return JsonResponse({'message': 'Evento procesado correctamente'})

    except json.JSONDecodeError:
        logger.error("Error al decodificar JSON del webhook")
        return JsonResponse({'message': 'JSON inválido'}, status=400)
    except Exception as e:
        logger.exception(f"Error procesando webhook: {str(e)}")
        return JsonResponse({'message': f'Error: {str(e)}'}, status=500)

def process_incoming_message(session, event_data, channel_layer):
    """
    Procesa un mensaje entrante de WhatsApp
    """
    try:
        # Extraer datos del mensaje
        message_id = event_data.get('id')
        from_number = event_data.get('from')
        timestamp = event_data.get('timestamp')
        push_name = event_data.get('pushName', '')
        message_content = event_data.get('message', {})
        from_me = bool(event_data.get('fromMe', False))
        userImage = event_data.get('userImage')

        # Convertir timestamp a datetime
        if isinstance(timestamp, int):
            message_date = timezone.datetime.fromtimestamp(timestamp, tz=timezone.get_current_timezone())
        else:
            message_date = timezone.now()

        # Limpiar el número de teléfono (quitar el @s.whatsapp.net)
        contacto_numero = ''
        if '@' in from_number:
            contacto_numero = from_number.split('@')[0]

        if session.numero == contacto_numero:
            return

        # Buscar o crear la conversación
        contacto = Contacto.objects.filter(sesion=session, from_number=from_number).first() or Contacto(
            sesion=session, from_number=from_number
        )
        contacto.estado = 'activo'

        # Actualizar nombre del contacto si está disponible
        if not contacto.contacto_nombre:
            contacts_list = [c.get('name') or c.get('notify') or '' for c in json.loads(session.contacts_list or '[]') if c["id"] == from_number]
            contacto.contacto_nombre = push_name
            if contacts_list and contacts_list[0]:
                contacto.contacto_nombre = contacts_list[0]
        if not contacto.contacto_numero:
            contacto.contacto_numero = contacto_numero

        if userImage:
            contacto.contacto_foto = f'data:image/jpg;base64,{get_image_as_base64(userImage)}'

        contacto.save()

        # Determinar el tipo de mensaje y su contenido
        message_type = 'texto'
        message_text = ''
        file_url = None

        # Procesar texto
        if 'conversation' in message_content:
            message_type = 'texto'
            message_text = message_content.get('conversation', '')
        elif 'extendedTextMessage' in message_content:
            message_type = 'texto'
            message_text = message_content.get('extendedTextMessage', {}).get('text', '')

        # Procesar archivos multimedia
        media_types = {
            'imageMessage': ('imagen', 'fileName', 'mimetype', 'caption'),
            'videoMessage': ('video', 'fileName', 'mimetype', 'caption'),
            'audioMessage': ('audio', 'fileName', 'mimetype', None),
            'documentMessage': ('documento', 'fileName', 'mimetype', 'caption'),
            'stickerMessage': ('sticker', None, 'mimetype', None)
        }

        for media_key, (type_name, filename_key, mimetype_key, caption_key) in media_types.items():
            if media_key in message_content:
                media_msg = message_content.get(media_key, {})
                message_type = type_name

                # Obtener el texto del caption si existe
                if caption_key and caption_key in media_msg:
                    message_text = media_msg.get(caption_key, '') or type_name or ''

                message_text = message_text or type_name

                # Procesar archivo multimedia si hay datos
                if 'mediaData' in event_data and event_data.get('mediaData'):
                    media_data = event_data['mediaData']
                    filename = media_msg.get(filename_key, f"{type_name}_{message_id}")

                    # Guardar el archivo
                    file_url = save_media_file(media_data, filename, session.id, contacto.id)

        # Actualizar la conversación con el último mensaje
        contacto.ultimo_mensaje = message_text[:100] + ('...' if len(message_text) > 100 else '')
        contacto.fecha_ultimo_mensaje = message_date
        contacto.save()

        conversation = ConversacionWhatsApp.objects.sin_expirar.filter(contacto=contacto).first() or \
                       ConversacionWhatsApp.objects.create(contacto=contacto)

        # Crear el mensaje
        message = MensajeWhatsApp.objects.create(
            conversacion=conversation,
            remitente=from_number,
            mensaje=message_text,
            tipo=message_type,
            archivo_url=file_url,
            fecha=message_date,
            mensaje_id_externo=message_id
        )

        # Actualizar estadísticas
        update_conversation_stats(conversation)

        if not conversation.bienvenida_enviado:
            if conversation.sesion.mensaje_bienvenida:
                whatsapp_service = WhatsAppService()
                whatsapp_service.send_text_message(conversation.sesion.session_id, contacto.from_number, conversation.sesion.mensaje_bienvenida, simularEscritura=True)
            conversation.bienvenida_enviado = True
            conversation.save()
        # Notificar a través de WebSockets
        async_to_sync(channel_layer.group_send)(
            f"chat_{conversation.id}",
            {
                'type': 'whatsapp_message',
                'event': 'new_message',
                'conversation_id': conversation.id,
                'message_id': message.id,
                'message_type': message_type,
                'message_text': message_text,
                'sender': from_number,
                'timestamp': message_date.isoformat()
            }
        )

        async_to_sync(channel_layer.group_send)(
            f"whatsapp_sessionroom_{session.id}",
            {
                'type': 'whatsapp_event',
                'event': 'new_message',
                'conversation_id': conversation.id,
                'timestamp': message_date.isoformat()
            }
        )

        logger.info(f"Mensaje recibido de {from_number} en la sesión {session.session_id}")

    except Exception as e:
        logger.exception(f"Error procesando mensaje entrante: {str(e)}")

def process_sent_message(session, event_data, channel_layer):
    """
    Procesa un mensaje enviado a través de WhatsApp
    """
    try:
        # Extraer datos del mensaje
        message_id = event_data.get('messageId') or event_data.get('id')
        from_number = event_data.get('to') or event_data.get('from')
        to_number = from_number.split('@')[0]
        message_data = event_data.get('message', {})
        message_content = event_data.get('message', {})

        if session.numero == to_number:
            return

        # Buscar la conversación
        try:
            contacto = Contacto.objects.get(
                sesion=session,
                contacto_numero=to_number
            )
        except Contacto.DoesNotExist:
            # Crear una nueva conversación si no existe
            contacto = Contacto.objects.create(
                sesion=session,
                contacto_numero=to_number,
                from_number=from_number,
                estado='activo',
                fecha_ultimo_mensaje=timezone.now()
            )

        # Determinar el tipo y contenido del mensaje
        message_type = message_data.get('type', 'texto')
        message_text = message_data.get('caption', '') or message_data.get('text', '') or message_data.get('conversation', '')


        # Procesar texto
        if 'conversation' in message_content:
            message_type = 'texto'
            message_text = message_content.get('conversation', '')
        elif 'extendedTextMessage' in message_content:
            message_type = 'texto'
            message_text = message_content.get('extendedTextMessage', {}).get('text', '')

        file_url = None
        # Procesar archivos multimedia
        media_types = {
            'imageMessage': ('imagen', 'fileName', 'mimetype', 'caption'),
            'videoMessage': ('video', 'fileName', 'mimetype', 'caption'),
            'audioMessage': ('audio', 'fileName', 'mimetype', None),
            'documentMessage': ('documento', 'fileName', 'mimetype', 'caption'),
            'stickerMessage': ('sticker', None, 'mimetype', None)
        }

        for media_key, (type_name, filename_key, mimetype_key, caption_key) in media_types.items():
            if media_key in message_content:
                media_msg = message_content.get(media_key, {})
                message_type = type_name

                # Obtener el texto del caption si existe
                if caption_key and caption_key in media_msg:
                    message_text = media_msg.get(caption_key, '') or type_name or ''

                message_text = message_text or type_name

                # Procesar archivo multimedia si hay datos
                if 'mediaData' in event_data:
                    media_data = event_data.get('mediaData')
                    filename = media_msg.get(filename_key, f"{type_name}_{message_id}")

                    if media_key == 'stickerMessage':
                        filename = f'{filename}.png'

                    # Guardar el archivo
                    file_url = save_media_file(media_data, filename, session.id, contacto.id)

        # Actualizar la conversación
        contacto.ultimo_mensaje = message_text[:100] + ('...' if len(message_text) > 100 else '')
        contacto.fecha_ultimo_mensaje = timezone.now()
        contacto.save()

        conversation = ConversacionWhatsApp.objects.sin_expirar.filter(contacto=contacto).first() or \
                       ConversacionWhatsApp.objects.create(contacto=contacto)

        # Crear el mensaje
        message = MensajeWhatsApp.objects.create(
            conversacion=conversation,
            remitente=session.numero,  # El remitente es el número de la sesión
            mensaje=message_text,
            tipo=message_type,
            archivo_url=file_url,  # No tenemos la URL del archivo en este punto
            fecha=timezone.now(),
            mensaje_id_externo=message_id,
            leido=True,  # Marcamos como leído ya que lo enviamos nosotros
            fecha_leido=timezone.now()
        )

        # if not conversation.bienvenida_enviado:
        #     if conversation.sesion.mensaje_bienvenida:
        #         whatsapp_service = WhatsAppService()
        #         whatsapp_service.send_text_message(conversation.sesion.session_id, contacto.from_number, conversation.sesion.mensaje_bienvenida, simularEscritura=True)
        #     conversation.bienvenida_enviado = True
        #     conversation.save()

        # Actualizar estadísticas
        update_conversation_stats(conversation)

        # Notificar a través de WebSockets
        async_to_sync(channel_layer.group_send)(
            f"chat_{conversation.id}",
            {
                'type': 'whatsapp_message',
                'event': 'message_sent',
                'conversation_id': conversation.id,
                'message_id': message.id,
                'message_type': message_type,
                'message_text': message_text,
                'sender': session.numero,
                'timestamp': timezone.now().isoformat()
            }
        )
        async_to_sync(channel_layer.group_send)(
            f"whatsapp_sessionroom_{session.id}",
            {
                'type': 'whatsapp_event',
                'event': 'new_message',
                'conversation_id': conversation.id
            }
        )

        logger.info(f"Mensaje enviado a {to_number} desde la sesión {session.session_id}")

    except Exception as e:
        logger.exception(f"Error procesando mensaje enviado: {str(e)}")

def process_deleted_message(session, event_data, channel_layer):
    """
    Procesa un mensaje eliminado en WhatsApp
    """
    try:
        # Extraer datos del mensaje
        message_id = event_data['message']['protocolMessage']['key']['id']
        chat = event_data['from']

        # Limpiar el número de teléfono
        if '@' in chat:
            chat = chat.split('@')[0]

        # Buscar el mensaje por su ID externo
        try:
            message = MensajeWhatsApp.objects.get(
                mensaje_id_externo=message_id,
                conversacion__sesion=session,
                conversacion__contacto_numero=chat
            )

            # Marcar como eliminado
            message.eliminado = True
            message.fecha_eliminacion = timezone.now()
            message.save()

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"chat_{message.conversacion.id}",
                {
                    'type': 'whatsapp_message',
                    'event': 'message_deleted',
                    'conversation_id': message.conversacion.id,
                    'message_id': message.id,
                    'external_message_id': message_id
                }
            )
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_sessionroom_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'new_message',
                    'conversation_id': message.conversacion.id
                }
            )

            logger.info(f"Mensaje {message_id} marcado como eliminado")

        except MensajeWhatsApp.DoesNotExist:
            logger.warning(f"No se encontró el mensaje {message_id} para marcar como eliminado")

    except Exception as e:
        logger.exception(f"Error procesando mensaje eliminado: {str(e)}")

def process_edited_message(session, event_data, fromchat, channel_layer):
    """
    Procesa un mensaje editado en WhatsApp
    """
    try:
        # Extraer datos del mensaje
        message_id = event_data['key']['id']
        chat = fromchat
        edited_message = event_data['editedMessage']

        # Limpiar el número de teléfono
        if '@' in chat:
            chat = chat.split('@')[0]

        # Buscar el mensaje por su ID externo
        try:
            message = MensajeWhatsApp.objects.get(
                mensaje_id_externo=message_id,
                conversacion__sesion=session,
                conversacion__contacto_numero=chat
            )

            # Guardar el mensaje original
            if not message.mensaje_original:
                message.mensaje_original = message.mensaje

            # Actualizar con el mensaje editado
            new_text = ''
            if 'conversation' in edited_message:
                new_text = edited_message.get('conversation', '')
            elif 'extendedTextMessage' in edited_message:
                new_text = edited_message.get('extendedTextMessage', {}).get('text', '')

            message.mensaje = new_text
            message.editado = True
            message.fecha_edicion = timezone.now()
            message.save()

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"chat_{message.conversacion.id}",
                {
                    'type': 'whatsapp_message',
                    'event': 'message_edited',
                    'conversation_id': message.conversacion.id,
                    'message_id': message.id,
                    'external_message_id': message_id,
                    'new_text': new_text,
                    'original_text': message.mensaje_original
                }
            )
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_sessionroom_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'new_message',
                    'conversation_id': message.conversation.id
                }
            )

            logger.info(f"Mensaje {message_id} editado")

        except MensajeWhatsApp.DoesNotExist:
            logger.warning(f"No se encontró el mensaje {message_id} para editar")

    except Exception as e:
        logger.exception(f"Error procesando mensaje editado: {str(e)}")

def process_contact_update(session, event_data, channel_layer):
    """
    Procesa una actualización de contacto en WhatsApp
    """
    try:
        contact_data = event_data.get('contact', {})
        contact_id = contact_data.get('id', '')

        # Limpiar el ID del contacto
        if '@' in contact_id:
            contact_id = contact_id.split('@')[0]

        # Buscar conversaciones con este contacto
        contactos = Contacto.objects.filter(
            sesion=session,
            contacto_numero=contact_id
        )

        for contacto in contactos:
            # Actualizar nombre si está disponible
            if 'notify' in contact_data:
                contacto.contacto_nombre = contact_data.get('notify')
                contacto.save()

        logger.info(f"Contacto {contact_id} actualizado")

    except Exception as e:
        logger.exception(f"Error procesando actualización de contacto: {str(e)}")

def process_profile_update(session, event_data, channel_layer):
    """
    Procesa una actualización de perfil en WhatsApp
    """
    try:
        presence_data = event_data.get('presence', {})
        user_id = presence_data.get('id', '')

        # Limpiar el ID del usuario
        if '@' in user_id:
            user_id = user_id.split('@')[0]

        # Buscar conversaciones con este usuario
        contactos = Contacto.objects.filter(
            sesion=session,
            contacto_numero=user_id
        )

        logger.info(f"Perfil de {user_id} actualizado")

    except Exception as e:
        logger.exception(f"Error procesando actualización de perfil: {str(e)}")

def save_media_file(media_base64, filename, session_id, conversation_id):
    """
    Guarda un archivo multimedia recibido en base64

    Args:
        media_base64: Datos del archivo en base64
        filename: Nombre del archivo
        session_id: ID de la sesión
        conversation_id: ID de la conversación

    Returns:
        str: URL del archivo guardado
    """
    try:
        # Decodificar el base64
        file_data = base64.b64decode(media_base64)

        # Crear la ruta para guardar el archivo
        file_path = f"whatsapp_media/{session_id}/{conversation_id}/{filename}"

        # Guardar el archivo
        path = default_storage.save(file_path, ContentFile(file_data))

        # Devolver la URL
        return default_storage.url(path)
    except Exception as e:
        logger.exception(f"Error guardando archivo multimedia: {str(e)}")
        return ''

def update_conversation_stats(conversation):
    """
    Actualiza las estadísticas de una conversación

    Args:
        conversation: Objeto ConversacionWhatsApp
    """
    try:
        # Obtener o crear las estadísticas
        stats, created = EstadisticasConversacion.objects.get_or_create(
            conversacion=conversation
        )

        # Contar mensajes
        total_messages = MensajeWhatsApp.objects.filter(conversacion=conversation).count()
        client_messages = MensajeWhatsApp.objects.filter(
            conversacion=conversation,
            remitente=conversation.contacto_numero
        ).count()
        advisor_messages = MensajeWhatsApp.objects.filter(
            conversacion=conversation
        ).exclude(
            remitente=conversation.contacto_numero
        ).exclude(
            es_automatico=True
        ).count()
        auto_messages = MensajeWhatsApp.objects.filter(
            conversacion=conversation,
            es_automatico=True
        ).count()
        ai_messages = MensajeWhatsApp.objects.filter(
            conversacion=conversation,
            ia_generado=True
        ).count()

        # Actualizar estadísticas
        stats.total_mensajes = total_messages
        stats.mensajes_cliente = client_messages
        stats.mensajes_asesor = advisor_messages
        stats.mensajes_automaticos = auto_messages
        stats.mensajes_ia = ai_messages

        # Calcular tiempo de primera respuesta
        if client_messages > 0 and advisor_messages > 0:
            first_client_msg = MensajeWhatsApp.objects.filter(
                conversacion=conversation,
                remitente=conversation.contacto_numero
            ).order_by('fecha').first()

            if first_client_msg:
                first_response = MensajeWhatsApp.objects.filter(
                    conversacion=conversation,
                    fecha__gt=first_client_msg.fecha
                ).exclude(
                    remitente=conversation.contacto_numero
                ).order_by('fecha').first()

                if first_response:
                    stats.tiempo_primera_respuesta = first_response.fecha - first_client_msg.fecha

        stats.save()

    except Exception as e:
        logger.exception(f"Error actualizando estadísticas de conversación: {str(e)}")