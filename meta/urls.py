"""Helpers de URL para Graph API y Facebook OAuth.

Centraliza la version de la API para que un upgrade (v22 → v23) sea un solo cambio.
"""
from __future__ import annotations

from django.conf import settings


def _version() -> str:
    """Lee la versión configurada o cae a un default conservador."""
    return getattr(settings, 'META_API_VERSION', 'v22.0')


# Constante exportada para los pocos call sites que la quieran inline.
# Se evalua en import-time pero es seguro: settings ya está cargado cuando
# se importa este módulo desde una vista o servicio.
GRAPH_API_VERSION = _version()


def build_graph_url(path: str) -> str:
    """Devuelve URL absoluta a Graph API.

    `path` debe empezar con '/' (ej: '/me', '/{app_id}/businesses').
    """
    if not path.startswith('/'):
        path = '/' + path
    return f'https://graph.facebook.com/{_version()}{path}'


def build_fb_url(path: str) -> str:
    """Devuelve URL absoluta a www.facebook.com (OAuth dialog, etc).

    `path` debe empezar con '/'.
    """
    if not path.startswith('/'):
        path = '/' + path
    return f'https://www.facebook.com/{_version()}{path}'
