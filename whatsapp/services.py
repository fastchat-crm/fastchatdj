# whatsapp/services.py
import requests
import json
import base64
import os

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from whatsapp.transcribe_whatsapp_audio import convert_audio, transcribe_audio, extract_voiced_audio
from django.conf import settings

from core.decoradores import sync_to_async_function
from core.funciones_adicionales import get_image_as_base64
from .models import SesionWhatsApp, WhatsAppWebhook, Contacto, MensajeWhatsApp


class WhatsAppService:
    def __init__(self):
        self.base_url = settings.WHATSAPP_API_URL
        self.headers = {
            'Content-Type': 'application/json',
            'X-API-Key': settings.NODE_SECRET_KEY
        }

    def create_session(self, session, webhook_url):
        """
        Crea una nueva sesión de WhatsApp en el servidor Node.js

        Args:
            session: Objeto SesionWhatsApp

        Returns:
            dict: Respuesta del servidor
        """

        # Crear los webhooks para todos los tipos de eventos
        webhooks = [
            {'url': webhook_url, 'type': 'qr_code'},
            {'url': webhook_url, 'type': 'ready'},
            {'url': webhook_url, 'type': 'authenticated'},
            {'url': webhook_url, 'type': 'auth_failure'},
            {'url': webhook_url, 'type': 'disconnected'},
            {'url': webhook_url, 'type': 'message'},
            {'url': webhook_url, 'type': 'message_sent'},
            {'url': webhook_url, 'type': 'profile_update'},
            {'url': webhook_url, 'type': 'contact_update'},
            {'url': webhook_url, 'type': 'message_deleted'},
            {'url': webhook_url, 'type': 'message_edited'},
            {'url': webhook_url, 'type': 'contacts_list'}
        ]

        # Datos para la solicitud
        data = {
            'sessionId': session.session_id,
            'webhooks': webhooks
        }

        try:
            response = requests.post(
                f"{self.base_url}/session",
                headers=self.headers,
                json=data
            )

            if response.status_code == 201:
                result = response.json()

                # Actualizar la sesión con el código QR si está disponible
                if 'qrCode' in result:
                    from .models import ConfigBaileys
                    cb, _ = ConfigBaileys.objects.get_or_create(sesion=session)
                    cb.qr_code = result['qrCode']
                    cb.save(update_fields=['qr_code'])

                # Guardar los webhooks en la base de datos
                for webhook_data in webhooks:
                    WhatsAppWebhook.objects.get_or_create(
                        session=session,
                        url=webhook_data['url'],
                        type=webhook_data['type']
                    )

                return {
                    'success': True,
                    'qr_code': result.get('qrCode')
                }
            else:
                error_msg = f"Error al crear sesión: {response.status_code} - {response.text}"
                return {
                    'success': False,
                    'error': error_msg
                }
        except Exception as e:
            error_msg = f"Error de conexión: {str(e)}"
            return {
                'success': False,
                'error': error_msg
            }

    def get_user_image(self, session_id, to):
        data = {
            'sessionId': session_id,
            'to': to
        }

        try:
            response = requests.get(
                f"{self.base_url}/getUserImage",
                headers=self.headers,
                json=data
            )

            if response.status_code == 200:
                return response.json().get('userImage') or ''
            else:
                return ''
        except Exception as e:
            return ''

    @sync_to_async_function
    def sync_contacts(self, session):
        from django.db import connection
        try:
            cb = getattr(session, 'config_baileys', None)
            contacts_list = json.loads((cb.contacts_list if cb else '[]') or '[]')
            for c in contacts_list:
                print(c)
                from_number = c.get('id') or ''
                if not from_number:
                    continue
                contacto_numero = "".join([x for x in from_number if x.isdigit()])
                photo = self.get_user_image(session.session_id, from_number)
                contacto = Contacto.objects.filter(
                    sesion=session, from_number=from_number,
                ).first() or Contacto(sesion=session, from_number=from_number)
                contacto.contacto_numero = contacto_numero
                contacto.contacto_nombre = c.get('name') or c.get('notify') or ''
                if photo:
                    contacto.contacto_foto = f'data:image/jpg;base64,{get_image_as_base64(photo)}'
                contacto.save()
        except Exception as ex:
            print(ex)
        finally:
            connection.close()

    @sync_to_async_function
    def transcribe_audio(self, message: MensajeWhatsApp, model_size="base" , lang='es'):
        from django.db import connection
        text = ''
        wav_file = ''
        voiced_wav = ''
        try:
            if not message.tipo == 'audio':
                return
            wav_file = convert_audio(message.get_archivo_path, f'{message.get_archivo_path}.wav')
            voiced_wav = extract_voiced_audio(wav_file, f"{wav_file}_voiced.wav")
            text = transcribe_audio(voiced_wav, model_size, lang)
            message.mensaje = text
            message.save()
        except Exception as ex:
            print(ex)
        finally:
            voiced_wav and os.path.exists(voiced_wav) and os.remove(voiced_wav)
            wav_file and os.path.exists(wav_file) and os.remove(wav_file)
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"chat_{message.conversacion.id}",
                {
                    'type': 'whatsapp_message',
                    'event': 'message_edited',
                    'conversation_id': message.conversacion.id,
                    'message_id': message.id,
                    'new_text': text,
                    'original_text': message.mensaje_original
                }
            )
            connection.close()

    def sync_transcribe_audio(self, message: MensajeWhatsApp, model_size="base", lang='es'):
        text = ''
        wav_file = ''
        voiced_wav = ''
        try:
            if not message.tipo == 'audio':
                return
            wav_file = convert_audio(message.get_archivo_path, f'{message.get_archivo_path}.wav')
            voiced_wav = extract_voiced_audio(wav_file, f"{wav_file}_voiced.wav")
            text = transcribe_audio(voiced_wav, model_size, lang)
            message.mensaje = text
            message.save()
        except Exception as ex:
            print(ex)
        finally:
            voiced_wav and os.path.exists(voiced_wav) and os.remove(voiced_wav)
            wav_file and os.path.exists(wav_file) and os.remove(wav_file)
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"chat_{message.conversacion.id}",
                {
                    'type': 'whatsapp_message',
                    'event': 'message_edited',
                    'conversation_id': message.conversacion.id,
                    'message_id': message.id,
                    'new_text': text,
                    'original_text': message.mensaje_original
                }
            )
        return text

    def send_text_message(self, session_id, to, text, conversacion_id=None, simularEscritura=False):
        """
        Envía un mensaje de texto a través de WhatsApp

        Args:
            session_id: ID de la sesión
            to: Número de teléfono del destinatario (con formato: 123456789@s.whatsapp.net)
            text: Texto del mensaje

        Returns:
            dict: Respuesta del servidor
        """
        data = {
            'sessionId': session_id, "conversacion_id": conversacion_id,
            'to': to,
            'text': text, 'simularEscritura': simularEscritura
        }

        try:
            response = requests.post(
                f"{self.base_url}/message/text",
                headers=self.headers,
                json=data
            )

            if response.status_code == 200:
                return {
                    'success': True,
                    'message_id': response.json().get('messageId')
                }
            else:
                return {
                    'success': False,
                    'error': f"Error al enviar mensaje: {response.status_code} - {response.text}"
                }
        except Exception as e:
            return {
                'success': False,
                'error': f"Error de conexión: {str(e)}"
            }

    def send_presence_update(self, session_id, to):
        """
        Envía un mensaje de texto a través de WhatsApp

        Args:
            session_id: ID de la sesión
            to: Número de teléfono del destinatario (con formato: 123456789@s.whatsapp.net)
            text: Texto del mensaje

        Returns:
            dict: Respuesta del servidor
        """
        data = {
            'sessionId': session_id,
            'to': to
        }

        try:
            response = requests.post(
                f"{self.base_url}/message/sendPresenceUpdate",
                headers=self.headers,
                json=data
            )

            if response.status_code == 200:
                return {
                    'success': True
                }
            else:
                return {
                    'success': False,
                    'error': f"Error al enviar mensaje: {response.status_code} - {response.text}"
                }
        except Exception as e:
            return {
                'success': False,
                'error': f"Error de conexión: {str(e)}"
            }

    def quit_presence_update(self, session_id, to):
        """
        Envía un mensaje de texto a través de WhatsApp

        Args:
            session_id: ID de la sesión
            to: Número de teléfono del destinatario (con formato: 123456789@s.whatsapp.net)
            text: Texto del mensaje

        Returns:
            dict: Respuesta del servidor
        """
        data = {
            'sessionId': session_id,
            'to': to
        }

        try:
            response = requests.post(
                f"{self.base_url}/message/quitPresenceUpdate",
                headers=self.headers,
                json=data
            )

            if response.status_code == 200:
                return {
                    'success': True
                }
            else:
                return {
                    'success': False,
                    'error': f"Error al enviar mensaje: {response.status_code} - {response.text}"
                }
        except Exception as e:
            return {
                'success': False,
                'error': f"Error de conexión: {str(e)}"
            }

    def send_media_message(self, session_id, to, file_path=None, file_content=None, caption=None, filename=None,
                           media_type=None, conversacion_id=None):
        """
        Envía un mensaje con archivo multimedia a través de WhatsApp, detectando automáticamente el tipo de medio

        Args:
            session_id: ID de la sesión
            to: Número de teléfono del destinatario (con formato: 123456789@s.whatsapp.net)
            file_path: Ruta al archivo (opcional)
            file_content: Contenido del archivo en bytes (opcional)
            caption: Texto que acompaña al archivo (opcional)
            filename: Nombre del archivo (opcional)
            media_type: Tipo de archivo ('image', 'video', 'audio', 'document') (opcional, se detecta automáticamente si no se proporciona)

        Returns:
            dict: Respuesta del servidor
        """
        # Mapeo de extensiones a tipos de medio
        extension_to_media_type = {
            # Imágenes
            'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'gif': 'image', 'webp': 'image', 'bmp': 'image',
            # Videos
            'mp4': 'video', 'mov': 'video', 'avi': 'video', 'mkv': 'video', 'webm': 'video', '3gp': 'video',
            # Audio
            'mp3': 'audio', 'ogg': 'audio', 'wav': 'audio', 'm4a': 'audio', 'aac': 'audio', 'flac': 'audio',
            # Documentos
            'pdf': 'document', 'doc': 'document', 'docx': 'document', 'xls': 'document', 'xlsx': 'document',
            'ppt': 'document', 'pptx': 'document', 'txt': 'document', 'csv': 'document', 'rtf': 'document',
            'zip': 'document', 'rar': 'document', '7z': 'document'
        }

        # Mapeo de tipos MIME a tipos de medio
        mime_to_media_type = {
            'image/': 'image',
            'video/': 'video',
            'audio/': 'audio',
            'application/pdf': 'document',
            'application/msword': 'document',
            'application/vnd.openxmlformats-officedocument': 'document',
            'application/vnd.ms-': 'document',
            'text/': 'document',
            'application/zip': 'document',
            'application/x-rar': 'document',
            'application/x-7z-compressed': 'document'
        }

        # Determinar el tipo MIME según la extensión
        mime_types = {
            'image': {
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'gif': 'image/gif',
                'webp': 'image/webp',
                'bmp': 'image/bmp'
            },
            'video': {
                'mp4': 'video/mp4',
                'mov': 'video/quicktime',
                'avi': 'video/x-msvideo',
                'mkv': 'video/x-matroska',
                'webm': 'video/webm',
                '3gp': 'video/3gpp'
            },
            'audio': {
                'mp3': 'audio/mpeg',
                'ogg': 'audio/ogg',
                'wav': 'audio/wav',
                'm4a': 'audio/mp4',
                'aac': 'audio/aac',
                'flac': 'audio/flac'
            },
            'document': {
                'pdf': 'application/pdf',
                'doc': 'application/msword',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'xls': 'application/vnd.ms-excel',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'ppt': 'application/vnd.ms-powerpoint',
                'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                'txt': 'text/plain',
                'csv': 'text/csv',
                'rtf': 'application/rtf',
                'zip': 'application/zip',
                'rar': 'application/x-rar-compressed',
                '7z': 'application/x-7z-compressed'
            }
        }

        # Obtener el contenido del archivo
        if file_path and not file_content:
            with open(file_path, 'rb') as f:
                file_content = f.read()
                if not filename:
                    filename = os.path.basename(file_path)

        if not file_content:
            return {
                'success': False,
                'error': 'No se proporcionó contenido de archivo'
            }

        # Determinar el tipo de medio automáticamente si no se proporciona
        if not media_type:
            # Primero intentar por el nombre del archivo
            if filename:
                ext = filename.split('.')[-1].lower()
                if ext in extension_to_media_type:
                    media_type = extension_to_media_type[ext]

            # Si aún no se ha determinado, intentar con python-magic
            if not media_type:
                try:
                    import magic
                    mime = magic.Magic(mime=True)
                    detected_mime = mime.from_buffer(file_content)

                    # Buscar coincidencia en el mapeo de MIME a tipo de medio
                    for mime_prefix, media in mime_to_media_type.items():
                        if detected_mime.startswith(mime_prefix):
                            media_type = media
                            break
                except ImportError:
                    # Si python-magic no está disponible, usar un enfoque básico
                    # Verificar los primeros bytes para detectar tipos comunes
                    if file_content.startswith(b'\xff\xd8\xff'):  # JPEG
                        media_type = 'image'
                    elif file_content.startswith(b'\x89PNG\r\n\x1a\n'):  # PNG
                        media_type = 'image'
                    elif file_content.startswith(b'GIF87a') or file_content.startswith(b'GIF89a'):  # GIF
                        media_type = 'image'
                    elif file_content.startswith(b'%PDF'):  # PDF
                        media_type = 'document'
                    elif file_content.startswith(b'PK\x03\x04'):  # ZIP, DOCX, XLSX, etc.
                        media_type = 'document'
                    else:
                        # Si no se puede determinar, usar documento como predeterminado
                        media_type = 'document'

        # Si aún no se ha determinado, usar documento como predeterminado
        if not media_type:
            media_type = 'document'

        # Convertir a base64
        media_base64 = base64.b64encode(file_content).decode('utf-8')

        # Determinar el tipo MIME
        mimetype = None
        if filename:
            ext = filename.split('.')[-1].lower()
            if media_type in mime_types and ext in mime_types[media_type]:
                mimetype = mime_types[media_type][ext]

        # Si no se pudo determinar el MIME por extensión, usar un valor predeterminado según el tipo de medio
        if not mimetype:
            default_mimes = {
                'image': 'image/jpeg',
                'video': 'video/mp4',
                'audio': 'audio/mpeg',
                'document': 'application/octet-stream'
            }
            mimetype = default_mimes.get(media_type, 'application/octet-stream')

        # Datos para la solicitud
        data = {
            'sessionId': session_id,
            'to': to,
            'caption': caption or '',
            'media': media_base64,
            'type': media_type,
            'filename': filename,
            'mimetype': mimetype, "conversacion_id": conversacion_id
        }

        try:
            response = requests.post(
                f"{self.base_url}/message/media",
                headers=self.headers,
                json=data
            )

            if response.status_code == 200:
                return {
                    'success': True,
                    'message_id': response.json().get('messageId')
                }
            else:
                return {
                    'success': False,
                    'error': f"Error al enviar archivo: {response.status_code} - {response.text}"
                }
        except Exception as e:
            return {
                'success': False,
                'error': f"Error de conexión: {str(e)}"
            }

    def check_session_status(self, session_id):
        """
        Consulta al servidor Node el estado real de la sesión.
        `connected` refleja el estado del socket en memoria (conexión viva con WhatsApp),
        `isActive` es la bandera persistida en BD del lado Node.
        """
        try:
            response = requests.get(
                f"{self.base_url}/session/{session_id}",
                headers=self.headers,
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'is_active': bool(data.get('isActive')),
                    'connected': bool(data.get('connected')),
                    'last_activity': data.get('lastActivity'),
                    'qr_code': data.get('qrCode'),
                }
            if response.status_code == 404:
                return {'success': False, 'not_found': True, 'error': 'Sesión no encontrada en el servidor de WhatsApp'}
            return {'success': False, 'error': f"Error {response.status_code}: {response.text}"}
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Timeout al consultar el servidor de WhatsApp'}
        except Exception as e:
            return {'success': False, 'error': f"Error de conexión: {str(e)}"}

    def close_session(self, session_id):
        """
        Cierra una sesión de WhatsApp

        Args:
            session_id: ID de la sesión

        Returns:
            dict: Respuesta del servidor
        """
        try:
            response = requests.delete(
                f"{self.base_url}/session/{session_id}",
                headers=self.headers
            )

            if response.status_code == 200:
                return {
                    'success': True
                }
            else:
                return {
                    'success': False,
                    'error': f"Error al cerrar sesión: {response.status_code} - {response.text}"
                }
        except Exception as e:
            return {
                'success': False,
                'error': f"Error de conexión: {str(e)}"
            }

    def format_phone_number(self, phone):
        """
        Formatea un número de teléfono para WhatsApp

        Args:
            phone: Número de teléfono (puede tener o no el prefijo '+')

        Returns:
            str: Número formateado para WhatsApp
        """
        # Eliminar caracteres no numéricos
        clean_number = ''.join(filter(str.isdigit, phone))

        # Asegurarse de que tenga el formato correcto para WhatsApp
        return f"{clean_number}@s.whatsapp.net"


def get_whatsapp_service(sesion=None, proveedor: str | None = None):
    """Dispatcher agnostico al transporte.

    Devuelve el servicio correspondiente segun `sesion.proveedor` o el argumento
    `proveedor` explicito. Asi el resto del codigo escribe:

        service = get_whatsapp_service(sesion)
        service.send_text_message(sesion.session_id, to, text)

    ...y no se entera si por debajo habla con Node/Baileys o con Meta Graph API.
    """
    prov = proveedor
    if prov is None and sesion is not None:
        prov = getattr(sesion, 'proveedor', 'baileys')
    prov = (prov or 'baileys').lower()

    if prov == 'meta':
        from .services_meta import MetaWhatsAppService
        return MetaWhatsAppService()
    if prov == 'instagram':
        from .services_instagram import InstagramService
        return InstagramService()
    if prov == 'messenger':
        from .services_instagram import MessengerService
        return MessengerService()
    return WhatsAppService()
