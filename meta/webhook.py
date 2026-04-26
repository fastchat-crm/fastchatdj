"""Validación de firma HMAC, handshake del verify_token y extractores
de payload — comunes a los 3 webhooks Meta (WhatsApp Cloud, Instagram,
Messenger).

Movido desde `whatsapp/common_meta.py` (que ahora re-exporta de acá para
no romper imports legacy).
"""
from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def validar_firma_hmac(raw_body: bytes, signature_header: str, app_secret: str | None) -> bool:
    """Compara `X-Hub-Signature-256` contra HMAC(app_secret, body).

    Si no hay `app_secret` configurado devolvemos True (modo permisivo para
    setup inicial — el operador debe setearlo para endurecer). Si hay app_secret
    pero no llegó header de firma, rechazamos.
    """
    if not app_secret:
        return True
    if not signature_header:
        return False
    try:
        expected = 'sha256=' + hmac.new(
            app_secret.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)
    except Exception:
        logger.exception("Error computando HMAC")
        return False


def responder_handshake(request, verify_token_esperado: str):
    """Maneja el handshake GET estándar de los webhooks Meta.

    Devuelve un tuple `(ok: bool, response_text: str | None, status: int)`.
    - Handshake válido → `(True, challenge, 200)`.
    - verify_token no matchea → `(False, 'forbidden', 403)`.
    - Sin parámetros suficientes → `(False, None, 0)` (caller decide).
    """
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    if not (mode and challenge is not None):
        return False, None, 0

    if mode != 'subscribe':
        return False, 'invalid_mode', 400
    if not token:
        return False, 'missing_verify_token', 400
    if token != verify_token_esperado:
        return False, 'forbidden', 403

    return True, challenge, 200


def extraer_phone_number_id(payload: dict) -> str | None:
    """Extrae `metadata.phone_number_id` del payload WA Cloud API."""
    try:
        for entry in payload.get('entry') or []:
            for change in entry.get('changes') or []:
                meta = (change.get('value') or {}).get('metadata') or {}
                if meta.get('phone_number_id'):
                    return meta['phone_number_id']
    except Exception:
        pass
    return None


def extraer_ig_user_id(payload: dict) -> str | None:
    """Extrae el IGSID del payload Instagram Graph API.

    `entry[].id` es el ig_user_id (cuenta Business); los `messaging[]`
    traen `sender.id` (IGSID del usuario) y `recipient.id` (IGSID del
    negocio, mismo que `entry.id`).
    """
    try:
        entries = payload.get('entry') or []
        for entry in entries:
            eid = entry.get('id')
            if eid:
                return eid
    except Exception:
        pass
    return None


def extraer_page_id(payload: dict) -> str | None:
    """Extrae el Page ID del payload Messenger (`entry[].id`)."""
    try:
        entries = payload.get('entry') or []
        for entry in entries:
            eid = entry.get('id')
            if eid:
                return eid
    except Exception:
        pass
    return None


def extraer_tipo_evento(payload: dict) -> str:
    """Detecta el `field` / tipo del evento para auditoría + ruteo."""
    try:
        entries = payload.get('entry') or []
        if not entries:
            return 'unknown'
        first = entries[0]
        # WA Cloud → entry.changes[0].field
        changes = first.get('changes') or []
        if changes:
            return changes[0].get('field') or 'unknown'
        # Messenger / IG → entry.messaging[0]
        messaging = first.get('messaging') or []
        if messaging:
            first_msg = messaging[0]
            if first_msg.get('message'):  return 'messages'
            if first_msg.get('postback'): return 'postback'
            if first_msg.get('reaction'): return 'reaction'
            if first_msg.get('read'):     return 'read'
            if first_msg.get('delivery'): return 'delivery'
            return 'messaging_other'
    except Exception:
        pass
    return 'unknown'
