# whatsapp/webhook_baileys_view.py — receptor de eventos Baileys (Node.js).
#
# Este endpoint recibe SOLO eventos del servicio Node.js que corre Baileys.
# Los eventos Meta llegan a /whatsapp/meta_webhook/ (meta_webhook_view.py).
# La lógica común de procesamiento de mensajes (IA, motor tradicional,
# horarios, rate-limit, helpers) vive en `procesar_mensaje.py` y la usan
# ambos transports.
import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.funciones import save_log_entry, encrypt_sesion_id
from core.funciones_adicionales import get_image_as_base64

from .models import (
    SesionWhatsApp,
    ConversacionWhatsApp, Contacto,
    MensajeWhatsApp,
)
from .services import WhatsAppService
from .trazas import registrar as _traza, notificar_superusers_error
from .procesar_mensaje import (
    process_incoming_message,
    save_media_file,
    update_conversation_stats,
)

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def webhook_handler(request):
    """
    Manejador de webhooks para eventos de WhatsApp
    """
    logger.info("WEBHOOK_RECV ip=%s len=%d", request.META.get('REMOTE_ADDR', '?'), len(request.body))
    # Verificar la clave API
    # Este endpoint recibe SOLO eventos Baileys desde Node.js. Los eventos Meta
    # llegan a /whatsapp/meta_webhook/ (meta_webhook_view.py). Por eso aqui se
    # instancia WhatsAppService directamente para los handlers de QR/ready/auth/
    # close. Para el handler de 'message' delegamos a process_incoming_message
    # (procesar_mensaje.py) que internamente usa get_whatsapp_service por si la
    # sesion termina ruteando a Meta.
    whatsapp_service = WhatsAppService()
    try:
        # Parsear los datos recibidos

        data = json.loads(request.body)
        event_type = data.get('type')
        event_data = data.get('data', {})
        session_id = event_data.get('sessionId')
        logger.info("WEBHOOK_EVENT type=%s session=%s", event_type, session_id)
        conversacion_id = event_data.get('conversacion_id')
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

        # ConfigBaileys vive los campos Baileys-specific. Se crea lazy para
        # que el webhook siga funcionando aun si una sesion vieja no tiene fila.
        from .models import ConfigBaileys
        def _cb():
            cb, _ = ConfigBaileys.objects.get_or_create(sesion=session)
            return cb

        # Procesar el evento según su tipo
        if event_type == 'qr_code':
            cb = _cb()
            cb.qr_code = event_data.get('qrCode')
            cb.save(update_fields=['qr_code'])
            session.estado = 'pendiente'
            session.save(update_fields=['estado'])

            save_log_entry(f'HS: SESION {session_id} QR CODE GENERADO', request, event_type, obj=session)

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'qr_code',
                    'session_id': session.id,
                    'qr_code': cb.qr_code
                }
            )

            logger.info(f"Código QR actualizado para la sesión {session_id}")

        elif event_type == 'ready':
            guardar = True
            cb = _cb()
            # Guardar información del usuario si está disponible
            if 'user' in event_data:
                user_info = event_data.get('user', {})
                if 'userImage' in event_data and event_data.get('userImage'):
                    cb.foto = f'data:image/jpg;base64,{get_image_as_base64(event_data.get("userImage"))}'
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
                        cb.whatsapp_id = whatsapp_id
                        if not session.nombre:
                            session.nombre = user_info.get('pushName') or user_info.get('verifiedBizName') or user_info.get('name') or user_info.get('notify') or user_info.get('verifiedName') or ''

            if guardar:
                session.estado = 'conectado'
                session.ultima_conexion = timezone.now()
                session.save()
                cb.error_mensaje = None
                cb.save()

                save_log_entry(f'HS: SESION {session_id} READY', request, event_type, obj=session)

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
            session.save()
            cb = _cb()
            cb.error_mensaje = None
            cb.save(update_fields=['error_mensaje'])

            save_log_entry(f'HS: SESION {session_id} authenticated'.upper(), request, event_type, obj=session)

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
            cb = _cb()
            contacts_list = json.loads(cb.contacts_list or '[]')
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
            cb.contacts_list = json.dumps(new_contacts_list)
            cb.contacts_length = len(new_contacts_list)
            cb.save(update_fields=['contacts_list', 'contacts_length'])

        elif event_type == 'auth_failure':
            detalle_auth = (
                event_data.get('error')
                or event_data.get('message')
                or event_data.get('reason')
                or ''
            )
            session.estado = 'error'
            session.save()
            cb = _cb()
            cb.error_mensaje = f"Error de autenticación: {detalle_auth}" if detalle_auth else "Error de autenticación"
            cb.save(update_fields=['error_mensaje'])
            msgerror = cb.error_mensaje

            save_log_entry(f'HS: SESION {session_id} auth_failure {detalle_auth}'.upper(), request, event_type, obj=session)
            logger.error("AUTH_FAILURE session=%s payload=%s", session_id, event_data)

            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'auth_failure',
                    'session_id': session.id,
                    'error': cb.error_mensaje,
                    'msgerror': msgerror,
                    'payload': event_data,
                }
            )

        elif event_type == 'disconnected':
            reason = event_data.get('reason', 'unknown')
            detalle_disc = event_data.get('error') or event_data.get('message') or ''
            session.estado = 'desconectado'
            session.save()
            cb = _cb()
            cb.desconectado_manualmente = False  # desconexión inesperada → reconectable
            cb.error_mensaje = f"Desconectado ({reason}){f': {detalle_disc}' if detalle_disc else ''}"
            cb.save(update_fields=['desconectado_manualmente', 'error_mensaje'])
            msgerror = cb.error_mensaje

            save_log_entry(f'HS: SESION {session_id} disconnected reason={reason} {detalle_disc}'.upper(), request, event_type, obj=session)
            logger.warning("DISCONNECTED session=%s reason=%s payload=%s", session_id, reason, event_data)

            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'disconnected',
                    'session_id': session.id,
                    'reason': reason,
                    'msgerror': msgerror,
                    'payload': event_data,
                }
            )

        elif event_type == 'rate_limited':
            try:
                retry_after_ms = int(event_data.get('retryAfterMs') or 60000)
            except (TypeError, ValueError):
                retry_after_ms = 60000
            retry_after_s = max(5, min(int(retry_after_ms / 1000), 600))

            cache.set(
                f'wa_rate_limited_{session.id}',
                {
                    'retry_after_s': retry_after_s,
                    'count': event_data.get('count'),
                    'max': event_data.get('max'),
                    'window_ms': event_data.get('windowMs'),
                    'window_start': event_data.get('windowStart'),
                },
                timeout=retry_after_s,
            )

            _traza(
                etapa='node_rate_limited', sesion=session, nivel='warning',
                detalle={
                    'count': event_data.get('count'),
                    'max': event_data.get('max'),
                    'window_ms': event_data.get('windowMs'),
                    'retry_after_ms': retry_after_ms,
                    'window_start': event_data.get('windowStart'),
                },
            )

            notificar_superusers_error(
                titulo=f'WhatsApp rate-limit alcanzado — sesión "{session.nombre or session.session_id}"',
                cuerpo=(
                    f'La sesión <strong>{session.nombre or session.session_id}</strong> alcanzó el límite '
                    f'de {event_data.get("max", "?")} envíos por ventana '
                    f'({int((event_data.get("windowMs") or 60000) / 1000)}s). '
                    f'La IA pausará envíos durante {retry_after_s}s para no saturar más.'
                ),
                url=f'/whatsapp/trazas/?sesion={encrypt_sesion_id(session.id)}',
                cache_key=f'notif_rate_limited_{session.id}',
                cooldown_segundos=600,
            )

            save_log_entry(f'HS: SESION {session_id} RATE_LIMITED', request, event_type, obj=session)
            logger.warning(
                "Sesión %s rate-limited: count=%s/%s, retry en %ss",
                session_id, event_data.get('count'), event_data.get('max'), retry_after_s,
            )

        elif event_type == 'message':
            if session.estado != 'conectado':
                session.estado = 'pendiente'
                session.save()
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
            if session.estado != 'conectado':
                session.estado = 'pendiente'
                session.save()
            # Procesar mensaje enviado
            process_sent_message(session, event_data, channel_layer)

        elif event_type == 'message_deleted':
            if session.estado != 'conectado':
                session.estado = 'pendiente'
                session.save()
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
        try:
            _traza(
                etapa='error_general',
                sesion=locals().get('session'),
                numero=locals().get('from_number'),
                nivel='error',
                detalle=f'webhook_handler: {type(e).__name__}: {str(e)[:1500]}',
            )
        except Exception:
            pass
        return JsonResponse({'message': f'Error: {str(e)}'}, status=500)


