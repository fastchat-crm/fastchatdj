"""Paquete RAG — ingesta de documentos y vectorstores.

Estructura:
  - tika_client.py  : cliente HTTP de Apache Tika (extracción de texto + OCR)
  - extraccion.py   : tubería única de extracción de texto (Tika primero,
                      loaders locales de respaldo)
  - vectorstore.py  : VectorStoreManager — chunking, embeddings y FAISS

Compat: `from agents_ai.vectorstore_manager import VectorStoreManager` sigue
funcionando vía shim.
"""
from .tika_client import (
    tika_disponible,
    ping_tika,
    extraer_texto_tika,
    extensiones_soportadas,
    get_tika_url,
)
from .extraccion import extraer_texto_archivo
from .vectorstore import VectorStoreManager

__all__ = [
    'tika_disponible', 'ping_tika', 'extraer_texto_tika', 'extensiones_soportadas',
    'get_tika_url', 'extraer_texto_archivo', 'VectorStoreManager',
]
