"""Shim de compatibilidad.

La implementación de Weaviate RAG multi-tenant se movió a
`agents_ai/rag/weaviate.py`. Este módulo re-exporta la API pública para no
romper imports existentes (`from agents_ai import weaviate_rag`,
`from agents_ai.weaviate_rag import buscar`, etc.).
"""
from agents_ai.rag.weaviate import *  # noqa: F401,F403
from agents_ai.rag import weaviate as _weaviate

__all__ = getattr(_weaviate, '__all__', [n for n in dir(_weaviate) if not n.startswith('_')])
