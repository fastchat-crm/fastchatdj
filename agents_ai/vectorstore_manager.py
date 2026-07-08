"""Shim de compatibilidad — el módulo vive ahora en agents_ai/rag/vectorstore.py."""
from .rag.vectorstore import VectorStoreManager

__all__ = ['VectorStoreManager']
