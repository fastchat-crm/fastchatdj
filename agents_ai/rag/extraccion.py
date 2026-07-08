"""Tubería única de extracción de texto para el RAG.

Orden de extracción:
  1. txt/md → lectura directa (sin servicios ni loaders).
  2. Formatos estructurados (csv/json/xlsx) → loader local primero (conserva
     estructura), Tika de respaldo.
  3. Resto (pdf, doc, docx, ppt, imágenes, etc.) → Tika primero (incluye OCR
     para PDFs escaneados), loader local de respaldo.

Extraer texto NO consume tokens LLM — el único costo posterior es el embedding.
"""
import logging
import os

from .tika_client import EXTENSIONES_TIKA, extraer_texto_tika, tika_disponible

logger = logging.getLogger(__name__)

_EXT_TEXTO_PLANO = ('.txt', '.md')
_EXT_ESTRUCTURADOS = ('.csv', '.json', '.xlsx')


def _extraer_texto_local(file_path: str) -> str:
    """Extracción con loaders locales de LangChain (pypdf, csv, json, excel)."""
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.pdf':
            from langchain_community.document_loaders import PyPDFLoader
            docs = PyPDFLoader(file_path).load()
        elif ext == '.csv':
            from langchain_community.document_loaders import CSVLoader
            docs = CSVLoader(file_path).load()
        elif ext == '.xlsx':
            from langchain_community.document_loaders import UnstructuredExcelLoader
            docs = UnstructuredExcelLoader(file_path).load()
        elif ext == '.json':
            from langchain_community.document_loaders import JSONLoader
            docs = JSONLoader(file_path).load()
        else:
            return ''
        return "\n".join(d.page_content for d in docs if d.page_content.strip())
    except Exception as e:
        logger.warning("Extracción local falló (%s): %s", file_path, e)
        return ''


def extraer_texto_archivo(file_path: str) -> str:
    """Extrae el texto completo de un archivo sin fragmentarlo ni embedear."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in _EXT_TEXTO_PLANO:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read().strip()
        except OSError as e:
            logger.warning("No se pudo leer %s: %s", file_path, e)
            return ''

    if ext in _EXT_ESTRUCTURADOS:
        texto = _extraer_texto_local(file_path)
        if texto:
            return texto
        if tika_disponible():
            return extraer_texto_tika(file_path)
        return ''

    if tika_disponible() and ext.lstrip('.') in EXTENSIONES_TIKA:
        texto = extraer_texto_tika(file_path)
        if texto:
            return texto

    return _extraer_texto_local(file_path)
