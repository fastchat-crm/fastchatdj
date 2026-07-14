"""Respuestas del cliente a un recordatorio de turno — captura determinista.

El recordatorio del cron ofrece confirmar/cancelar respondiendo por WhatsApp.
Este módulo resuelve esas respuestas SIN pasar por el LLM (cero tokens):
process_incoming_message lo consulta antes del motor de flujo y del pipeline
IA y, si el mensaje es una palabra clave y el contacto tiene un turno
recordado vigente, aplica el cambio de estado y devuelve el texto a responder.
"""
import logging
import re
import unicodedata

from django.utils import timezone

logger = logging.getLogger(__name__)

_CONFIRMAR = frozenset({'confirmar', 'confirmo', 'confirmado', 'si confirmo'})
_CANCELAR = frozenset({'cancelar', 'cancelo', 'cancelar turno', 'cancelar cita', 'cancelar mi cita'})


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z\s]', '', texto.lower()).strip()


def _turno_recordado(contacto):
    from .models import ACTIVE_STATUSES, Turno
    return (Turno.objects
            .filter(contacto=contacto, status=True, recordatorio_enviado=True,
                    estado__in=ACTIVE_STATUSES, inicio__gt=timezone.now())
            .select_related('servicio', 'recurso__grupo_agenda')
            .order_by('inicio')
            .first())


def procesar_respuesta_recordatorio(contacto, texto) -> str | None:
    """Devuelve el texto a responder si el mensaje resuelve un recordatorio.

    None si no aplica (no es palabra clave o no hay turno recordado vigente) —
    en ese caso el pipeline sigue su curso normal (motor/IA).
    """
    t = _normalizar(texto)
    if t not in _CONFIRMAR and t not in _CANCELAR:
        return None
    turno = _turno_recordado(contacto)
    if turno is None:
        return None
    fecha_fmt = turno.inicio.strftime('%d/%m/%Y a las %H:%M')
    if t in _CONFIRMAR:
        if turno.estado != 'confirmed':
            turno.estado = 'confirmed'
            turno.save()
        logger.info('Turno %s confirmado por respuesta al recordatorio', turno.id)
        return (f"✅ ¡Listo! Tu turno de {turno.servicio.nombre} con {turno.recurso.nombre} "
                f"el {fecha_fmt} quedó confirmado. ¡Te esperamos!")
    turno.estado = 'cancelled'
    turno.save()
    logger.info('Turno %s cancelado por respuesta al recordatorio', turno.id)
    _notificar_cancelacion(turno)
    return (f"Tu turno de {turno.servicio.nombre} el {fecha_fmt} fue cancelado. "
            f"Si querés reagendar, escribime y buscamos otro horario.")


def _notificar_cancelacion(turno):
    try:
        from core.funciones import notificacion
        responsable = turno.recurso.grupo_agenda.responsable
        if not responsable:
            return
        notificacion(
            titulo='Turno cancelado por el cliente',
            cuerpo=(f'El cliente <strong>{turno.contacto.contacto_nombre or turno.contacto.from_number}</strong> '
                    f'canceló su turno de {turno.servicio.nombre} con {turno.recurso.nombre} '
                    f'del {turno.inicio:%d/%m/%Y %H:%M} respondiendo al recordatorio.'),
            destinatario=responsable,
            url='/agenda/',
            prioridad=1,
            tipo=4,
        )
    except Exception:
        logger.exception('No se pudo notificar la cancelación del turno %s', turno.id)
