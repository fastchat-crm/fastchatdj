"""Shim de compatibilidad.

El auditor IA de agentes se movió a `agents_ai/agentes/auditor.py`. Este módulo
re-exporta la API pública y el helper interno `_detectar_respuestas_problema`
(usado desde fuera) para no romper imports existentes.
"""
from agents_ai.agentes.auditor import *  # noqa: F401,F403
from agents_ai.agentes.auditor import _detectar_respuestas_problema  # noqa: F401
