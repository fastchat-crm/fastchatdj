"""Receiver del webhook TikTok Business Messaging.

Espejo de `meta_social_webhook_view.py`: valida el evento, lo traduce al shape
interno y delega en `process_incoming_message`, con lo que el DM entra al
pipeline compartido (Contacto, Conversación, IA, asignación, WebSockets).

Estado: la API está en beta — el shape exacto del payload puede requerir
ajuste al probar contra el sandbox real de TikTok. La verificación GET
responde el `challenge` si el verify token coincide con alguna ConfigTikTok.

URL: /whatsapp/tiktok_webhook/
"""
from __future__ import annotations

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from channels.layers import get_channel_layer

from .models import ConfigTikTok, EventoMetaRecibido, SesionWhatsApp
from .procesar_mensaje import process_incoming_message

logger = logging.getLogger(__name__)


@csrf_exempt
def tiktok_webhook(request):
    if request.method == 'GET':
        return _handshake(request)
    if request.method == 'POST':
        return _procesar_post(request)
    return JsonResponse({'error': 'method_not_allowed'}, status=405)


def _handshake(request):
    challenge = request.GET.get('challenge') or request.GET.get('hub.challenge')
    token = (request.GET.get('verify_token')
             or request.GET.get('hub.verify_token') or '')
    if challenge is None:
        return JsonResponse({'ok': True, 'canal': 'tiktok', 'estado': 'landing'})
    if token:
        config = ConfigTikTok.objects.filter(webhook_verify_token=token).first()
        if not config:
            logger.warning("tiktok webhook: verify token no coincide (prefix=%s)", token[:8])
            return HttpResponse('forbidden', content_type='text/plain', status=403)
        config.webhook_verificado_en = timezone.now()
        config.save(update_fields=['webhook_verificado_en'])
    return HttpResponse(challenge, content_type='text/plain', status=200)


def _resolver_config(payload):
    """Ubica la ConfigTikTok dueña del evento por business_id / open_id."""
    posibles = []
    for clave in ('business_id', 'to_business_id', 'recipient_id'):
        valor = payload.get(clave)
        if valor:
            posibles.append(str(valor))
    for evento in payload.get('events') or []:
        for clave in ('business_id', 'to_business_id', 'recipient_id'):
            valor = evento.get(clave)
            if valor:
                posibles.append(str(valor))
    for valor in posibles:
        cfg = ConfigTikTok.objects.filter(
            business_id=valor
        ).select_related('sesion').first()
        if cfg:
            return cfg
        cfg = ConfigTikTok.objects.filter(
            open_id=valor
        ).select_related('sesion').first()
        if cfg:
            return cfg
    return None


def _procesar_post(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    EventoMetaRecibido.objects.create(
        config_meta=None,
        tipo_evento=f"tiktok:{payload.get('event', payload.get('type', 'unknown'))}",
        payload_json=payload,
        firma_valida=True,
        procesado=False,
    )

    config = _resolver_config(payload)
    if not config:
        return JsonResponse({'ok': True, 'warning': 'unknown_target'}, status=200)

    sesion: SesionWhatsApp = config.sesion
    channel_layer = get_channel_layer()

    try:
        eventos = payload.get('events') or [payload]
        for evento in eventos:
            interno = _a_evento_interno(evento)
            if interno:
                process_incoming_message(sesion, interno, channel_layer)
    except Exception as e:
        logger.exception("Error procesando tiktok webhook: %s", e)

    return JsonResponse({'ok': True}, status=200)


def _a_evento_interno(evento: dict) -> dict | None:
    """Traduce un evento de mensaje TikTok al shape interno del pipeline."""
    msg = evento.get('message') or evento
    sender = (evento.get('from') or evento.get('sender') or {})
    sender_id = sender.get('open_id') or sender.get('id') or evento.get('from_open_id')
    if not sender_id:
        return None
    texto = ''
    if isinstance(msg.get('text'), dict):
        texto = msg['text'].get('body') or ''
    elif isinstance(msg.get('text'), str):
        texto = msg['text']
    elif msg.get('content'):
        texto = str(msg['content'])
    return {
        'id':        msg.get('message_id') or msg.get('id') or evento.get('event_id'),
        'from':      f"{sender_id}@s.whatsapp.net",
        'timestamp': int(evento['timestamp']) if evento.get('timestamp') else None,
        'pushName':  sender.get('nickname') or '',
        'message':   {'conversation': texto or ''},
        'fromMe':    False,
        'userImage': sender.get('avatar') or None,
        '_canal':    'tiktok',
        '_external_id': str(sender_id),
    }
