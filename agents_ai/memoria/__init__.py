"""Paquete de memoria del agente.

Estructura:
  - historial.py          : DjangoChatMessageHistory — memoria conversacional
                            por conversación sobre la tabla MessageStore
  - rag_conversaciones.py : memoria RAG por agente — FAISS con pares
                            pregunta→respuesta aprendidos de conversaciones previas

Compat: `from agents_ai.memoria_django import DjangoChatMessageHistory` sigue
funcionando vía shim.
"""
from .historial import DjangoChatMessageHistory
from .rag_conversaciones import (
    guardar_interaccion,
    guardar_interaccion_async,
    guardar_conocimiento,
    recuperar_memoria,
    memoria_existe,
    ruta_memoria_agente,
)

__all__ = [
    'DjangoChatMessageHistory',
    'guardar_interaccion', 'guardar_interaccion_async', 'guardar_conocimiento',
    'recuperar_memoria', 'memoria_existe', 'ruta_memoria_agente',
]
