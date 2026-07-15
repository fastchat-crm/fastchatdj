"""Receivers de webhooks Instagram DM y Messenger.

Comparten estructura con `meta_webhook_view.py`:
  - GET → handshake con `hub.verify_token`.
  - POST → eventos firmados con HMAC-SHA256 contra `app_secret`.

El payload Meta (page) trae mensajes en `entry[].messaging[]` (legacy) o en
`entry[].messages[]` para IG. Lo traducimos al shape interno y reusamos
`process_incoming_message` igual que el receiver de WhatsApp Cloud.

Implementación compartida. Cada red la expone bajo su propia app/URL:
  Instagram DM  → /instagram/webhook/  (instagram.webhook_view)
  Messenger     → /facebook/webhook/   (facebook.webhook_view)

Alias legacy (compat, dashboards ya configurados):
  /whatsapp/instagram_webhook/
  /whatsapp/messenger_webhook/
"""
from __future__ import annotations

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from channels.layers import get_channel_layer

from .common_meta import validar_firma_hmac as _validar_hmac_shared
from .funciones_comentarios import (
    guardar_comentario_facebook,
    guardar_comentario_instagram,
)
from .models import (
    ConfigInstagram,
    ConfigMessenger,
    EventoMetaRecibido,
    SesionWhatsApp,
)
from .procesar_mensaje import process_incoming_message
from .trazas import registrar as _traza

logger = logging.getLogger(__name__)


def _validar_hmac(raw_body: bytes, sig_header: str, secret: str) -> bool:
    # Delega en el helper compartido con meta_webhook_view para que haya una
    # sola implementacion de HMAC-SHA256 en todo el proyecto.
    return _validar_hmac_shared(raw_body, sig_header, secret)


def _cliente_espera_html(request) -> bool:
    return 'text/html' in (request.META.get('HTTP_ACCEPT') or '').lower()


def _render_info(request, proveedor: str, emoji: str, ConfigCls,
                 estado: str = 'landing', status_code: int = 200):
    try:
        from .common_meta import get_meta_app_secret
        total = ConfigCls.objects.count()
        verificados = ConfigCls.objects.exclude(webhook_verificado_en__isnull=True).count()
        with_app_secret = total if get_meta_app_secret() else 0
    except Exception:
        total = verificados = with_app_secret = 0
    ctx = {
        'estado':            estado,
        'proveedor':         proveedor,
        'emoji':             emoji,
        'total_configs':     total,
        'verificados':       verificados,
        'sin_verificar':     max(total - verificados, 0),
        'with_app_secret':   with_app_secret,
        'eventos_total':     0,
        'eventos_procesados': 0,
        'eventos_con_error':  0,
        'ultimos_eventos':   [],
        'webhook_url':       request.build_absolute_uri(request.path),
        'metodo':            request.method,
        'ahora':             timezone.now(),
        'ua_resumido':       (request.META.get('HTTP_USER_AGENT') or '')[:120],
        'query_string':      request.META.get('QUERY_STRING') or '',
    }
    return render(request, 'whatsapp/meta_webhook_info.html', ctx, status=status_code)


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

@csrf_exempt
def instagram_webhook(request):
    if request.method == 'GET':
        return _handshake_generico(request, ConfigInstagram, 'instagram', '📷')
    if request.method == 'POST':
        return _procesar_post_social(request, ConfigInstagram, 'instagram')
    if _cliente_espera_html(request):
        return _render_info(request, 'Instagram DM', '📷', ConfigInstagram,
                            estado='metodo_no_permitido', status_code=405)
    return JsonResponse({'error': 'method_not_allowed'}, status=405)


# ---------------------------------------------------------------------------
# Messenger
# ---------------------------------------------------------------------------

