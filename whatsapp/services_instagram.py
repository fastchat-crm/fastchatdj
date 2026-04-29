"""Shim — la implementación vive en `meta.instagram`.

Para código nuevo preferí `from meta.instagram import InstagramService, MessengerService`.
"""
from meta.instagram import (  # noqa: F401
    InstagramService,
    MessengerService,
    GRAPH_API_VERSION,
    GRAPH_API_BASE,
)
