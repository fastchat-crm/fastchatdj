"""Shim de compatibilidad — el módulo vive ahora en agents_ai/memoria/historial.py."""
from .memoria.historial import DjangoChatMessageHistory

__all__ = ['DjangoChatMessageHistory']
