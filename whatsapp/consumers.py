import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.template.loader import render_to_string
from .models import ConversacionWhatsApp, MensajeWhatsApp
from .services import WhatsAppService, get_whatsapp_service


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversacion_id = self.scope['url_route']['kwargs']['conversacion_id']
        self.user = self.scope.get('user')
        self.room_group_name = f'chat_{self.conversacion_id}'

        # Unirse al grupo de la conversación
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        # Abandonar el grupo de la conversación
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # Recibir mensaje del grupo de la conversación
    async def whatsapp_message(self, event):
        html = await self.get_messages_html(self.conversacion_id)

        # Enviar mensajes al WebSocket
        await self.send(text_data=json.dumps({
            'type': 'messages_update',
            'html': html
        }))

    async def receive(self, text_data=None, bytes_data=None):
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('event')
        if message_type == 'sendPresenceUpdate':
            await self.send_presence_update(self.conversacion_id)
        elif message_type == 'quitPresenceUpdate':
            await self.quit_presence_update(self.conversacion_id)


    @database_sync_to_async
    def send_presence_update(self, conversacion_id):
        conversacion = ConversacionWhatsApp.objects.filter(
            contacto__sesion__usuario__id=self.user.id, id=conversacion_id
        ).first()
        if not conversacion:
            return
        whatsapp_service = get_whatsapp_service(conversacion.sesion)
        whatsapp_service.send_presence_update(conversacion.sesion.session_id, conversacion.from_number)

    @database_sync_to_async
    def quit_presence_update(self, conversacion_id):
        conversacion = ConversacionWhatsApp.objects.filter(
            contacto__sesion__usuario__id=self.user.id, id=conversacion_id
        ).first()
        if not conversacion:
            return
        whatsapp_service = get_whatsapp_service(conversacion.sesion)
        whatsapp_service.quit_presence_update(conversacion.sesion.session_id, conversacion.from_number)

    @database_sync_to_async
    def get_messages_html(self, conversacion_id):
        try:
            conversacion = ConversacionWhatsApp.objects.filter(contacto__sesion__usuario__id=self.user.id, id=conversacion_id).first()
            mensajes = MensajeWhatsApp.objects.filter(
                conversacion=conversacion
            ).order_by('fecha')

            # Renderizar la plantilla de mensajes
            html = render_to_string('whatsapp/conversaciones/mensajes_partial.html', {
                'mensajes': mensajes,
                'conversacion': conversacion
            })

            return html
        except ConversacionWhatsApp.DoesNotExist:
            return ""


class SessionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.room_group_name = f'whatsapp_session_{self.session_id}'
        self.user = self.scope.get('user')

        # Unirse al grupo de la conversación
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data=None, bytes_data=None):
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('event')

        if message_type == 'update_session':
            await self.send(text_data=json.dumps({}))
        elif message_type == 'qr_code':
            await self.send(text_data=json.dumps({
                'type': 'qr_code', "qr_code": text_data_json["qr_code"]
            }))
        elif message_type == 'error':
            await self.send(text_data=json.dumps({
                'type': 'error', "msgerror": text_data_json["msgerror"]
            }))

    async def whatsapp_event(self, event):
        message = event

        # Enviar mensaje al WebSocket
        await self.send(text_data=json.dumps(message))


class SessionRoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.room_group_name = f'whatsapp_sessionroom_{self.session_id}'
        self.user = self.scope.get('user')

        # Unirse al grupo de la conversación
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    @database_sync_to_async
    def get_conversacion_data(self, conversacion_id):
        try:
            conversacion = ConversacionWhatsApp.objects.filter(
                contacto__sesion__usuario__id=self.user.id, id=conversacion_id
            ).select_related('contacto').first()
            if not conversacion:
                return {'html': '', 'nombre': ''}
            html = render_to_string('whatsapp/conversaciones/conversacion_item.html', {
                'conversacion': conversacion
            })
            nombre = (
                conversacion.contacto.contacto_nombre
                or conversacion.contacto.from_number
                or 'Contacto'
            )
            return {'html': html, 'nombre': nombre}
        except Exception:
            return {'html': '', 'nombre': ''}

    async def whatsapp_event(self, event):
        conversacion_id = event['conversation_id']
        from_me = event.get('from_me', False)

        data = await self.get_conversacion_data(conversacion_id)

        await self.send(text_data=json.dumps({
            'type': 'messages_update',
            'html': data['html'],
            'conversacion_id': conversacion_id,
            'from_me': from_me,
            'contacto_nombre': data['nombre'],
        }))