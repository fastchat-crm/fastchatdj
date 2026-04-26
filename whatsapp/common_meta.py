"""Shim de compatibilidad — toda esta lógica vive ahora en el paquete `meta/`.

Re-exportamos los símbolos públicos para no romper imports legacy:

    from whatsapp.common_meta import get_meta_app_credentials, validar_firma_hmac

Para código nuevo preferí importar directo del paquete:

    from meta import get_meta_app_credentials, validar_firma_hmac
    # o más específico:
    from meta.credenciales import get_meta_app_credentials
    from meta.webhook import validar_firma_hmac
"""
from meta.credenciales import (
    get_meta_app_credentials,
    get_meta_app_secret,
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

__all__ = [
    'get_meta_app_credentials', 'get_meta_app_secret', 'get_meta_config_id',
    'validar_firma_hmac', 'responder_handshake',
    'extraer_phone_number_id', 'extraer_ig_user_id', 'extraer_page_id',
    'extraer_tipo_evento',
]
