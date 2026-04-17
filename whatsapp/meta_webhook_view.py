"""Receiver de webhooks Meta Cloud API.

Meta hace dos cosas contra este endpoint:

1. **GET (handshake de verificacion)** — una sola vez al configurar el webhook
   en el panel de Meta. Llega con `hub.mode`, `hub.verify_token`, `hub.challenge`.
   Debemos devolver el `hub.challenge` tal cual si el verify_token coincide con
   `ConfigMeta.webhook_verify_token`.

2. **POST (evento)** — cada vez que algo pasa en WhatsApp (mensaje entrante,
   status de mensaje, cambio de plantilla, etc.). El body viene firmado con
   HMAC-SHA256 en el header `X-Hub-Signature-256` usando `ConfigMeta.app_secret`.

Despues de validar, traducimos el payload Meta al formato interno que ya
entiende `process_incoming_message` (existente, usado por Baileys) y llamamos
la misma funcion — asi todo el pipeline IA / trazas / crons reusa codigo.

URL: /whatsapp/meta_webhook/
"""
import hashlib
import hmac
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from channels.layers import get_channel_layer

from .models import ConfigMeta, EventoMetaRecibido, SesionWhatsApp
from .view_webhook_handler import process_incoming_message
from .trazas import registrar as _traza

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@csrf_exempt
def meta_webhook(request):
    if request.method == 'GET':
        return _verificar_webhook(request)
    if request.method == 'POST':
        return _procesar_evento(request)
    return HttpResponse(status=405)


# ---------------------------------------------------------------------------
# Handshake (GET)
# ---------------------------------------------------------------------------

def _verificar_webhook(request):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge', '')

    if mode != 'subscribe' or not token:
        return HttpResponse('bad_request', status=400)

    config = ConfigMeta.objects.filter(webhook_verify_token=token).first()
    if not config:
        logger.warning("Meta webhook verify: token no coincide con ninguna ConfigMeta")
        return HttpResponse('forbidden', status=403)

    config.webhook_verificado_en = timezone.now()
    config.save(update_fields=['webhook_verificado_en'])

    logger.info("Meta webhook verificado para ConfigMeta id=%s (WABA %s)",
                config.id, config.waba_id)
    return HttpResponse(challenge, content_type='text/plain', status=200)


# ---------------------------------------------------------------------------
# Evento (POST)
# ---------------------------------------------------------------------------

def _procesar_evento(request):
    raw_body = request.body
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    signature = request.headers.get('X-Hub-Signature-256', '') or request.META.get('HTTP_X_HUB_SIGNATURE_256', '')
    phone_number_id = _extraer_phone_number_id(payload)
    config = ConfigMeta.objects.filter(phone_number_id=phone_number_id).first() if phone_number_id else None

    firma_valida = _validar_firma_hmac(raw_body, signature, config)

    evento = EventoMetaRecibido.objects.create(
        config_meta=config,
        tipo_evento=_extraer_tipo_evento(payload),
        payload_json=payload,
        firma_valida=firma_valida,
        procesado=False,
    )

    if not firma_valida and config and config.app_secret:
        evento.error_procesamiento = 'firma_hmac_invalida'
        evento.save(update_fields=['error_procesamiento'])
        logger.warning("Meta webhook: firma HMAC invalida para phone_number_id=%s", phone_number_id)
        return JsonResponse({'ok': False, 'error': 'invalid_signature'}, status=401)

    if not config:
        evento.error_procesamiento = 'config_meta_no_encontrada'
        evento.save(update_fields=['error_procesamiento'])
        logger.warning("Meta webhook: no se encontro ConfigMeta para phone_number_id=%s", phone_number_id)
        return JsonResponse({'ok': True, 'warning': 'unknown_phone'}, status=200)

    try:
        _enrutar_payload(payload, config, evento)
        evento.procesado = True
        evento.save(update_fields=['procesado'])
    except Exception as e:
        logger.exception("Meta webhook: error procesando evento id=%s: %s", evento.id, e)
        evento.error_procesamiento = str(e)[:1000]
        evento.save(update_fields=['error_procesamiento'])
        # Respondemos 200 de todos modos para que Meta no reintente hasta el infinito
        # por un bug nuestro. El evento queda en la tabla para reproceso manual.

    return JsonResponse({'ok': True}, status=200)


# ---------------------------------------------------------------------------
# Validacion HMAC
# ---------------------------------------------------------------------------

