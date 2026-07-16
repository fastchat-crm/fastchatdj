"""Receiver del webhook TikTok Business Messaging.

Vive en la app `tiktok` (cada red social expone su webhook bajo su propia URL:
`/tiktok/webhook/`). Valida el evento, lo traduce al shape interno y delega en
`whatsapp.procesar_mensaje.process_incoming_message`, con lo que el DM entra al
pipeline compartido (Contacto, Conversación, IA, asignación, WebSockets).

Estado: la API está en beta — el shape exacto del payload puede requerir ajuste
al probar contra el sandbox real de TikTok. La verificación GET responde el
`challenge` si el verify token coincide con alguna ConfigTikTok.

URL canónica: /tiktok/webhook/
Alias legacy (compat): /whatsapp/tiktok_webhook/
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

from whatsapp.models import ConfigTikTok, EventoMetaRecibido, SesionWhatsApp
from whatsapp.procesar_mensaje import process_incoming_message

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
    # Exigir verify_token válido antes de responder el challenge: sin esto,
    # cualquiera podía completar la verificación del endpoint sin conocer token.
    if not token:
        return HttpResponse('missing_verify_token', content_type='text/plain', status=400)
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
            business_id=valor, sesion__status=True
        ).select_related('sesion').first()
        if cfg:
            return cfg
        cfg = ConfigTikTok.objects.filter(
            open_id=valor, sesion__status=True
        ).select_related('sesion').first()
        if cfg:
            return cfg
    return None


def _firma_valida_tiktok(request, config):
    """Valida la firma HMAC-SHA256 del webhook TikTok contra `client_secret`.

    Devuelve (valida: bool, verificable: bool):
      - verificable=False cuando no hay secreto configurado (beta): no se puede
        verificar; el caller decide (hoy: procesa con traza, no rechaza para no
        romper el sandbox). Configura `client_secret` para volverlo fail-closed.
    """
    secret = (getattr(config, 'client_secret', '') or '').strip() if config else ''
    if not secret:
        return False, False
    firma = (
        request.META.get('HTTP_TIKTOK_SIGNATURE')
        or request.META.get('HTTP_X_TIKTOK_SIGNATURE')
        or request.headers.get('Tiktok-Signature')
        or ''
    ).strip()
    if not firma:
        return False, True
    if firma.startswith('sha256='):
        firma = firma.split('=', 1)[1]
    esperado = hmac.new(secret.encode('utf-8'), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, firma), True


def _procesar_post(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    config = _resolver_config(payload)
    firma_ok, verificable = _firma_valida_tiktok(request, config)

    from django.conf import settings
    fail_closed = getattr(settings, 'META_WEBHOOK_FAIL_CLOSED', True)
    tipo_evento = f"tiktok:{payload.get('event', payload.get('type', 'unknown'))}"[:50]

    # Rechazar si la firma es verificable e inválida, o si no es verificable
    # (ConfigTikTok sin client_secret) y estamos en modo fail-closed (default).
    # Igual que el webhook Meta: no se procesan eventos sin autenticar.
    if (verificable and not firma_ok) or (not verificable and fail_closed):
        motivo = 'firma_hmac_invalida' if verificable else 'sin_client_secret_fail_closed'
        logger.warning("tiktok webhook: evento rechazado (%s)", motivo)
        EventoMetaRecibido.objects.create(
            config_meta=None,
            tipo_evento=tipo_evento,
            payload_json=payload,
            firma_valida=False,
            procesado=False,
            error_procesamiento=motivo,
        )
        return JsonResponse({'error': 'invalid_signature'}, status=401)

    evento_log = EventoMetaRecibido.objects.create(
        config_meta=None,
        tipo_evento=tipo_evento,
        payload_json=payload,
        firma_valida=firma_ok,
        procesado=False,
    )
    if not verificable:
        evento_log.error_procesamiento = 'firma_no_verificada (ConfigTikTok sin client_secret)'
        evento_log.save(update_fields=['error_procesamiento'])

    if not config:
        evento_log.error_procesamiento = 'Sin ConfigTikTok que coincida con business_id/open_id del payload (unknown_target).'
        evento_log.save(update_fields=['error_procesamiento'])
        return JsonResponse({'ok': True, 'warning': 'unknown_target'}, status=200)

    sesion: SesionWhatsApp = config.sesion
    channel_layer = get_channel_layer()

    # Ids propios del negocio: descartan echos (eventos del propio negocio que
    # TikTok reentrega), evitando que el bot se responda a sí mismo.
    own_ids = set()
    for attr in ('open_id', 'business_id'):
        val = getattr(config, attr, None)
        if val:
            own_ids.add(str(val))

    errores = []
    eventos = payload.get('events') or [payload]
    for evento in eventos:
        # try por-evento: un evento malformado no debe abortar el resto del lote.
        try:
            interno = _a_evento_interno(evento, own_ids)
            if interno:
                process_incoming_message(sesion, interno, channel_layer)
        except Exception as e:
            logger.exception("Error procesando evento tiktok: %s", e)
            errores.append(str(e)[:500])

    if errores:
        evento_log.error_procesamiento = ' | '.join(errores)[:2000]
        evento_log.save(update_fields=['error_procesamiento'])
    else:
        evento_log.procesado = True
        evento_log.save(update_fields=['procesado'])

    return JsonResponse({'ok': True}, status=200)


def _a_evento_interno(evento: dict, own_ids=None) -> dict | None:
    """Traduce un evento de mensaje TikTok al shape interno del pipeline."""
    msg = evento.get('message') or evento
    sender = (evento.get('from') or evento.get('sender') or {})
    sender_id = sender.get('open_id') or sender.get('id') or evento.get('from_open_id')
    if not sender_id:
        return None
    # Echo/self: el emisor es el propio negocio o el evento viene marcado echo.
    if evento.get('is_echo') or msg.get('is_echo'):
        return None
    if own_ids and str(sender_id) in own_ids:
        return None
    texto = ''
    if isinstance(msg.get('text'), dict):
        texto = msg['text'].get('body') or ''
    elif isinstance(msg.get('text'), str):
        texto = msg['text']
    elif msg.get('content'):
        texto = str(msg['content'])
    try:
        ts = int(float(evento['timestamp'])) if evento.get('timestamp') else None
    except (TypeError, ValueError):
        ts = None
    return {
        'id':        msg.get('message_id') or msg.get('id') or evento.get('event_id'),
        'from':      f"{sender_id}@s.whatsapp.net",
        'timestamp': ts,
        'pushName':  sender.get('nickname') or '',
        'message':   {'conversation': texto or ''},
        'fromMe':    False,
        'userImage': sender.get('avatar') or None,
        '_canal':    'tiktok',
        '_external_id': str(sender_id),
    }
