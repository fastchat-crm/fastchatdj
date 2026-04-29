"""Generador IA de horarios de atencion + excepciones (feriados).

Dos puntos de entrada (mantienen los 2 actions UI existentes):

- `generar_semanales(descripcion, sesion, apikey_obj, request)` — convierte
  descripcion natural en bloques `HorarioAtencion` (dia, hora_inicio, hora_fin).
  Usado por la accion `generar_horarios_ia`.
- `generar_excepciones(descripcion, sesion, apikey_obj, request)` — convierte
  descripcion natural en `ExcepcionHorario` (fecha + abierto + motivo).
  Usado por la accion `generar_excepciones_ia`.
"""
import datetime as _dt
import logging

from .base import IAActionError, invocar_json
from .prompts import get_prompt

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers de validacion
# ============================================================================
def _validar_horarios(items) -> list:
    """Valida y normaliza items de horario crudos del LLM."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            d = int(it.get('dia_semana'))
            hi = str(it.get('hora_inicio'))[:5]
            hf = str(it.get('hora_fin'))[:5]
            if 0 <= d <= 6 and len(hi) == 5 and len(hf) == 5:
                out.append({'dia_semana': d, 'hora_inicio': hi, 'hora_fin': hf})
        except (TypeError, ValueError):
            continue
    return out


def _validar_excepciones(items) -> list:
    """Valida y normaliza items de excepcion crudos del LLM."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            fecha = str(it.get('fecha') or '')[:10]
            _dt.datetime.strptime(fecha, '%Y-%m-%d')
            abierto = bool(it.get('abierto'))
            motivo = str(it.get('motivo') or '')[:200]
            out.append({'fecha': fecha, 'abierto': abierto, 'motivo': motivo})
        except (TypeError, ValueError):
            continue
    return out


# ============================================================================
# Punto de entrada — horarios semanales
# ============================================================================
def generar_semanales(*, descripcion: str, sesion, apikey_obj, request) -> dict:
    """Genera horarios semanales via LLM y los persiste como `HorarioAtencion`.

    Returns: {items, count, message, tokens, modelo}.
    Raises: IAActionError si descripcion corta, JSON invalido o LLM error.
    """
    from whatsapp.models import HorarioAtencion

    descripcion = (descripcion or '').strip()
    if len(descripcion) < 10:
        raise IAActionError("Describe con mas detalle (minimo 10 chars).")
    if not sesion:
        raise IAActionError("Sesion no encontrada.")

    prompt = get_prompt('horarios_wa.semanales', descripcion=descripcion)

    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='otro',
        prompt_preview=descripcion[:300],
        max_tokens=4000,
        temperature=0.3,
    )

    horarios = _validar_horarios(payload.get('horarios') if isinstance(payload, dict) else None)

    for it in horarios:
        HorarioAtencion.objects.create(
            sesion=sesion,
            dia_semana=it['dia_semana'],
            hora_inicio=it['hora_inicio'],
            hora_fin=it['hora_fin'],
            activo=True,
            usuario_creacion=request.user,
        )

    return {
        'items': horarios,
        'count': len(horarios),
        'message': f'{len(horarios)} horario(s) generado(s) por IA.',
        'tokens': tokens,
        'modelo': modelo,
    }


# ============================================================================
# Punto de entrada — excepciones / feriados
# ============================================================================
def generar_excepciones(*, descripcion: str, sesion, apikey_obj, request) -> dict:
    """Genera excepciones (feriados/dias especiales) via LLM y persiste como
    `ExcepcionHorario` con `update_or_create` por (sesion, fecha)."""
    from whatsapp.models import ExcepcionHorario

    descripcion = (descripcion or '').strip()
    if len(descripcion) < 10:
        raise IAActionError("Describe con mas detalle (minimo 10 chars).")
    if not sesion:
        raise IAActionError("Sesion no encontrada.")

    anio_actual = _dt.date.today().year
    prompt = get_prompt(
        'horarios_wa.excepciones',
        anio_actual=anio_actual,
        descripcion=descripcion,
    )

    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='otro',
        prompt_preview=descripcion[:300],
        max_tokens=4000,
        temperature=0.3,
    )

    excepciones = _validar_excepciones(payload.get('excepciones') if isinstance(payload, dict) else None)

    for it in excepciones:
        ExcepcionHorario.objects.update_or_create(
            sesion=sesion,
            fecha=it['fecha'],
            defaults={
                'abierto': it['abierto'],
                'motivo': it['motivo'],
                'usuario_creacion': request.user,
            },
        )

    return {
        'items': excepciones,
        'count': len(excepciones),
        'message': f'{len(excepciones)} excepcion(es) generada(s) por IA.',
        'tokens': tokens,
        'modelo': modelo,
    }
