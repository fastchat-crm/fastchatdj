"""Shim de compatibilidad.

`AgenteResumidor` se movió a `agents_ai/agentes/resumidor.py`. Este módulo
re-exporta la API pública para no romper imports existentes
(`from agents_ai.agente_resumidor import AgenteResumidor`).
"""
from agents_ai.agentes.resumidor import *  # noqa: F401,F403
from agents_ai.agentes.resumidor import AgenteResumidor  # noqa: F401

__all__ = ['AgenteResumidor']
