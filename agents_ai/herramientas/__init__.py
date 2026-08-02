"""Herramientas (tools) que el LLM puede invocar vía function-calling.

  - builder.py : construye tools LangChain dinámicas desde `HerramientaAgente`
                 (HTTP) y las tools estáticas del agente.

Compat: `from agents_ai.tools_builder import build_tools_de_agente` sigue
funcionando — `agents_ai/tools_builder.py` re-exporta desde aquí.
"""
from .builder import build_tools_de_agente

__all__ = ['build_tools_de_agente']
