import os
import sys
from datetime import timedelta

from django.core.wsgi import get_wsgi_application
from django.db.models import F
from django.utils import timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from agenda.models import ACTIVE_STATUSES, Turno
from core.funciones import logCron
from whatsapp.services import get_whatsapp_service


MAX_INTENTOS = 3


def _build_message(turno):
    grupo = turno.recurso.grupo_agenda
    return (
        f"Recordatorio: tenés un turno\n"
        f"- {turno.servicio.nombre}\n"
        f"- Con: {turno.recurso.nombre}\n"
        f"- Cuándo: {turno.inicio.strftime('%Y-%m-%d %H:%M')}\n"
        f"- Precio: {turno.precio_cobrado} {grupo.moneda}\n"
        f"\nRespondé *confirmar* para confirmarlo, *cancelar* para cancelarlo "
        f"o *reagendar* para moverlo."
    )


def _enviar(turno):
    sesion = turno.contacto.sesion
    if not sesion or not sesion.activo:
        return False, 'Sesión inactiva'
    service = get_whatsapp_service(sesion)
    response = service.send_text_message(
        sesion.session_id,
        turno.contacto.from_number,
        _build_message(turno),
    )
    if not response.get('success', False):
        return False, response.get('error') or response.get('message') or 'Falló el envío'
    return True, 'OK'


def main():
    ahora = timezone.now()
    # Catch-up: un turno está "vencido para recordar" desde (inicio - horas_antes)
    # hasta su inicio. Si el cron estuvo caído, el recordatorio sale igual en la
    # próxima corrida en vez de perderse (antes había una ventana fija de 30 min).
    pendientes = (Turno.objects
                  .filter(status=True, recordatorio_enviado=False,
                          estado__in=ACTIVE_STATUSES,
                          recordatorio_intentos__lt=MAX_INTENTOS,
                          inicio__gt=ahora)
                  .select_related('recurso__grupo_agenda', 'servicio', 'contacto__sesion'))
    enviados = 0
    fallidos = 0
    for turno in pendientes:
        horas = (turno.recordatorio_horas_antes
                 or turno.recurso.grupo_agenda.recordatorio_horas_antes
                 or 24)
        momento_aviso = turno.inicio - timedelta(hours=horas)
        if ahora < momento_aviso:
            continue
        # Reserva hecha DESPUÉS del momento de aviso (ej. turno para dentro de
        # 2h con recordatorio de 24h): no se recuerda — el cliente acaba de
        # agendar y ya recibió la confirmación.
        if turno.fecha_registro and turno.fecha_registro > momento_aviso:
            continue
        # Claim atómico ANTES de enviar: si otro proceso ya lo tomó, update
        # devuelve 0 y se salta — evita doble envío con crons concurrentes.
        claimed = Turno.objects.filter(
            pk=turno.pk, recordatorio_enviado=False,
        ).update(recordatorio_enviado=True)
        if not claimed:
            continue
        try:
            ok, msg = _enviar(turno)
        except Exception as ex:
            ok, msg = False, str(ex)
        if ok:
            enviados += 1
            logCron('Recordatorios', f'Recordatorio enviado para turno {turno.id}', True)
        else:
            fallidos += 1
            Turno.objects.filter(pk=turno.pk).update(
                recordatorio_enviado=False,
                recordatorio_intentos=F('recordatorio_intentos') + 1,
            )
            logCron('Recordatorios', f'Falló el envío del recordatorio para turno {turno.id}: {msg}', False)
    logCron('Recordatorios', f'Ejecución completada. Enviados={enviados}, fallidos={fallidos}', True)


if __name__ == '__main__':
    main()
