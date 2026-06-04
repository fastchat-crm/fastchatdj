"""
cron_jobs/enviar_mensaje_reconexion.py

Envía el mensaje de reconexión de la sesión a las conversaciones ABIERTAS que
quedaron en silencio: el último mensaje es nuestro (saliente) y ya pasó más de
1 hora sin que el cliente responda, siempre dentro de la ventana de 24 h del
cliente (regla de WhatsApp/Meta para texto libre).

Pensado para correr cada hora. Solo envía UN nudge por silencio: marca
`conversacion.reconexion_enviada = True` y no vuelve a enviar hasta que el
cliente escriba de nuevo (procesar_mensaje resetea el flag al entrar su mensaje).
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Q
from django.utils import timezone

from core.funciones import logCron
from whatsapp.models import ConversacionWhatsApp, MensajeWhatsApp
from whatsapp.services import get_whatsapp_service

PROCESO = 'Reconexión de Conversaciones'

MINUTOS_INACTIVIDAD = 60
HORAS_VENTANA = 24


def _broadcast(conversacion):
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'chat_{conversacion.id}', {'type': 'whatsapp_message'}
            )
    except Exception:
        pass


ahora = timezone.now()
corte_inactividad = ahora - timedelta(minutes=MINUTOS_INACTIVIDAD)
corte_ventana = ahora - timedelta(hours=HORAS_VENTANA)

conversaciones = ConversacionWhatsApp.objects.filter(
    estado_conversacion=0,
    conversacion_finalizada=False,
    reconexion_enviada=False,
    contacto__sesion__activo=True,
    contacto__sesion__reconexion_activa=True,
).exclude(
    Q(contacto__sesion__mensaje_reconexion__isnull=True)
    | Q(contacto__sesion__mensaje_reconexion='')
).select_related('contacto', 'contacto__sesion')

total = conversaciones.count()

if total == 0:
    logCron(PROCESO, 'Sin conversaciones candidatas para reconexión', exito=True)
else:
    logCron(PROCESO, f'Evaluando {total} conversación(es) abierta(s)', exito=True)
    enviados = 0
    for conversacion in conversaciones:
        try:
            sesion = conversacion.contacto.sesion
            numero = sesion.numero
            texto = (sesion.mensaje_reconexion or '').strip()
            if not texto:
                continue

            ultimo = conversacion.mensajes.order_by('-fecha', '-id').first()
            if not ultimo or not ultimo.fecha:
                continue
            # El último mensaje debe ser nuestro (saliente).
            if ultimo.remitente != numero:
                continue
            # Debe llevar más de 1 hora sin respuesta del cliente.
            if ultimo.fecha > corte_inactividad:
                continue

            # Respetar ventana de 24 h: el cliente tuvo que escribir hace < 24 h.
            ultimo_entrante = (
                conversacion.mensajes.exclude(remitente=numero)
                .order_by('-fecha', '-id').first()
            )
            if not ultimo_entrante or not ultimo_entrante.fecha:
                continue
            if ultimo_entrante.fecha < corte_ventana:
                continue

            service = get_whatsapp_service(sesion)
            respuesta = service.send_text_message(
                sesion.session_id, conversacion.from_number, texto,
                conversacion_id=conversacion.id,
            )
            if not respuesta.get('success', False):
                logCron(
                    PROCESO,
                    f'Conversación #{conversacion.id}: falló envío de reconexión '
                    f'({respuesta.get("error", "error desconocido")})',
                    exito=False,
                )
                continue

            MensajeWhatsApp.objects.create(
                mensaje_id_externo=respuesta.get('message_id'),
                conversacion=conversacion,
                remitente=numero,
                mensaje=texto,
                tipo='texto',
                fecha=timezone.now(),
                leido=True,
                fecha_leido=timezone.now(),
                ia_generado=False,
                estado_envio='enviado',
            )
            conversacion.reconexion_enviada = True
            conversacion.save(update_fields=['reconexion_enviada'])
            _broadcast(conversacion)
            enviados += 1
            logCron(PROCESO, f'Reconexión enviada a conversación #{conversacion.id}', exito=True)
        except Exception as e:
            logCron(PROCESO, f'Error en conversación #{conversacion.id}: {e}', exito=False)

    logCron(PROCESO, f'Proceso finalizado. {enviados} reconexión(es) enviada(s) de {total} evaluada(s)', exito=True)
