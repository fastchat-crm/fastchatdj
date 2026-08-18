"""Paquete del motor conversacional (AgenteConsultor).

Estructura:
  - clasificacion.py : detección de saludos, acks y consultas amplias (regex, sin LLM)
  - retrieval.py     : cache FAISS, búsqueda híbrida BM25+MMR, recortes de contexto

La clase AgenteConsultor vive en agents_ai/agente_consultor.py y consume estos
módulos. Los imports públicos externos no cambian:
  from agents_ai.agente_consultor import AgenteConsultor
"""
from .clasificacion import (
    normalizar_texto,
    _es_saludo,
    _es_ack_simple,
    _es_consulta_amplia,
    _GREETING_WORDS,
)
from .retrieval import (
    _get_vectorstore_cached,
    invalidate_vectorstore_cache,
    _build_bm25,
    _get_bm25_cached,
    _hybrid_search,
    _dedup_preservando_orden,
    _trim_contexto,
    _extraer_seccion_relevante,
)

__all__ = [
    'normalizar_texto', '_es_saludo', '_es_ack_simple', '_es_consulta_amplia',
    '_get_vectorstore_cached', 'invalidate_vectorstore_cache', '_build_bm25',
    '_get_bm25_cached', '_hybrid_search', '_dedup_preservando_orden',
    '_trim_contexto', '_extraer_seccion_relevante',
]
