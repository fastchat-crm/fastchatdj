import os, sys
from datetime import datetime

from django.core.wsgi import get_wsgi_application
from django.db import transaction
from django.db.models import Q

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from whatsapp.models import MensajeWhatsAppProgramado
from whatsapp.services import get_whatsapp_service
from core.funciones import logCron


ahora = datetime.now()
hoy = ahora.date()
hora_actual = ahora.time()

mensajes_programados = MensajeWhatsAppProgramado.objects.filter(
    status=True,
    enviado=False,
    contacto__sesion__proveedor='baileys',
).filter(Q(fecha__lt=hoy) | Q(fecha=hoy, hora__lte=hora_actual))

try:
    with transaction.atomic():
        for mensaje in mensajes_programados:
            sesion = mensaje.sesion
            sesion_id = sesion.session_id
            from_number = mensaje.from_number
            archivo = mensaje.archivo
            texto = mensaje.mensaje
            whatsapp_service = get_whatsapp_service(sesion)
            response = whatsapp_service.send_text_message(sesion_id, from_number, texto, simularEscritura=True)
            if not response.get('success', False):
                logCron(f"Mensajes Programados", f"Error al enviar mensaje programado: {mensaje.__str__()}", False)
                continue
            if archivo:
                filename = archivo.name.split('/')[1] if '/' in archivo.name else archivo.name
                response_archivo = whatsapp_service.send_media_message(sesion_id, from_number, caption=texto, file_content=archivo.read(), filename=filename)
                if not response_archivo.get('success', False):
                    logCron(f"Mensajes Programados", f"Error al enviar archivo del mensaje programado: {mensaje.__str__()}", False)
                    continue
            mensaje.enviado = True
            mensaje.fecha_envio = ahora
            mensaje.save()
            logCron(f"Mensajes Programados", f"Mensaje programado enviado: {mensaje.__str__()}", True)
except Exception as e:
    logCron(f"Mensajes Programados", f"Error al enviar mensajes programados: {str(e)}", False)
    print(f"Error al enviar mensajes de despedida: {e}")