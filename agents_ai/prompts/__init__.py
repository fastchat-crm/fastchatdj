"""Paquete central de prompts del sistema IA.

Todo prompt del sistema vive en agents_ai:
  - plantillas.py       : PROMPT_TEMPLATES — template maestro del agente conversacional
  - personalidades.py   : PERSONALIDAD_PRESETS + choices + FRASES_RELLENO (humanización)
  - ai_actions/prompts.py : registry de prompts de las acciones IA one-shot
                            (campañas, horarios, pipeline, plantillas WA)
  - auditor_agente.py   : AUDITOR_SYSTEM_PROMPT (auditoría de agentes)

Compat: `from core.constantes import PROMPT_TEMPLATES, PERSONALIDAD_PRESETS, ...`
sigue funcionando — core/constantes.py re-exporta desde aquí.
"""
from .plantillas import PROMPT_TEMPLATES
from .personalidades import (
    PERSONALIDAD_PRESETS,
    PERSONALIDAD_PRESET_CHOICES,
    FRASES_RELLENO,
)

__all__ = [
    'PROMPT_TEMPLATES',
    'PERSONALIDAD_PRESETS', 'PERSONALIDAD_PRESET_CHOICES', 'FRASES_RELLENO',
]
