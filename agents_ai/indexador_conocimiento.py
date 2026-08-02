"""Shim de compatibilidad.

La implementación del indexador de conocimiento (provisión de tenant,
reindexación, extracción de detalle) se movió a `agents_ai/rag/indexador.py`.
Este módulo re-exporta la API pública y los helpers internos que aún se usan
desde fuera (`_resolver_gemini_key`, `_extraer_detalle`) para no romper imports
existentes (`from agents_ai import indexador_conocimiento as _idx`, etc.).
"""
from agents_ai.rag.indexador import *  # noqa: F401,F403
from agents_ai.rag.indexador import (  # noqa: F401
    _resolver_gemini_key,
    _extraer_detalle,
)