def _validar_firma_hmac(raw_body: bytes, signature_header: str, config: ConfigMeta) -> bool:
    """Compara X-Hub-Signature-256 contra HMAC(app_secret, body).
    Si no hay config.app_secret devuelve True (modo permisivo para setup inicial)."""
    if not config or not config.app_secret:
        return True  # sin app_secret no podemos validar, dejamos pasar con warning
    if not signature_header:
        return False
    try:
        expected = 'sha256=' + hmac.new(
            config.app_secret.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)
    except Exception:
        logger.exception("Error computando HMAC")
        return False


# ---------------------------------------------------------------------------
# Extractores del payload Meta
# ---------------------------------------------------------------------------

def _extraer_phone_number_id(payload: dict) -> str | None:
    try:
        entries = payload.get('entry') or []
        for entry in entries:
            for change in entry.get('changes') or []:
                meta = (change.get('value') or {}).get('metadata') or {}
                if meta.get('phone_number_id'):
                    return meta['phone_number_id']
    except Exception:
        pass
    return None


def _extraer_tipo_evento(payload: dict) -> str:
    try:
        entries = payload.get('entry') or []
        if entries:
            changes = entries[0].get('changes') or []
            if changes:
                return changes[0].get('field') or 'unknown'
    except Exception:
        pass
    return 'unknown'


# ---------------------------------------------------------------------------
# Enrutamiento por tipo de evento
# ---------------------------------------------------------------------------

def _enrutar_payload(payload: dict, config: ConfigMeta, evento: EventoMetaRecibido):
    channel_layer = get_channel_layer()
    sesion = config.sesion

    for entry in payload.get('entry') or []:
        for change in entry.get('changes') or []:
            field = change.get('field')
            value = change.get('value') or {}

            if field == 'messages':
                # Meta agrupa: 'messages' (entrantes) y 'statuses' (ACK) en el mismo change.
                for msg_meta in value.get('messages') or []:
                    evento_interno = _meta_a_evento_interno(msg_meta, value, sesion)
                    if evento_interno:
                        process_incoming_message(sesion, evento_interno, channel_layer)

                for status_meta in value.get('statuses') or []:
                    _procesar_status_meta(status_meta, sesion, evento)

            elif field == 'message_template_status_update':
                _procesar_cambio_plantilla(value, config)

            else:
                logger.info("Meta webhook field no manejado: %s", field)
                _traza(
                    etapa='webhook_recibido', sesion=sesion, nivel='info',
                    detalle={'meta_field_no_manejado': field, 'value_preview': str(value)[:300]},
                )


# ---------------------------------------------------------------------------
# Traductor Meta → formato interno (el que espera process_incoming_message)
# ---------------------------------------------------------------------------

def _meta_a_evento_interno(msg_meta: dict, value: dict, sesion: SesionWhatsApp) -> dict | None:
    """Convierte un mensaje entrante en formato Meta al shape que
    process_incoming_message (view_webhook_handler) espera, originalmente
    disenado para Baileys."""
    try:
        from_num = msg_meta.get('from', '')
        if not from_num:
            return None

        # Meta entrega el numero plano "593..."; internamente lo normalizamos a
        # "593...@s.whatsapp.net" para mantener compatibilidad con el resto del
        # pipeline que ya asume ese formato.
        if '@' not in from_num:
            from_num_fmt = f"{from_num}@s.whatsapp.net"
        else:
            from_num_fmt = from_num

        push_name = ''
        for contacto in value.get('contacts') or []:
            if contacto.get('wa_id') and from_num.endswith(contacto['wa_id']):
                push_name = (contacto.get('profile') or {}).get('name') or ''
                break

        ts = msg_meta.get('timestamp')
        try:
            ts = int(ts) if ts else None
        except Exception:
            ts = None

        tipo_meta = msg_meta.get('type')
        message_content: dict = {}
        media_type = None
        media_data = None
        filename = None
        caption = ''

        if tipo_meta == 'text':
            texto = (msg_meta.get('text') or {}).get('body', '')
            message_content = {'conversation': texto}

        elif tipo_meta == 'interactive':
            # Respuesta a botones o listas — la guardamos como texto plano
            interactive = msg_meta.get('interactive') or {}
            kind = interactive.get('type')
            texto_boton = ''
            if kind == 'button_reply':
                texto_boton = (interactive.get('button_reply') or {}).get('title', '')
            elif kind == 'list_reply':
                texto_boton = (interactive.get('list_reply') or {}).get('title', '')
            message_content = {'conversation': texto_boton}

        elif tipo_meta in ('image', 'video', 'audio', 'document', 'sticker'):
            media_type_map = {
                'image':    'imageMessage',
                'video':    'videoMessage',
                'audio':    'audioMessage',
                'document': 'documentMessage',
                'sticker':  'stickerMessage',
            }
            media_type = media_type_map[tipo_meta]
            media_obj = msg_meta.get(tipo_meta) or {}
            caption = media_obj.get('caption', '')
            filename = media_obj.get('filename')
            # Meta entrega un media_id; habra que descargarlo via Graph API.
            # Aqui pasamos el id crudo en mediaData para que el fetcher lo resuelva.
            media_data = {'meta_media_id': media_obj.get('id'), 'mime_type': media_obj.get('mime_type')}
            message_content = {media_type: media_obj}

        elif tipo_meta == 'location':
            loc = msg_meta.get('location') or {}
            texto = f"Ubicacion: {loc.get('latitude')}, {loc.get('longitude')}"
            if loc.get('name'):
                texto = f"{loc['name']} — {texto}"
            message_content = {'conversation': texto}

        else:
            logger.info("Meta: tipo de mensaje no soportado aun: %s", tipo_meta)
            message_content = {'conversation': f"[Mensaje tipo '{tipo_meta}' no soportado]"}

        # Shape compatible con Baileys/process_incoming_message
        evento_interno = {
            'id': msg_meta.get('id'),
            'from': from_num_fmt,
            'timestamp': ts,
            'pushName': push_name,
            'message': message_content,
            'fromMe': False,
            'userImage': None,
        }
        if media_type:
            evento_interno['mediaType'] = media_type
        if caption:
            evento_interno['caption'] = caption
        if filename:
            evento_interno['fileName'] = filename
        if media_data:
            evento_interno['mediaData'] = media_data

        return evento_interno

    except Exception:
        logger.exception("Error traduciendo mensaje Meta a formato interno")
        return None


