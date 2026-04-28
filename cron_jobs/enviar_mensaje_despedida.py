"""
cron_jobs/enviar_mensaje_despedida.py

Cierra conversaciones que han superado su tiempo de expiración (fecha_hora_expira < now).

La lógica de cierre vive en ConversacionWhatsApp.cerrar() — aquí sólo se
seleccionan las candidatas y se delega el cierre con los flags del cron.
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from django.utils import timezone

from core.funciones import logCron
from whatsapp.models import ConversacionWhatsApp

PROCESO = 'Cierre Automático de Conversaciones'


conversaciones = ConversacionWhatsApp.objects.filter(
    despedida_enviado=False,
    conversacion_finalizada=False,
    fecha_hora_expira__lt=timezone.now(),
    contacto__sesion__activo=True,
).select_related(
    'contacto',
    'contacto__sesion',
    'contacto__sesion__agente_ia',
    'asignado_a',
)

total = conversaciones.count()

if total == 0:
    logCron(PROCESO, 'Sin conversaciones expiradas pendientes de cerrar', exito=True)
else:
    logCron(PROCESO, f'Procesando {total} conversación(es) expirada(s)', exito=True)
    for conversacion in conversaciones:
        try:
            cerrada = conversacion.cerrar(
                enviar_despedida=True,
                respetar_asignacion_humana=True,
                respetar_bloqueo_cierre=True,
            )
            if cerrada:
                logCron(PROCESO, f'Conversación #{conversacion.id} cerrada por expiración', exito=True)
            else:
                logCron(
                    PROCESO,
                    f'Conversación #{conversacion.id} omitida (asignada a humano, bloqueada o ya cerrada)',
                    exito=True,
                )
        except Exception as e:
            logCron(PROCESO, f'Error al cerrar conversación #{conversacion.id}: {e}', exito=False)
