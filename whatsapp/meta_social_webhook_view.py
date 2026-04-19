"""Receivers de webhooks Instagram DM y Messenger.

Comparten estructura con `meta_webhook_view.py`:
  - GET → handshake con `hub.verify_token`.
  - POST → eventos firmados con HMAC-SHA256 contra `app_secret`.

El payload Meta (page) trae mensajes en `entry[].messaging[]` (legacy) o en
`entry[].messages[]` para IG. Lo traducimos al shape interno y reusamos
`process_incoming_message` igual que el receiver de WhatsApp Cloud.

URLs:
  /whatsapp/instagram_webhook/
  /whatsapp/messenger_webhook/
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from channels.layers import get_channel_layer

from .models import (
    ConfigInstagram,
    ConfigMessenger,
    EventoMetaRecibido,
    SesionWhatsApp,
)
from .view_webhook_handler import process_incoming_message
from .trazas import registrar as _traza

logger = logging.getLogger(__name__)


def _validar_hmac(raw_body: bytes, sig_header: str, secret: str) -> bool:
    if not secret:
        return True
    if not sig_header:
        return False
    try:
        expected = 'sha256=' + hmac.new(
            secret.encode('utf-8'), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

@csrf_exempt
def instagram_webhook(request):
    if request.method == 'GET':
        return _handshake_generico(request, ConfigInstagram, 'instagram')
    if request.method == 'POST':
        return _procesar_post_social(request, ConfigInstagram, 'instagram')
    return HttpResponse(status=405)


# ---------------------------------------------------------------------------
# Messenger
# ---------------------------------------------------------------------------

@csrf_exempt
def messenger_webhook(request):
    if request.method == 'GET':
        return _handshake_generico(request, ConfigMessenger, 'messenger')
    if request.method == 'POST':
        return _procesar_post_social(request, ConfigMessenger, 'messenger')
    return HttpResponse(status=405)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handshake_generico(request, ConfigCls, canal):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge', '')
    if mode != 'subscribe' or not token:
        return HttpResponse('bad_request', status=400)
    config = ConfigCls.objects.filter(webhook_verify_token=token).first()
    if not config:
        logger.warning("%s webhook: token no coincide", canal)
        return HttpResponse('forbidden', status=403)
    config.webhook_verificado_en = timezone.now()
    config.save(update_fields=['webhook_verificado_en'])
    return HttpResponse(challenge, content_type='text/plain', status=200)


def _resolver_config_por_payload(payload, ConfigCls, canal):
    """Identifica a qué ConfigInstagram/Messenger pertenece el evento."""
    try:
        for entry in payload.get('entry') or []:
            page_or_ig_id = entry.get('id')
            if canal == 'instagram':
                cfg = ConfigCls.objects.filter(
                    ig_user_id=page_or_ig_id
                ).select_related('sesion').first()
                if cfg:
                    return cfg
                cfg = ConfigCls.objects.filter(
                    page_id=page_or_ig_id
                ).select_related('sesion').first()
                if cfg:
                    return cfg
            else:
                cfg = ConfigCls.objects.filter(
                    page_id=page_or_ig_id
                ).select_related('sesion').first()
                if cfg:
                    return cfg
    except Exception:
        logger.exception("Error resolviendo config %s", canal)
    return None


def _procesar_post_social(request, ConfigCls, canal):
    raw_body = request.body
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    config = _resolver_config_por_payload(payload, ConfigCls, canal)
    sig = request.headers.get('X-Hub-Signature-256', '')
    secret = (config.app_secret if config else '') or ''
    firma_valida = _validar_hmac(raw_body, sig, secret)

    EventoMetaRecibido.objects.create(
        config_meta=None,
        tipo_evento=f'{canal}:{payload.get("object", "unknown")}',
        payload_json=payload,
        firma_valida=firma_valida,
        procesado=False,
    )

    if not firma_valida and secret:
        return JsonResponse({'ok': False, 'error': 'invalid_signature'}, status=401)
    if not config:
        return JsonResponse({'ok': True, 'warning': 'unknown_target'}, status=200)

    sesion: SesionWhatsApp = config.sesion
    channel_layer = get_channel_layer()

    try:
        for entry in payload.get('entry') or []:
            messaging_blocks = entry.get('messaging') or []
            for m in messaging_blocks:
                evento_interno = _social_a_evento_interno(m, canal)
                if evento_interno:
                    process_incoming_message(sesion, evento_interno, channel_layer)
            for m in entry.get('messages') or []:
                evento_interno = _social_a_evento_interno_v2(m, canal)
                if evento_interno:
                    process_incoming_message(sesion, evento_interno, channel_layer)
    except Exception as e:
        logger.exception("Error procesando %s webhook: %s", canal, e)
        _traza(
            etapa='error_general', sesion=sesion, nivel='error',
            detalle={f'{canal}_webhook_error': str(e)},
        )

    return JsonResponse({'ok': True}, status=200)


def _social_a_evento_interno(m: dict, canal: str) -> dict | None:
    """Traduce el shape `messaging` del legacy Messenger/IG al interno."""
    sender_id = (m.get('sender') or {}).get('id')
    if not sender_id:
        return None
    msg = m.get('message') or {}
    if msg.get('is_echo'):
        return None
    text = msg.get('text', '')
    referral = m.get('referral') or msg.get('referral') or {}

    evento = {
        'id':        msg.get('mid') or m.get('timestamp'),
        'from':      f"{sender_id}@s.whatsapp.net",
        'timestamp': int(m.get('timestamp', 0) // 1000) if m.get('timestamp') else None,
        'pushName':  '',
        'message':   {'conversation': text or ''},
        'fromMe':    False,
        'userImage': None,
        '_canal':    canal,
        '_external_id': sender_id,
    }
    if referral:
        evento['_referral'] = referral
    # Adjuntos
    for att in msg.get('attachments') or []:
        tipo = att.get('type', 'file')
        url = (att.get('payload') or {}).get('url')
        if url:
            evento['mediaData'] = {'url': url}
            evento['mediaType'] = {
                'image': 'imageMessage', 'video': 'videoMessage',
                'audio': 'audioMessage', 'file': 'documentMessage',
            }.get(tipo, 'documentMessage')
            evento['caption'] = text or tipo
            break
    return evento


def _social_a_evento_interno_v2(m: dict, canal: str) -> dict | None:
    """Algunos endpoints IG nuevos entregan en `entry[].messages[]` directamente."""
    sender_id = (m.get('from') or {}).get('id')
    if not sender_id:
        return None
    text = (m.get('text') or {}).get('body') or m.get('message', '')
    return {
        'id':        m.get('id'),
        'from':      f"{sender_id}@s.whatsapp.net",
        'timestamp': int(m.get('timestamp')) if m.get('timestamp') else None,
        'pushName':  '',
        'message':   {'conversation': text or ''},
        'fromMe':    False,
        'userImage': None,
        '_canal':    canal,
        '_external_id': sender_id,
    }
