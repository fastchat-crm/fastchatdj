import os, sys

from django.core.wsgi import get_wsgi_application

from agents_ai.agente_consultor import AgenteConsultor
from agents_ai.agente_resumidor import AgenteResumidor

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
            whatsapp_service.send_text_message(session_id, from_number, mensaje_despedida, simularEscritura=True)
        session = conversacion.contacto.sesion
        if not conversacion.resumen_conversacion and session.agente_ia and session.agente_ia.apikey and session.agente_ia.descripcion:
            agente = session.agente_ia
            consultor = AgenteResumidor(
                provider=agente.apikey.proveedor,
                apikey=agente.apikey.descripcion, conversacion=conversacion
            )
            conversacion.resumen_conversacion = consultor.resumir()
        conversacion.despedida_enviado = True
        conversacion.conversacion_finalizada = True
        conversacion.save()
except Exception as e:
    print(f"Error al enviar mensajes de despedida: {e}")