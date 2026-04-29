"""Shim — la implementación vive en `meta.capi`.

Para código nuevo preferí `from meta.capi import enviar_evento, reportar_purchase, reportar_lead_si_corresponde`.
"""
from meta.capi import (  # noqa: F401
    enviar_evento,
    reportar_lead_si_corresponde,
    reportar_purchase,
    GRAPH_API_VERSION,
    GRAPH_API_BASE,
)
