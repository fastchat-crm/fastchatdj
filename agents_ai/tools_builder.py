"""Shim de compatibilidad.

El constructor de herramientas dinámicas (HerramientaAgente → tools LangChain)
se movió a `agents_ai/herramientas/builder.py`. Este módulo re-exporta la API
pública para no romper imports existentes
(`from agents_ai.tools_builder import build_tools_de_agente`).
"""
from agents_ai.herramientas.builder import *  # noqa: F401,F403
from agents_ai.herramientas.builder import build_tools_de_agente  # noqa: F401

__all__ = ['build_tools_de_agente']
