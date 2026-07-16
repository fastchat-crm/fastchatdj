"""Paquete meta — todas las llamadas directas a la Meta Graph API.

Organización por dominio:

| Módulo               | Para qué |
|----------------------|----------|
| `meta.urls`          | Helpers de URL (build_graph_url, build_fb_url, version) |
| `meta.credenciales`  | Lee `CredencialMetaApp` (BD) con fallback a settings |
| `meta.webhook`       | Firma HMAC, handshake, extractores de payload |
| `meta.autodetect`    | Auto-detecta App / Business / SystemUser / Embedded Signup config_id |
| `meta.validacion`    | Checklist completo (App + Token + Scopes + WABA…) |
| `meta.perfiles`      | Verifica perfiles IG / Messenger / WA contra Graph |
| **Senders por canal**|  |
| `meta.whatsapp`      | `MetaWhatsAppService` — envío WA Cloud + plantillas + media |
| `meta.instagram`     | `InstagramService`, `MessengerService` — DMs IG/FB |
| `meta.capi`          | Conversions API — eventos Lead / Purchase para Ads Manager |

Para código nuevo:
    from meta import build_graph_url, get_meta_config_id
    from meta.whatsapp import MetaWhatsAppService
    from meta.instagram import InstagramService

Los archivos legacy en `whatsapp/services_*.py` y `whatsapp/common_meta.py`
son shims que re-exportan de acá para no romper imports existentes.
"""
from meta.urls import (
    GRAPH_API_VERSION,
    build_graph_url,
    build_fb_url,
)
from meta.credenciales import (
    get_meta_app_credentials,
    get_meta_app_secret,
    get_meta_app_secrets,
    get_meta_config_id,
)
from meta.webhook import (
    validar_firma_hmac,
    responder_handshake,
    extraer_phone_number_id,
    extraer_ig_user_id,
    extraer_page_id,
    extraer_tipo_evento,
)
from meta.autodetect import auto_detectar_meta
from meta.validacion import validar_credenciales, SCOPES_REQUERIDOS

__all__ = [
    # urls
    'GRAPH_API_VERSION', 'build_graph_url', 'build_fb_url',
    # credenciales
    'get_meta_app_credentials', 'get_meta_app_secret', 'get_meta_app_secrets', 'get_meta_config_id',
    # webhook
    'validar_firma_hmac', 'responder_handshake',
    'extraer_phone_number_id', 'extraer_ig_user_id', 'extraer_page_id',
    'extraer_tipo_evento',
    # autodetect / validacion
    'auto_detectar_meta', 'validar_credenciales', 'SCOPES_REQUERIDOS',
]