def process_sent_message(session, event_data, channel_layer):
    """
    Procesa un mensaje enviado a través de WhatsApp
    """
    try:
        print('process_sent_message', event_data)
        # Extraer datos del mensaje
        message_id = event_data.get('messageId') or event_data.get('id')
        from_number = event_data.get('to') or event_data.get('from')
        to_number = from_number.split('@')[0]
        message_data = event_data.get('message', {})
        message_content = event_data.get('message', {})
        conversacion_id = event_data.get('conversacion_id') or 0

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
        # Procesar archivos multimedia — soporta formato nuevo (flat) y antiguo (nested)
        TIPO_MAP = {
            'imageMessage': 'imagen',
            'videoMessage': 'video',
            'audioMessage': 'audio',
            'documentMessage': 'documento',
            'stickerMessage': 'sticker',
        }
        detected_media_key = event_data.get('mediaType')
        if not detected_media_key:
            for k in TIPO_MAP:
                if k in message_content:
                    detected_media_key = k
                    break

        if detected_media_key and detected_media_key in TIPO_MAP:
            type_name = TIPO_MAP[detected_media_key]
            message_type = type_name
            media_msg = message_content.get(detected_media_key, {}) if isinstance(message_content, dict) else {}

            caption = event_data.get('caption') or media_msg.get('caption', '')
            if caption:
                message_text = caption
            message_text = message_text or type_name

            if event_data.get('mediaData'):
                media_data = event_data['mediaData']
                filename = (
                    event_data.get('fileName')
                    or media_msg.get('fileName')
                    or f"{type_name}_{message_id}"
                )
                if detected_media_key == 'stickerMessage' and not filename.lower().endswith('.png'):
                    filename = f'{filename}.png'
                file_url = save_media_file(media_data, filename)

        # Actualizar la conversación
        contacto.ultimo_mensaje = message_text[:100] + ('...' if len(message_text) > 100 else '')
        contacto.fecha_ultimo_mensaje = timezone.now()
        contacto.save()

        # Guard de idempotencia: si ya procesamos este mensaje_id, no duplicar
        if message_id and MensajeWhatsApp.objects.filter(
            mensaje_id_externo=message_id, conversacion__contacto__sesion=session
        ).exists():
            logger.warning(f"Mensaje enviado duplicado ignorado: {message_id}")
            return

        conversation = ConversacionWhatsApp.objects.filter(id=conversacion_id).first() or\
                       ConversacionWhatsApp.objects.sin_expirar.filter(contacto=contacto).order_by('-id').first() or \
                       ConversacionWhatsApp.objects.create(
                           contacto=contacto, fromMe=True,
                           proveedor_atencion=getattr(session, 'proveedor', '') or '',
                       )

        # Crear el mensaje
        message = MensajeWhatsApp.objects.create(
            conversacion=conversation,
            remitente=session.numero,  # El remitente es el número de la sesión
            mensaje=message_text,
            tipo=message_type,
            archivo=file_url,  # No tenemos la URL del archivo en este punto
            fecha=timezone.now(),
            mensaje_id_externo=message_id,
            leido=True,  # Marcamos como leído ya que lo enviamos nosotros
            fecha_leido=timezone.now()
        )

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
                'conversation_id': conversation.id,
                'from_me': True,
            }
        )

        logger.info(f"Mensaje enviado a {to_number} desde la sesión {session.session_id}")

    except Exception as e:
        logger.exception(f"Error procesando mensaje enviado: {str(e)}")
        try:
            _traza(
                etapa='error_general', sesion=session,
                numero=locals().get('to_number'),
                nivel='error',
                detalle=f'process_sent_message: {type(e).__name__}: {str(e)[:1500]}',
            )
        except Exception:
            pass


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
        try:
            _traza(
                etapa='error_general', sesion=session, nivel='error',
                detalle=f'process_deleted_message: {type(e).__name__}: {str(e)[:1500]}',
            )
        except Exception:
            pass


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
                    'conversation_id': message.conversacion.id
                }
            )

            logger.info(f"Mensaje {message_id} editado")

        except MensajeWhatsApp.DoesNotExist:
            logger.warning(f"No se encontró el mensaje {message_id} para editar")

    except Exception as e:
        logger.exception(f"Error procesando mensaje editado: {str(e)}")
        try:
            _traza(
                etapa='error_general', sesion=session, nivel='error',
                detalle=f'process_edited_message: {type(e).__name__}: {str(e)[:1500]}',
            )
        except Exception:
            pass


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
        try:
            _traza(
                etapa='error_general', sesion=session, nivel='error',
                detalle=f'process_contact_update: {type(e).__name__}: {str(e)[:1500]}',
            )
        except Exception:
            pass


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
        try:
            _traza(
                etapa='error_general', sesion=session, nivel='error',
                detalle=f'process_profile_update: {type(e).__name__}: {str(e)[:1500]}',
            )
        except Exception:
            pass
