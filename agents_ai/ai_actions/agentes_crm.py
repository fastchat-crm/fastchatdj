"""Generador IA de AgentesIA (asistente "crear agente").

Punto de entrada: `generar(descripcion, tono, idioma, apikey_obj, perfil, request)`.
La logica HTTP / extraccion de POST se queda en la view; aca solo vive la
construccion del prompt, llamada al LLM, validacion de placeholders criticos,
y persistencia del AgentesIA + asignacion de la apikey.
"""
import logging

from .base import IAActionError, invocar_json
from .prompts import get_prompt

logger = logging.getLogger(__name__)


# Placeholders criticos que el `prompt_template` generado DEBE incluir,
# si no, se cae al template default.
PLACEHOLDERS_REQUERIDOS = ('{descripcion_agente}', '{question}', '{context}')

# Fallback ultra-conservador si no hay PROMPT_TEMPLATES disponibles.
PROMPT_TEMPLATE_FALLBACK = (
    "Eres un asistente para: {descripcion_agente}\n"
    "{contexto_extra}Cliente: {question}\n====\n{context}\n====\nRespuesta:"
)


def _coerce_str(v, default: str = '') -> str:
    """Coerciona cualquier valor a str (sin lanzar). Util cuando el LLM
    devuelve numeros/null en campos que esperabamos string."""
    if v is None:
        return default
    if isinstance(v, str):
        return v
    try:
        return str(v)
    except Exception:
        return default


def _resolver_template_default() -> str:
    """Plantilla por defecto del sistema (espanol). Se importa lazy para no
    crear ciclos al cargar este modulo."""
    try:
        from core.constantes import PROMPT_TEMPLATES
        return PROMPT_TEMPLATES.get('es') or ''
    except Exception:
        return ''


def generar(*, descripcion: str, tono: str, idioma: str,
            apikey_obj, perfil, request) -> dict:
    """Genera un AgentesIA completo via LLM y lo persiste en DB.

    Args:
        descripcion: descripcion del rol/alcance (>=15 chars).
        tono: 'amigable', 'formal', 'cercano', etc. Default 'amigable'.
        idioma: codigo corto, 'es' por defecto.
        apikey_obj: ApiKeyIA validada (se asigna al agente creado).
        perfil: PerfilNegocioIA padre del agente.
        request: HttpRequest (necesario para `agente.save(request)` que
                 ejecuta el audit del ModeloBase).

    Returns:
        dict con keys: agente_id, nombre, descripcion, prompt_template,
        contexto_estatico, anotar_listas, tokens, modelo.

    Raises:
        IAActionError — input invalido, JSON malformado, LLM error.
    """
    from crm.models import AgentesIA

    descripcion = (descripcion or '').strip()
    tono = (tono or 'amigable').strip()[:60] or 'amigable'
    idioma = (idioma or 'es').strip()[:8] or 'es'

    if len(descripcion) < 15:
        raise IAActionError(
            "Describe con mas detalle que debe hacer el agente (minimo 15 caracteres)."
        )

    prompt = get_prompt(
        'agentes_crm',
        tono=tono,
        idioma=idioma,
        descripcion_usuario=descripcion,
    )

    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='otro',
        prompt_preview=descripcion[:300],
        max_tokens=4000,
        temperature=0.4,
    )

    default_tpl = _resolver_template_default()

    nombre = _coerce_str(payload.get('nombre'), 'Agente generado').strip()[:255] or 'Agente generado'
    descripcion_ag = _coerce_str(payload.get('descripcion'), descripcion).strip()[:4000] or descripcion
    prompt_tpl = _coerce_str(payload.get('prompt_template'), '').strip() or default_tpl
    contexto_est_raw = _coerce_str(payload.get('contexto_estatico'), '').strip()
    contexto_est = contexto_est_raw or None
    anotar = bool(payload.get('anotar_listas'))

    # Validar placeholders criticos — si faltan, usar plantilla default
    if not prompt_tpl or not all(p in prompt_tpl for p in PLACEHOLDERS_REQUERIDOS):
        prompt_tpl = default_tpl
    if not prompt_tpl:
        prompt_tpl = PROMPT_TEMPLATE_FALLBACK

    agente = AgentesIA(
        perfil=perfil,
        nombre=nombre,
        descripcion=descripcion_ag,
        prompt_template=prompt_tpl,
        contexto_estatico=contexto_est,
        anotar_listas=anotar,
    )
    agente.save(request)
    agente.apikey.add(apikey_obj)

    return {
        'agente_id': agente.id,
        'nombre': agente.nombre,
        'descripcion': agente.descripcion,
        'prompt_template': agente.prompt_template,
        'contexto_estatico': agente.contexto_estatico or '',
        'anotar_listas': agente.anotar_listas,
        'tokens': tokens,
        'modelo': modelo,
    }
