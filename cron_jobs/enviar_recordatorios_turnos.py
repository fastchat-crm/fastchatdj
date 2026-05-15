import os
import sys
from datetime import timedelta

from django.core.wsgi import get_wsgi_application
from django.db import transaction
from django.utils import timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from agenda.models import ACTIVE_STATUSES, Turno
from core.funciones import logCron
from whatsapp.services import get_whatsapp_service


CRON_WINDOW_MIN = 30


def _build_message(turno):
    grupo = turno.recurso.grupo_agenda
    return (
        f"Reminder: you have an appointment\n"
        f"- {turno.servicio.nombre}\n"
        f"- With: {turno.recurso.nombre}\n"
        f"- When: {turno.inicio.strftime('%Y-%m-%d %H:%M')}\n"
        f"- Price: {turno.precio_cobrado} {grupo.moneda}\n"
        f"\nReply *cancel* to cancel or *reschedule* to move it."
    )


def _enviar(turno):
    sesion = turno.contacto.sesion
    if not sesion or not sesion.activo:
        return False, 'Session inactive'
    service = get_whatsapp_service(sesion)
    response = service.send_text_message(
        sesion.session_id,
        turno.contacto.from_number,
        _build_message(turno),
    )
    if not response.get('success', False):
        return False, response.get('error') or response.get('message') or 'Send failed'
    return True, 'OK'


def main():
    ahora = timezone.now()
    pendientes = (Turno.objects
                  .filter(status=True, recordatorio_enviado=False, estado__in=ACTIVE_STATUSES)
                  .select_related('recurso__grupo_agenda', 'servicio', 'contacto__sesion'))
    enviados = 0
    fallidos = 0
    for turno in pendientes:
        horas = turno.recurso.grupo_agenda.recordatorio_horas_antes or 24
        ventana_inicio = ahora + timedelta(hours=horas)
        ventana_fin = ventana_inicio + timedelta(minutes=CRON_WINDOW_MIN)
        if not (ventana_inicio <= turno.inicio <= ventana_fin):
            continue
        try:
            with transaction.atomic():
                ok, msg = _enviar(turno)
                if ok:
                    turno.recordatorio_enviado = True
                    turno.save()
                    enviados += 1
                    logCron('Reminders', f'Reminder sent for appointment {turno.id}', True)
                else:
                    fallidos += 1
                    logCron('Reminders', f'Failed to send reminder for appointment {turno.id}: {msg}', False)
        except Exception as ex:
            fallidos += 1
            logCron('Reminders', f'Exception sending reminder for appointment {turno.id}: {ex}', False)
    logCron('Reminders', f'Run complete. Sent={enviados}, failed={fallidos}', True)


if __name__ == '__main__':
    main()
