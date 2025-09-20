import os, sys
from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from whatsapp.models import ConversacionWhatsApp
from whatsapp.services import WhatsAppService


conversaciones = ConversacionWhatsApp.objects.expirado.filter(
    despedida_enviado=False, conversacion_finalizada=False, fromMe=False
).select_related('contacto', 'contacto__sesion')
whatsapp_service = WhatsAppService()

try:
    for conversacion in conversaciones:
        mensaje_despedida = conversacion.contacto.sesion.mensaje_despedida
        from_number = conversacion.contacto.from_number
        session_id = conversacion.contacto.sesion.session_id
        if mensaje_despedida:
            whatsapp_service.send_text_message(session_id, from_number, mensaje_despedida, conversacion_id=conversacion.id, simularEscritura=True)
        conversacion.resumir_conversacion()
        conversacion.despedida_enviado = True
        conversacion.conversacion_finalizada = True
        conversacion.save()
except Exception as e:
    print(f"Error al enviar mensajes de despedida: {e}")