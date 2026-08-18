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

Transacciones: el proyecto usa `ATOMIC_REQUESTS=True`, pero estas vistas se
excluyen con `transaction.non_atomic_requests` — un query fallido y silenciado
dentro del request dejaba la transacción de PostgreSQL abortada ("current
transaction is aborted") y el acceso posterior a la sesión devolvía 500 a Meta,
que dejaba de entregar mensajes. Cada entry se procesa en su propio
`transaction.atomic()` (rollback aislado) y la auditoría `EventoMetaRecibido`
en transacción aparte vía `crear_evento_log`/`guardar_evento_log`.
"""
from __future__ import annotations

import json
import logging

from django.db import transaction
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
from django.core.cache import cache

from .models import (
    ConfigInstagram,
    ConfigMessenger,
    Contacto,
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
@transaction.non_atomic_requests
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
@transaction.non_atomic_requests
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


def _resolver_config_por_entry(entry_id, ConfigCls, canal):
    """Identifica a qué ConfigInstagram/Messenger pertenece UN entry concreto.

    Meta agrupa en un mismo POST entries de páginas/cuentas de distintos
    tenants suscritas a la misma app. Resolver la config por-entry (y no una
    sola vez para todo el payload) evita que los mensajes de una empresa se
    procesen bajo la sesión de otra. Se filtra `sesion__status=True` para no
    atender sesiones eliminadas (soft-delete).
    """
    if not entry_id:
        return None
    try:
        if canal == 'instagram':
            cfg = ConfigCls.objects.filter(
                ig_user_id=entry_id, sesion__status=True
            ).select_related('sesion').first()
            if cfg:
                return cfg
            return ConfigCls.objects.filter(
                page_id=entry_id, sesion__status=True
            ).select_related('sesion').first()
        return ConfigCls.objects.filter(
            page_id=entry_id, sesion__status=True
        ).select_related('sesion').first()
    except Exception:
        logger.exception("Error resolviendo config %s", canal)
    return None


def crear_evento_log(tipo_evento, payload, firma_valida, **extra):
    """Crea el registro de auditoría `EventoMetaRecibido` en transacción propia.

    Si la escritura falla (tabla sin migrar, payload con caracteres inválidos
    para jsonb, etc.) se loguea y devuelve None: la auditoría nunca debe tumbar
    la respuesta al proveedor ni dejar la conexión con la transacción abortada.
    Compartido con el receiver TikTok (`tiktok/webhook_view.py`).
    """
    try:
        with transaction.atomic():
            return EventoMetaRecibido.objects.create(
                config_meta=None,
                tipo_evento=tipo_evento,
                payload_json=payload,
                firma_valida=firma_valida,
                procesado=False,
                **extra,
            )
    except Exception:
        logger.exception("No se pudo crear EventoMetaRecibido (%s)", tipo_evento)
        return None


def guardar_evento_log(evento_log, **campos):
    """Actualiza campos del registro de auditoría sin romper el request.

    Acepta None (cuando `crear_evento_log` falló) y aísla la escritura en su
    propia transacción por el mismo motivo que en la creación.
    """
    if evento_log is None:
        return
    try:
        with transaction.atomic():
            for campo, valor in campos.items():
                setattr(evento_log, campo, valor)
            evento_log.save(update_fields=list(campos))
    except Exception:
        logger.exception("No se pudo actualizar EventoMetaRecibido %s", evento_log.pk)


def _procesar_post_social(request, ConfigCls, canal):
    raw_body = request.body
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    sig = request.headers.get('X-Hub-Signature-256', '')
    from meta.credenciales import get_meta_app_secrets
    firma_valida = _validar_hmac(raw_body, sig, get_meta_app_secrets())

    # `object` es controlado por el emisor: truncar a la longitud del campo
    # evita un DataError 500 con valores largos.
    evento_log = crear_evento_log(
        f'{canal}:{payload.get("object", "unknown")}'[:50], payload, firma_valida,
    )

    # `_validar_hmac` devuelve True en modo permisivo sin secret; `not firma_valida`
    # cubre firma inválida con secret y secret ausente en modo estricto.
    if not firma_valida:
        guardar_evento_log(
            evento_log,
            error_procesamiento='Firma HMAC inválida (X-Hub-Signature-256 no coincide con app_secret).',
        )
        return JsonResponse({'ok': False, 'error': 'invalid_signature'}, status=401)

    channel_layer = get_channel_layer()
    hubo_config = False
    errores = []

    # Cada entry se resuelve a su propia config/sesión: un batch multi-página de
    # Meta puede mezclar tenants. El try + atomic por-entry aísla el fallo de un
    # entry (revierte sus escrituras parciales y deja la conexión limpia) para
    # no abortar el lote completo ni envenenar la transacción de PostgreSQL.
    for entry in payload.get('entry') or []:
        config = _resolver_config_por_entry(entry.get('id'), ConfigCls, canal)
        if not config:
            continue
        hubo_config = True
        sesion: SesionWhatsApp = config.sesion

        # Ids propios de la cuenta (page / ig_user): sirven para descartar los
        # "echoes" — Meta reentrega los mensajes que envía la propia cuenta; si
        # se procesan como entrantes, el bot terminaría respondiéndose a sí mismo.
        own_ids = set()
        for attr in ('ig_user_id', 'page_id'):
            val = getattr(config, attr, None)
            if val:
                own_ids.add(str(val))

        try:
            with transaction.atomic():
                for m in entry.get('messaging') or []:
                    for evento_interno in _social_a_eventos_internos(m, canal, own_ids):
                        _enriquecer_perfil_social(config, sesion, evento_interno, canal)
                        process_incoming_message(sesion, evento_interno, channel_layer)
                for m in entry.get('messages') or []:
                    evento_interno = _social_a_evento_interno_v2(m, canal, own_ids)
                    if evento_interno:
                        _enriquecer_perfil_social(config, sesion, evento_interno, canal)
                        process_incoming_message(sesion, evento_interno, channel_layer)
                for change in entry.get('changes') or []:
                    if canal == 'instagram' and change.get('field') == 'comments':
                        guardar_comentario_instagram(sesion, config, change.get('value') or {})
                    elif canal == 'messenger' and change.get('field') == 'feed':
                        guardar_comentario_facebook(sesion, config, change.get('value') or {})
        except Exception as e:
            logger.exception("Error procesando %s webhook (entry %s): %s", canal, entry.get('id'), e)
            errores.append(str(e)[:500])
            _traza(
                etapa='error_general', sesion=sesion, nivel='error',
                detalle={f'{canal}_webhook_error': str(e)},
            )

    if not hubo_config:
        guardar_evento_log(
            evento_log,
            error_procesamiento=f'Sin configuración {canal} que coincida con el destinatario del payload (unknown_target).',
        )
        return JsonResponse({'ok': True, 'warning': 'unknown_target'}, status=200)

    if errores:
        guardar_evento_log(evento_log, error_procesamiento=' | '.join(errores)[:2000])
    else:
        guardar_evento_log(evento_log, procesado=True)

    return JsonResponse({'ok': True}, status=200)


def _enriquecer_perfil_social(config, sesion, evento, canal):
    """Completa pushName/userImage del evento con el User Profile API de Meta.

    Los webhooks de Messenger/IG no traen nombre ni foto del usuario (solo el
    PSID/IGSID), así que sin esto el contacto queda con el id numérico como
    nombre. Solo pega a Graph cuando el contacto aún no tiene nombre o foto;
    el resultado (incluido el fallo, dict vacío) se cachea 6h por sender para
    no pegar a Graph en cada mensaje. `process_incoming_message` persiste
    pushName→contacto_nombre y userImage→contacto_foto (base64).
    """
    try:
        sender_id = evento.get('_external_id')
        if not sender_id or evento.get('fromMe'):
            return
        contacto = Contacto.objects.filter(
            sesion=sesion, from_number=evento.get('from')
        ).only('id', 'contacto_nombre', 'contacto_foto').first()
        tiene_nombre = bool(contacto and contacto.contacto_nombre)
        tiene_foto = bool(contacto and contacto.contacto_foto)
        if tiene_nombre and tiene_foto:
            return
        cache_key = f'perfil_social_v2_{canal}_{sender_id}'
        perfil = cache.get(cache_key)
        if perfil is None:
            from meta.perfiles import (
                obtener_perfil_usuario_instagram,
                obtener_perfil_usuario_messenger,
            )
            if canal == 'instagram':
                perfil = obtener_perfil_usuario_instagram(config, sender_id)
            else:
                perfil = obtener_perfil_usuario_messenger(config, sender_id)
            perfil = perfil or {}
            cache.set(cache_key, perfil, 6 * 3600)
            _traza(
                etapa='webhook_recibido', sesion=sesion, numero=str(sender_id),
                nivel='info' if perfil.get('ok') else 'warning',
                detalle={'perfil_social': canal,
                         'resultado': {k: v for k, v in perfil.items() if k != 'raw'} or 'sin_datos'},
            )
        if not (perfil and perfil.get('ok')):
            return
        if perfil.get('nombre') and not evento.get('pushName') and not tiene_nombre:
            evento['pushName'] = perfil['nombre']
        if perfil.get('foto') and not evento.get('userImage') and not tiene_foto:
            evento['userImage'] = perfil['foto']
    except Exception:
        logger.exception("Error enriqueciendo perfil %s de %s", canal, evento.get('_external_id'))


def _social_a_eventos_internos(m: dict, canal: str, own_ids=None) -> list:
    """Traduce el shape `messaging` del legacy Messenger/IG al interno.

    Devuelve una lista: un evento por adjunto (Messenger/IG permiten varios
    adjuntos en un mismo mensaje) o un único evento de texto. Antes se procesaba
    solo el primer adjunto y el resto se perdía en silencio.
    """
    sender_id = (m.get('sender') or {}).get('id')
    if not sender_id:
        return []
    # Eventos sin `message` (delivery, read, postback, reaction) no son mensajes
    # entrantes: descartarlos evita crear MensajeWhatsApp vacíos.
    if not m.get('message'):
        return []
    msg = m.get('message') or {}
    if msg.get('is_echo'):
        return []
    # Echo/self: el emisor es la propia cuenta (page/ig_user).
    if own_ids and str(sender_id) in own_ids:
        return []
    text = msg.get('text', '')
    referral = m.get('referral') or msg.get('referral') or {}
    base_id = msg.get('mid') or m.get('timestamp')

    def _nuevo_evento(evento_id):
        evento = {
            'id':        evento_id,
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
        return evento

    adjuntos = [a for a in (msg.get('attachments') or []) if (a.get('payload') or {}).get('url')]
    if not adjuntos:
        return [_nuevo_evento(base_id)]

    eventos = []
    for idx, att in enumerate(adjuntos):
        tipo = att.get('type', 'file')
        url = (att.get('payload') or {}).get('url')
        # id único por adjunto para no colisionar en la deduplicación aguas abajo.
        evento = _nuevo_evento(f'{base_id}_{idx}' if idx else base_id)
        # El texto acompaña solo al primer adjunto.
        if idx:
            evento['message'] = {'conversation': ''}
        evento['mediaData'] = {'url': url}
        evento['mediaType'] = {
            'image': 'imageMessage', 'video': 'videoMessage',
            'audio': 'audioMessage', 'file': 'documentMessage',
        }.get(tipo, 'documentMessage')
        evento['caption'] = (text or tipo) if idx == 0 else tipo
        eventos.append(evento)
    return eventos


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
