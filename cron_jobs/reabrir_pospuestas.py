import os, sys

from django.core.wsgi import get_wsgi_application
from django.utils import timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from whatsapp.models import ConversacionWhatsApp
from core.funciones import logCron


ahora = timezone.now()

vencidas = ConversacionWhatsApp.objects.filter(
    status=True,
    snooze_hasta__isnull=False,
    snooze_hasta__lte=ahora,
)

total = 0
try:
    for conv in vencidas:
        conv.snooze_hasta = None
        conv.estado_atencion = 'abierta'
        conv.save(update_fields=['snooze_hasta', 'estado_atencion'])
        total += 1
    logCron('reabrir_pospuestas', f'{total} conversaciones reabiertas', exito=True)
except Exception as ex:
    logCron('reabrir_pospuestas', f'Error: {ex}', exito=False)
    raise
