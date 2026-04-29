"""Utilidades de horario de atención (business hours)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

from django.utils import timezone

from .models import ExcepcionHorario, HorarioAtencion, SesionWhatsApp


def _ahora_en_tz_sesion(sesion: SesionWhatsApp) -> datetime:
    tz_name = sesion.zona_horaria or 'America/Guayaquil'
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.get_current_timezone()
    return timezone.now().astimezone(tz)


def dentro_de_horario(sesion: SesionWhatsApp,
                      momento: Optional[datetime] = None) -> bool:
    """Devuelve True si `momento` está dentro del horario de atención de la
    sesión. Si no hay horarios configurados, asume 24/7 abierto."""
    tiene_horario = sesion.horarios.filter(status=True, activo=True).exists()
    if not tiene_horario:
        return True

    ahora = momento or _ahora_en_tz_sesion(sesion)
    fecha = ahora.date()
    hora = ahora.time()

    excepcion = sesion.excepciones_horario.filter(
        fecha=fecha, status=True,
    ).first()
    if excepcion:
        if not excepcion.abierto:
            return False
        if excepcion.hora_inicio and excepcion.hora_fin:
            return excepcion.hora_inicio <= hora <= excepcion.hora_fin
        return True

    dia = ahora.weekday()  # 0=lunes .. 6=domingo
    horarios = sesion.horarios.filter(
        status=True, activo=True, dia_semana=dia,
    )
    for h in horarios:
        if h.hora_inicio <= hora <= h.hora_fin:
            return True
    return False


def mensaje_fuera_horario_configurado(sesion: SesionWhatsApp) -> Optional[str]:
    txt = (sesion.mensaje_fuera_horario or '').strip()
    return txt or None