@csrf_exempt
def messenger_webhook(request):
    if request.method == 'GET':
        return _handshake_generico(request, ConfigMessenger, 'messenger', '💬')
    if request.method == 'POST':
        return _procesar_post_social(request, ConfigMessenger, 'messenger')
    if _cliente_espera_html(request):
        return _render_info(request, 'Facebook Messenger', '💬', ConfigMessenger,
                            estado='metodo_no_permitido', status_code=405)
    return JsonResponse({'error': 'method_not_allowed'}, status=405)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handshake_generico(request, ConfigCls, canal, emoji):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    # Sin `hub.challenge` no es Meta haciendo el handshake → alguien probando
    # la URL desde el navegador. Renderizamos la landing informativa igual que
    # en meta_webhook.
    if not (mode and challenge is not None):
        proveedor_label = 'Instagram DM' if canal == 'instagram' else 'Facebook Messenger'
        return _render_info(request, proveedor_label, emoji, ConfigCls, estado='landing')

    if mode != 'subscribe':
        return HttpResponse('invalid_mode', content_type='text/plain', status=400)
    if not token:
        return HttpResponse('missing_verify_token', content_type='text/plain', status=400)

    config = ConfigCls.objects.filter(webhook_verify_token=token).first()
    if not config:
        logger.warning("%s webhook: token no coincide (prefix=%s)", canal, (token or '')[:8])
        return HttpResponse('forbidden', content_type='text/plain', status=403)
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
    from .common_meta import get_meta_app_secret
    secret = get_meta_app_secret()
    firma_valida = _validar_hmac(raw_body, sig, secret)

    evento_log = EventoMetaRecibido.objects.create(
        config_meta=None,
        tipo_evento=f'{canal}:{payload.get("object", "unknown")}',
        payload_json=payload,
        firma_valida=firma_valida,
        procesado=False,
    )

    if not firma_valida and secret:
        evento_log.error_procesamiento = 'Firma HMAC inválida (X-Hub-Signature-256 no coincide con app_secret).'
        evento_log.save(update_fields=['error_procesamiento'])
        return JsonResponse({'ok': False, 'error': 'invalid_signature'}, status=401)
    if not config:
        evento_log.error_procesamiento = f'Sin configuración {canal} que coincida con el destinatario del payload (unknown_target).'
        evento_log.save(update_fields=['error_procesamiento'])
        return JsonResponse({'ok': True, 'warning': 'unknown_target'}, status=200)

    sesion: SesionWhatsApp = config.sesion
    channel_layer = get_channel_layer()

    # Ids propios de la cuenta (page / ig_user): sirven para descartar los
    # "echoes" — Meta reentrega los mensajes que envía la propia cuenta; si se
    # procesan como entrantes, el bot terminaría respondiéndose a sí mismo.
    own_ids = set()
    for attr in ('ig_user_id', 'page_id'):
        val = getattr(config, attr, None)
        if val:
            own_ids.add(str(val))

    try:
        for entry in payload.get('entry') or []:
            messaging_blocks = entry.get('messaging') or []
            for m in messaging_blocks:
                evento_interno = _social_a_evento_interno(m, canal, own_ids)
                if evento_interno:
                    process_incoming_message(sesion, evento_interno, channel_layer)
            for m in entry.get('messages') or []:
                evento_interno = _social_a_evento_interno_v2(m, canal, own_ids)
                if evento_interno:
                    process_incoming_message(sesion, evento_interno, channel_layer)
            for change in entry.get('changes') or []:
                if canal == 'instagram' and change.get('field') == 'comments':
                    guardar_comentario_instagram(sesion, config, change.get('value') or {})
                elif canal == 'messenger' and change.get('field') == 'feed':
                    guardar_comentario_facebook(sesion, config, change.get('value') or {})
        evento_log.procesado = True
        evento_log.save(update_fields=['procesado'])
    except Exception as e:
        logger.exception("Error procesando %s webhook: %s", canal, e)
        evento_log.error_procesamiento = str(e)[:2000]
        evento_log.save(update_fields=['error_procesamiento'])
        _traza(
            etapa='error_general', sesion=sesion, nivel='error',
            detalle={f'{canal}_webhook_error': str(e)},
        )

    return JsonResponse({'ok': True}, status=200)


def _social_a_evento_interno(m: dict, canal: str, own_ids=None) -> dict | None:
    """Traduce el shape `messaging` del legacy Messenger/IG al interno."""
    sender_id = (m.get('sender') or {}).get('id')
    if not sender_id:
        return None
    msg = m.get('message') or {}
    if msg.get('is_echo'):
        return None
    # Echo/self: el emisor es la propia cuenta (page/ig_user).
    if own_ids and str(sender_id) in own_ids:
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


def _social_a_evento_interno_v2(m: dict, canal: str, own_ids=None) -> dict | None:
    """Algunos endpoints IG nuevos entregan en `entry[].messages[]` directamente."""
    sender_id = (m.get('from') or {}).get('id')
    if not sender_id:
        return None
    # Echo/self: descartar mensajes emitidos por la propia cuenta o marcados echo.
    if m.get('is_echo'):
        return None
    if own_ids and str(sender_id) in own_ids:
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
