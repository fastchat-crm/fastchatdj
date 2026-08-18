"""Cliente Apache Tika — extracción de texto de documentos sin gastar tokens LLM.

Tika corre como servicio HTTP (imagen docker apache/tika, ideal la variante
-full con Tesseract para OCR). La URL y el switch on/off viven en la tabla
Configuración (seguridad.Configuracion.tika_url / tika_activo) — editables
desde el panel administrador.

El texto extraído alimenta el RAG (FAISS) o el contexto estático del agente:
el único costo posterior es el embedding, nunca tokens LLM por leer el PDF.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

_TIMEOUT_NORMAL = 60
_TIMEOUT_OCR = 120
_MIN_CHARS_SIN_OCR = 80

EXTENSIONES_LOCALES = ('pdf', 'csv', 'json', 'xlsx', 'txt', 'md')

EXTENSIONES_TIKA = (
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'odt', 'odp', 'ods', 'rtf', 'epub',
    'html', 'htm', 'xlsx', 'xls',
    'png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'webp',
)


def get_tika_url() -> str:
    """URL del servicio Tika según la Configuración del sistema. '' si está apagado.

    Cacheada 60 s — la extracción por lotes (entrenamiento con N archivos) no
    repite las queries de Configuracion por cada archivo.
    """
    try:
        from django.core.cache import cache
        cacheada = cache.get('tika_url_config')
        if cacheada is not None:
            return cacheada
        from seguridad.models import Configuracion
        confi = Configuracion.get_instancia()
        if not getattr(confi, 'tika_activo', False):
            url = ''
        else:
            url = (getattr(confi, 'tika_url', '') or '').strip().rstrip('/')
        cache.set('tika_url_config', url, 60)
        return url
    except Exception as exc:
        logger.debug("No se pudo leer configuración de Tika: %s", exc)
        return ''


def tika_disponible() -> bool:
    return bool(get_tika_url())


def extensiones_soportadas() -> list:
    """Extensiones aceptadas para entrenamiento — se amplía si Tika está activo."""
    exts = set(EXTENSIONES_LOCALES)
    if tika_disponible():
        exts.update(EXTENSIONES_TIKA)
    return sorted(exts)


def ping_tika(url: str = None, timeout: int = 5) -> dict:
    """Verifica si el servicio Tika responde. Devuelve {activo, version|error}."""
    url = (url or '').strip().rstrip('/') or get_tika_url()
    if not url:
        return {'activo': False, 'error': 'Servicio Tika desactivado o sin URL configurada.'}
    try:
        r = requests.get(f'{url}/version', timeout=timeout)
        if r.ok:
            return {'activo': True, 'url': url, 'version': r.text.strip()[:100]}
        return {'activo': False, 'url': url, 'error': f'HTTP {r.status_code}'}
    except Exception as exc:
        return {'activo': False, 'url': url, 'error': str(exc)[:200]}


def _put_tika(url: str, contenido: bytes, headers: dict, timeout: int) -> str:
    r = requests.put(f'{url}/tika', data=contenido, headers=headers, timeout=timeout)
    if r.ok:
        r.encoding = 'utf-8'
        return r.text or ''
    logger.warning("Tika devolvió HTTP %s", r.status_code)
    return ''


def extraer_texto_tika(file_path: str) -> str:
    """Extrae texto plano de un archivo vía Tika. Reintenta con OCR para PDFs escaneados.

    Devuelve '' si Tika está apagado, no responde o el archivo no tiene texto legible.
    """
    url = get_tika_url()
    if not url:
        return ''
    try:
        with open(file_path, 'rb') as f:
            contenido = f.read()
    except OSError as exc:
        logger.warning("No se pudo leer %s: %s", file_path, exc)
        return ''

    headers = {
        'Accept': 'text/plain',
        'X-Tika-OCRLanguage': 'spa+eng',
    }
    try:
        texto = _put_tika(url, contenido, headers, _TIMEOUT_NORMAL)
    except Exception as exc:
        logger.warning("Error consultando Tika (%s): %s", file_path, exc)
        return ''

    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf' and len((texto or '').strip()) < _MIN_CHARS_SIN_OCR:
        headers_ocr = dict(headers)
        headers_ocr['X-Tika-PDFOcrStrategy'] = 'ocr_and_text'
        try:
            texto_ocr = _put_tika(url, contenido, headers_ocr, _TIMEOUT_OCR)
            if len((texto_ocr or '').strip()) > len((texto or '').strip()):
                texto = texto_ocr
        except Exception as exc:
            logger.warning("Reintento OCR de Tika falló (%s): %s", file_path, exc)

    return (texto or '').strip()
