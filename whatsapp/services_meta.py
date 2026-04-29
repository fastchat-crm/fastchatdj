"""Shim — la implementación vive en `meta.whatsapp`.

Para código nuevo preferí `from meta.whatsapp import MetaWhatsAppService`.
Acá re-exportamos los símbolos públicos para no romper imports legacy.
"""
from meta.whatsapp import (  # noqa: F401
    MetaWhatsAppService,
    GRAPH_API_VERSION,
    GRAPH_API_BASE,
    _sanitizar_header_meta,
)
