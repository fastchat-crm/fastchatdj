"""Shim de compatibilidad.

El prompt recomendado se movió a `agents_ai/prompts/recomendados.py`. Este
módulo re-exporta el símbolo para no romper imports existentes
(`from agents_ai.prompts_recomendados import PROMPT_RECOMENDADO`).
"""
from .prompts.recomendados import PROMPT_RECOMENDADO

__all__ = ['PROMPT_RECOMENDADO']
