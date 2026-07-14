import os, sys
from datetime import datetime

from django.core.wsgi import get_wsgi_application
from django.db.models import F, Q

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from django.core.cache import cache

from whatsapp.models import MensajeWhatsAppProgramado, ConversacionWhatsApp
from whatsapp.services import get_whatsapp_service
from core.funciones import logCron


MAX_INTENTOS = 3

ahora = datetime.now()
hoy = ahora.date()
hora_actual = ahora.time()

mensajes_programados = MensajeWhatsAppProgramado.objects.filter(
    status=True,
    enviado=False,
    intentos__lt=MAX_INTENTOS,
    contacto__sesion__proveedor__in=('baileys', 'meta'),
    contacto__sesion__activo=True,
    contacto__opt_out=False,
    contacto__whatsapp_invalido=False,
).filter(Q(fecha__lt=hoy) | Q(fecha=hoy, hora__lte=hora_actual))

for mensaje in mensajes_programados:
    try:
        sesion = mensaje.sesion
        sesion_id = sesion.session_id
        from_number = mensaje.from_number
        archivo = mensaje.archivo
        texto = mensaje.mensaje
        conversacion_id = None
        if sesion.proveedor == 'meta':
            # Ventana 24h de Meta: si ya está bloqueado, reintentar recién en 6h
            # (o cuando el cliente vuelva a escribir y reabra la ventana).
            if cache.get(f'prog_meta_bloqueado_{mensaje.id}'):
                continue
            conv = ConversacionWhatsApp.objects.filter(contacto=mensaje.contacto).order_by('-id').first()
            conversacion_id = conv.id if conv else None
        # Claim atómico ANTES de enviar: si otro proceso ya lo tomó, update
        # devuelve 0 y se salta — evita doble envío con crons concurrentes.
        claimed = MensajeWhatsAppProgramado.objects.filter(
            pk=mensaje.pk, enviado=False,
        ).update(enviado=True, fecha_envio=ahora)
        if not claimed:
            continue
        whatsapp_service = get_whatsapp_service(sesion)
        response = whatsapp_service.send_text_message(
            sesion_id, from_number, texto, simularEscritura=True,
            conversacion_id=conversacion_id,
        )
        if not response.get('success', False):
            MensajeWhatsAppProgramado.objects.filter(pk=mensaje.pk).update(
                enviado=False, fecha_envio=None, intentos=F('intentos') + 1,
            )
            if response.get('requiere_plantilla'):
                cache.set(f'prog_meta_bloqueado_{mensaje.id}', 1, 6 * 3600)
                logCron(
                    "Mensajes Programados",
                    f"Ventana 24h vencida para {mensaje.__str__()} — se reintenta cada 6h "
                    f"o cuando el cliente vuelva a escribir. Alternativa: enviar una plantilla aprobada.",
                    False,
                )
            else:
                logCron("Mensajes Programados", f"Error al enviar mensaje programado: {mensaje.__str__()}", False)
            continue
        if archivo:
            filename = archivo.name.split('/')[1] if '/' in archivo.name else archivo.name
            response_archivo = whatsapp_service.send_media_message(sesion_id, from_number, caption=texto, file_content=archivo.read(), filename=filename)
            if not response_archivo.get('success', False):
                # El texto ya salió: se mantiene enviado=True para no duplicarlo;
                # el adjunto perdido queda registrado en el log.
                logCron("Mensajes Programados", f"Error al enviar archivo del mensaje programado: {mensaje.__str__()}", False)
                continue
        logCron("Mensajes Programados", f"Mensaje programado enviado: {mensaje.__str__()}", True)
    except Exception as e:
        MensajeWhatsAppProgramado.objects.filter(pk=mensaje.pk, enviado=True, fecha_envio=ahora).update(
            enviado=False, fecha_envio=None, intentos=F('intentos') + 1,
        )
        logCron("Mensajes Programados", f"Error al enviar mensajes programados: {str(e)}", False)
        print(f"Error al enviar mensaje programado: {e}")
