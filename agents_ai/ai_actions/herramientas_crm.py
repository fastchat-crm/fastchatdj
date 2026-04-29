"""Generador IA de configuracion de HerramientaAgente (asistente IA).

El usuario describe en lenguaje natural que necesita consultar (ej. "saber
estado del envio dado un codigo") y este modulo devuelve la configuracion
completa de la HerramientaAgente lista para guardar (nombre, metodo,
parametros, plantilla de respuesta, etc.).

Punto de entrada: `generar(frase, agente, request)`.
"""
import logging

from .base import IAActionError, invocar_json
from .prompts import get_prompt

logger = logging.getLogger(__name__)


def generar(*, frase: str, agente, request) -> dict:
    """Genera el dict de configuracion de una HerramientaAgente via LLM.

    NO persiste en DB — devuelve la configuracion para que el frontend la
    pre-cargue en el wizard y el usuario la edite/confirme.

    Args:
        frase: descripcion del usuario en lenguaje natural (>=1 char util).
        agente: AgentesIA al que se asociara la herramienta (define la apikey
                a usar — primera apikey activa del agente).
        request: HttpRequest (no usado actualmente, dejado por simetria con
                 las otras acciones que si necesitan audit / save).

    Returns:
        dict con keys: config (dict listo para HerramientaAgenteForm),
        tokens, modelo.

    Raises:
        IAActionError — frase vacia, agente sin apikey, JSON malformado.
    """
    frase = (frase or '').strip()
    if not frase:
        raise IAActionError("Describe que necesita consultar la herramienta.")

    apikey_obj = agente.apikey.filter(estado=True).first()
    if not apikey_obj:
        raise IAActionError("El agente no tiene una API Key activa.")

    prompt = get_prompt('herramientas_crm', descripcion_usuario=frase)

    config, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='herramienta',
        agente=agente,
        prompt_preview=frase[:300],
        max_tokens=4000,
        temperature=0.3,
    )

    return {
        'config': config,
        'tokens': tokens,
        'modelo': modelo,
    }