# ---------------------------------------------------------------------------
# Status / ACK (message_ack equivalent)
# ---------------------------------------------------------------------------

def _procesar_status_meta(status: dict, sesion: SesionWhatsApp, evento: EventoMetaRecibido):
    """Meta envia statuses con fases: sent, delivered, read, failed. Por ahora
    solo lo logueamos — si el CRM necesita actualizar el MensajeWhatsApp
    correspondiente (por mensaje_id_externo), se implementa aqui."""
    mid = status.get('id')
    estado = status.get('status')
    logger.info("Meta status: msg=%s estado=%s sesion=%s", mid, estado, sesion.id)
    _traza(
        etapa='mensaje_enviado' if estado == 'sent' else 'webhook_recibido',
        sesion=sesion, nivel='info',
        detalle={'meta_status': estado, 'mensaje_id_externo': mid},
    )


# ---------------------------------------------------------------------------
# Cambios de estado de plantillas (APPROVED / REJECTED / etc.)
# ---------------------------------------------------------------------------

def _procesar_cambio_plantilla(value: dict, config: ConfigMeta):
    """Meta notifica cuando una plantilla cambia de estado. Actualizamos
    PlantillaWhatsApp.estado_meta."""
    from .models import PlantillaWhatsApp

    nombre = value.get('message_template_name')
    idioma = value.get('message_template_language') or 'es'
    nuevo_estado = value.get('event') or value.get('new_status')  # API cambia nombres
    motivo = value.get('reason')

    if not nombre or not nuevo_estado:
        return

    plantilla = PlantillaWhatsApp.objects.filter(
        config_meta=config, nombre=nombre, idioma=idioma
    ).first()
    if not plantilla:
        logger.info("Meta: cambio de estado para plantilla desconocida %s (%s)", nombre, idioma)
        return

    estado_map = {
        'APPROVED':             'APPROVED',
        'REJECTED':             'REJECTED',
        'PENDING':              'PENDING',
        'PAUSED':               'PAUSED',
        'DISABLED':             'DISABLED',
        'FLAGGED':              'PAUSED',
        'PENDING_DELETION':     'DISABLED',
    }
    plantilla.estado_meta = estado_map.get(nuevo_estado.upper(), plantilla.estado_meta)
    if plantilla.estado_meta == 'APPROVED' and not plantilla.fecha_aprobacion:
        plantilla.fecha_aprobacion = timezone.now()
    if motivo:
        plantilla.motivo_rechazo = motivo
    plantilla.ultima_sincronizacion = timezone.now()
    plantilla.save(update_fields=[
        'estado_meta', 'fecha_aprobacion', 'motivo_rechazo', 'ultima_sincronizacion'
    ])
    logger.info("Plantilla %s (%s) → %s", nombre, idioma, plantilla.estado_meta)
