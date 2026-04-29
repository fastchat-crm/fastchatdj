"""Generador IA de PlantillaWhatsApp (Meta Cloud API).

Dos puntos de entrada (preservan los 2 flujos UI existentes):

- `generar_uno(descripcion_usuario, sesion)` — UNA plantilla; usado por la
  accion `generar_con_ia` del modulo plantillas. Requiere `sesion.agente_ia`
  (la apikey y el contexto se sacan de ahi).
- `generar_lote(descripcion, n, sesion, apikey_obj)` — N plantillas; usado por
  la accion `preview_plantillas_ia` (preview multi-variante antes de
  confirmar). La view resuelve la apikey con fallback al perfil del usuario.

La persistencia (confirmar plantillas) es responsabilidad de la view porque
no toca el LLM.
"""
import logging

from .base import IAActionError, invocar_json
from .prompts import get_prompt

logger = logging.getLogger(__name__)


# ============================================================================
# Constantes de validacion compartidas con la view
# ============================================================================
VALID_CATEGORIAS = {'UTILITY', 'MARKETING', 'AUTHENTICATION'}
HEADER_TIPOS_OK = {'NONE', 'TEXT', 'IMAGE', 'VIDEO', 'DOCUMENT'}


# ============================================================================
# Generador single (mantiene el flujo del action 'generar_con_ia')
# ============================================================================
def generar_uno(*, descripcion_usuario: str, sesion) -> dict:
    """Genera UNA plantilla via LLM, sin persistir.

    Args:
        descripcion_usuario: solicitud del usuario (no vacia).
        sesion: SesionWhatsApp; debe tener `agente_ia` con apikey activa.
                El contexto del negocio se compone de
                `agente_ia.perfil.resumen_contexto_ia()` + `agente_ia.contexto_estatico`.

    Returns:
        dict con keys: plantilla (dict crudo de la IA), tokens, modelo.

    Raises:
        IAActionError — descripcion vacia, sesion sin agente, agente sin apikey,
        LLM error o JSON malformado.
    """
    descripcion_usuario = (descripcion_usuario or '').strip()
    if not descripcion_usuario:
        raise IAActionError("Escribe una descripcion de la plantilla que quieres generar.")
    if not sesion:
        raise IAActionError("Sesion no encontrada.")
    agente = getattr(sesion, 'agente_ia', None)
    if not agente:
        raise IAActionError("La sesion no tiene un agente IA asignado.")
    apikey = agente.apikey.filter(estado=True).first()
    if not apikey:
        raise IAActionError("El agente no tiene API Keys activas.")

    contexto_negocio = ''
    if getattr(agente, 'perfil', None):
        try:
            contexto_negocio = agente.perfil.resumen_contexto_ia() or ''
        except Exception:
            contexto_negocio = ''
    if getattr(agente, 'contexto_estatico', None):
        contexto_negocio += '\n\nInformacion adicional del agente:\n' + agente.contexto_estatico[:2000]

    prompt = get_prompt(
        'plantillas_wa.uno',
        contexto_negocio=contexto_negocio or '(sin contexto)',
        descripcion_usuario=descripcion_usuario,
    )

    plantilla, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey,
        origen='plantilla',
        agente=agente,
        prompt_preview=descripcion_usuario[:300],
        max_tokens=4000,
        temperature=0.4,
    )

    return {
        'plantilla': plantilla,
        'tokens': tokens,
        'modelo': modelo,
    }


# ============================================================================
# Generador lote (mantiene el flujo del action 'preview_plantillas_ia')
# ============================================================================
def _sanitizar_plantilla(p: dict) -> dict:
    """Sanitiza UNA plantilla del lote contra reglas duras de Meta.

    Llama al sanitizador del header de Meta (`whatsapp.services_meta`)
    para limpiar caracteres prohibidos y trunca campos a sus limites.
    """
    from whatsapp.services_meta import _sanitizar_header_meta

    cat = str(p.get('categoria') or 'UTILITY').upper()
    if cat not in VALID_CATEGORIAS:
        cat = 'UTILITY'
    ht = str(p.get('header_tipo') or 'NONE').upper()
    if ht not in HEADER_TIPOS_OK:
        ht = 'NONE'
    return {
        'nombre':           (str(p.get('nombre') or '').strip().lower().replace(' ', '_'))[:60],
        'idioma':           (str(p.get('idioma') or 'es')).strip()[:8],
        'categoria':        cat,
        'header_tipo':      ht,
        'header_contenido': _sanitizar_header_meta(p.get('header_contenido') or '') if ht == 'TEXT' else '',
        'cuerpo':           (str(p.get('cuerpo') or '').strip())[:1024],
        'footer':           _sanitizar_header_meta(p.get('footer') or ''),
    }


def generar_lote(*, descripcion: str, n: int, sesion, apikey_obj) -> dict:
    """Genera N plantillas via LLM (preview), sin persistir.

    Args:
        descripcion: solicitud del usuario (>=10 chars).
        n: cantidad de plantillas a generar (clamp a [1, 10]).
        sesion: SesionWhatsApp Meta (con `config_meta`). Se usa para extraer
                contexto del negocio si tiene `agente_ia.perfil`.
        apikey_obj: ApiKeyIA validada (puede venir del agente o del perfil
                    via fallback en la view).

    Returns:
        dict con keys: plantillas (lista sanitizada), count, tokens, modelo.

    Raises:
        IAActionError — descripcion corta, JSON malformado, LLM error.
    """
    descripcion = (descripcion or '').strip()
    if len(descripcion) < 10:
        raise IAActionError("Describe al menos 10 caracteres.")
    n = max(1, min(int(n or 3), 10))

    if not sesion:
        raise IAActionError("Sesion Meta no encontrada.")
    if not apikey_obj:
        raise IAActionError("No hay API Key IA activa. Configura una en CRM -> Entrenamiento.")

    contexto_negocio = ''
    agente_ia = getattr(sesion, 'agente_ia', None)
    if agente_ia and getattr(agente_ia, 'perfil', None):
        try:
            contexto_negocio = (agente_ia.perfil.resumen_contexto_ia() or '')[:2000]
        except Exception:
            contexto_negocio = ''

    prompt = get_prompt(
        'plantillas_wa.lote',
        n=n,
        descripcion=descripcion,
        contexto_negocio=contexto_negocio or '(sin contexto adicional)',
    )

    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='plantilla',
        agente=agente_ia,
        prompt_preview=descripcion[:300],
        max_tokens=4000,
        temperature=0.6,
    )

    plantillas_raw = payload.get('plantillas') if isinstance(payload, dict) else None
    if not isinstance(plantillas_raw, list):
        raise IAActionError("Estructura JSON invalida (esperaba lista 'plantillas').")

    plantillas_clean = [
        _sanitizar_plantilla(p) for p in plantillas_raw[:n] if isinstance(p, dict)
    ]

    return {
        'plantillas': plantillas_clean,
        'count': len(plantillas_clean),
        'tokens': tokens,
        'modelo': modelo,
    }
