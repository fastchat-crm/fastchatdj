"""Generador IA de Campana (multi-canal: WhatsApp / Instagram / Messenger).

Punto de entrada: `generar(descripcion_usuario, sesion, apikey_obj)`.
NO persiste — devuelve la configuracion lista para que el wizard del
frontend pre-rellene el formulario de campana.
"""
import logging
import time

from .base import IAActionError, invocar_json
from .prompts import get_prompt

logger = logging.getLogger(__name__)


_TIPOS_VALIDOS = ('texto', 'plantilla', 'media')


def _coerce_str(v, default: str = '') -> str:
    if v is None:
        return default
    if isinstance(v, str):
        return v
    try:
        return str(v)
    except Exception:
        return default


def generar(*, descripcion_usuario: str, sesion, apikey_obj) -> dict:
    """Genera la configuracion de una Campana via LLM, sin persistir.

    Args:
        descripcion_usuario: objetivo de la campana en lenguaje natural (>=15 chars).
        sesion: SesionWhatsApp activa del usuario (define `canal_principal`
                via `get_proveedor_display()`).
        apikey_obj: ApiKeyIA validada (la view la resuelve buscando la
                    primera apikey activa del perfil del usuario).

    Returns:
        dict con keys: campana (nombre, descripcion, mensaje_texto, tipo,
        throttle_por_minuto), latencia_ms, tokens, modelo.

    Raises:
        IAActionError — descripcion corta, sesion ausente, JSON malformado.
    """
    descripcion_usuario = (descripcion_usuario or '').strip()
    if len(descripcion_usuario) < 15:
        raise IAActionError("Describe con mas detalle la campana (minimo 15 caracteres).")
    if not sesion:
        raise IAActionError("Selecciona una sesion primero.")

    canal_principal = ''
    try:
        canal_principal = sesion.get_proveedor_display()
    except Exception:
        canal_principal = getattr(sesion, 'proveedor', '') or 'whatsapp'

    prompt = get_prompt(
        'campanas_wa',
        canal_principal=canal_principal,
        descripcion_usuario=descripcion_usuario,
    )

    t0 = time.time()
    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='otro',
        prompt_preview=descripcion_usuario[:300],
        max_tokens=2000,
        temperature=0.7,
    )
    latencia_ms = int((time.time() - t0) * 1000)

    nombre = _coerce_str(payload.get('nombre'), 'Campana generada').strip()[:150] or 'Campana generada'
    descripcion = _coerce_str(payload.get('descripcion'), '').strip()[:500]
    mensaje_texto = _coerce_str(payload.get('mensaje_texto'), '').strip()[:4000]
    tipo = _coerce_str(payload.get('tipo'), 'texto').strip().lower()
    if tipo not in _TIPOS_VALIDOS:
        tipo = 'texto'
    try:
        throttle = int(payload.get('throttle_por_minuto') or 20)
    except (TypeError, ValueError):
        throttle = 20
    throttle = max(5, min(throttle, 200))

    return {
        'campana': {
            'nombre': nombre,
            'descripcion': descripcion,
            'mensaje_texto': mensaje_texto,
            'tipo': tipo,
            'throttle_por_minuto': throttle,
        },
        'latencia_ms': latencia_ms,
        'tokens': tokens,
        'modelo': modelo,
    }
