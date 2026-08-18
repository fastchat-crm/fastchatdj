"""Receiver del webhook de Instagram DM — expuesto bajo `/instagram/webhook/`.

La implementación es compartida con Messenger (mismo payload Meta `page`) y vive
en `whatsapp.meta_social_webhook_view`, junto al pipeline de mensajería que
alimenta (`process_incoming_message`, `EventoMetaRecibido`, `common_meta`). Aquí
sólo se re-exporta el entrypoint para que cada red tenga su webhook bajo su
propia app/URL.

URL canónica: /instagram/webhook/
Alias legacy (compat): /whatsapp/instagram_webhook/
"""
from whatsapp.meta_social_webhook_view import instagram_webhook  # noqa: F401
