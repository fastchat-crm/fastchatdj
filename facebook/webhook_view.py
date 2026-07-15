"""Receiver del webhook de Facebook Messenger — expuesto bajo `/facebook/webhook/`.

La implementación es compartida con Instagram (mismo payload Meta `page`) y vive
en `whatsapp.meta_social_webhook_view`, junto al pipeline de mensajería que
alimenta (`process_incoming_message`, `EventoMetaRecibido`, `common_meta`). Aquí
sólo se re-exporta el entrypoint para que cada red tenga su webhook bajo su
propia app/URL.

URL canónica: /facebook/webhook/
Alias legacy (compat): /whatsapp/messenger_webhook/
"""
from whatsapp.meta_social_webhook_view import messenger_webhook  # noqa: F401
