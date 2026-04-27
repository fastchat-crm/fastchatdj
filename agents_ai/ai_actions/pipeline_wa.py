"""Generador IA de PipelineVenta + EtapaPipeline (Kanban de ventas).

Punto de entrada: `generar(descripcion, n_etapas, apikey_obj, request)`.
Crea un PipelineVenta y sus EtapaPipeline en la misma transaccion.
"""
import logging

from .base import IAActionError, invocar_json
from .prompts import get_prompt

logger = logging.getLogger(__name__)


def _normalizar_etapa(et: dict, indice: int) -> dict | None:
    """Valida y normaliza una etapa cruda del LLM. Devuelve None si invalida."""
    if not isinstance(et, dict):
        return None
    nombre = str(et.get('nombre') or f'Etapa {indice + 1}').strip()[:80]
    color = str(et.get('color') or '#6c757d').strip()[:7]
    if not color.startswith('#'):
        color = '#6c757d'
    try:
        prob = max(0, min(int(et.get('probabilidad_cierre') or 0), 100))
    except (TypeError, ValueError):
        prob = 0
    return {
        'nombre': nombre,
        'color': color,
        'probabilidad_cierre': prob,
        'es_ganado': bool(et.get('es_ganado')),
        'es_perdido': bool(et.get('es_perdido')),
    }


def generar(*, descripcion: str, n_etapas: int, apikey_obj, request) -> dict:
    """Genera PipelineVenta + sus EtapaPipeline via LLM y los persiste.

    Args:
        descripcion: descripcion del negocio (>=10 chars).
        n_etapas: cantidad sugerida de etapas (clamp 3-8). El LLM puede
                  generar [n-1, n+1] etapas para flexibilidad.
        apikey_obj: ApiKeyIA validada.
        request: HttpRequest (necesario para `usuario_creacion`).

    Returns:
        dict: pipeline_id, nombre, etapas_creadas, message, tokens, modelo.

    Raises:
        IAActionError — descripcion corta, JSON malformado, < 2 etapas validas.
    """
    from whatsapp.models import EtapaPipeline, PipelineVenta

    descripcion = (descripcion or '').strip()
    try:
        n_etapas = int(n_etapas or 5)
    except (TypeError, ValueError):
        n_etapas = 5
    n_etapas = max(3, min(n_etapas, 8))

    if len(descripcion) < 10:
        raise IAActionError(
            "Describe brevemente tu negocio (10+ caracteres) para que la IA pueda armar etapas relevantes."
        )

    prompt = get_prompt(
        'pipeline_wa',
        n_min=n_etapas - 1,
        n_max=n_etapas + 1,
        descripcion=descripcion,
    )

    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='otro',
        prompt_preview=descripcion[:300],
        max_tokens=2000,
        temperature=0.5,
    )

    nombre = str(payload.get('nombre') or 'Pipeline generado por IA').strip()[:60]
    descripcion_p = str(payload.get('descripcion') or descripcion).strip()[:200]
    etapas_raw = payload.get('etapas') or []
    if not isinstance(etapas_raw, list) or len(etapas_raw) < 2:
        raise IAActionError("La IA no genero etapas validas. Reintenta con mas detalle.")

    etapas_norm = [n for et in etapas_raw if (n := _normalizar_etapa(et, etapas_raw.index(et))) is not None]

    pipe = PipelineVenta.objects.create(
        nombre=nombre,
        descripcion=descripcion_p,
        usuario_creacion=request.user,
    )
    creadas = 0
    for i, et in enumerate(etapas_norm):
        EtapaPipeline.objects.create(
            pipeline=pipe,
            nombre=et['nombre'],
            orden=i + 1,
            color=et['color'],
            probabilidad_cierre=et['probabilidad_cierre'],
            es_ganado=et['es_ganado'],
            es_perdido=et['es_perdido'],
            usuario_creacion=request.user,
        )
        creadas += 1

    return {
        'pipeline_id': pipe.id,
        'nombre': nombre,
        'etapas_creadas': creadas,
        'message': f'Pipeline "{nombre}" creado con {creadas} etapas.',
        'tokens': tokens,
        'modelo': modelo,
    }
