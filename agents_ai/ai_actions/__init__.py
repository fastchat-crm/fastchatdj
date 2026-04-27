"""Acciones IA estandarizadas (generar/llenar/validar contenidos via LLM).

Cada submodulo `<modulo>_<app>.py` (ej. `dpchatbots_crm.py`, `plantillas_wa.py`)
expone una funcion publica `generar(...)` (o equivalente) que centraliza la
logica que antes vivia duplicada en views de `crm/`, `whatsapp/`, etc.

Punto unico de configuracion del LLM: `base.py` (resuelve provider, fuerza
JSON, registra `ConsumoTokenIA`, parsea respuesta tolerando prosa/fences).

Para agregar una accion nueva:
  1. Crear `agents_ai/ai_actions/<modulo>_<app>.py`
  2. Definir prompt en `prompts.py` (clave en el dict PROMPTS)
  3. Implementar `generar(...)` que llama a `base.invocar_json(...)`
  4. La view externa solo importa y llama: `from agents_ai.ai_actions import <modulo>_<app>`
"""
from .base import (
    IAActionError,
    build_llm,
    invocar_json,
    log_consumo,
    parse_json_response,
    validar_apikey,
)

__all__ = [
    'IAActionError',
    'build_llm',
    'invocar_json',
    'log_consumo',
    'parse_json_response',
    'validar_apikey',
]
