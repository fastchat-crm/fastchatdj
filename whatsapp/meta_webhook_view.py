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

Si alguien accede con un navegador o curl (sin los params de handshake),
renderizamos una pagina HTML informativa — util para el dev que prueba la URL.

URL: /whatsapp/meta_webhook/
"""
import hashlib
import hmac
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from channels.layers import get_channel_layer

from .models import ConfigMeta, EventoMetaRecibido, MetaWebhookHit, SesionWhatsApp
from .procesar_mensaje import process_incoming_message
from .trazas import registrar as _traza


def _log_hit(request, status_code: int, nota: str = ''):
    """Registra el hit HTTP en MetaWebhookHit. Best-effort — nunca rompe el
    flujo del webhook si la BD esta caida."""
    try:
        body = request.body or b''
        try:
            body_preview = body.decode('utf-8', errors='replace')[:600]
        except Exception:
            body_preview = repr(body[:300])
        ip = (
            request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            or request.META.get('REMOTE_ADDR', '')
            or ''
        )
        sig = (
            request.META.get('HTTP_X_HUB_SIGNATURE_256')
            or request.headers.get('X-Hub-Signature-256', '')
        )
        MetaWebhookHit.objects.create(
            method=(request.method or '')[:10],
            status_code=status_code,
            ip=ip[:64],
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:256],
            query_string=(request.META.get('QUERY_STRING') or '')[:512],
            signature_presente=bool(sig),
            body_length=len(body),
            body_preview=body_preview,
            nota=(nota or '')[:200],
        )
    except Exception:
        logger.exception("MetaWebhookHit: fallo registrando hit (ignorando)")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@csrf_exempt
def meta_webhook(request):
    response = None
    nota = ''
    if request.method == 'GET':
        response = _verificar_webhook(request)
        nota = 'handshake' if request.GET.get('hub.challenge') else 'browser_landing'
    elif request.method == 'POST':
        response = _procesar_evento(request)
        nota = 'evento_post'
    else:
        if _cliente_espera_html(request):
            response = _render_info(request, estado='metodo_no_permitido', status_code=405)
        else:
            response = JsonResponse({'error': 'method_not_allowed'}, status=405)
        nota = 'metodo_no_permitido'
    _log_hit(request, response.status_code if response else 0, nota=nota)
    return response


# ---------------------------------------------------------------------------
# Handshake (GET)
# ---------------------------------------------------------------------------

def _verificar_webhook(request):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    # Detectar handshake real de Meta: SIEMPRE trae los 3 parametros.
    # Si falta `hub.challenge` no es Meta — es alguien probando la URL.
    es_handshake_meta = bool(mode and challenge is not None)

    if not es_handshake_meta:
        # Acceso desde navegador / curl / monitoreo: pagina informativa.
        return _render_info(request, estado='landing')

    # A partir de aqui estamos en el flujo oficial de Meta. Meta espera
    # respuestas en texto plano (sin HTML), incluso en los errores.
    if mode != 'subscribe':
        logger.warning("Meta webhook: hub.mode invalido '%s'", mode)
        return HttpResponse('invalid_mode', content_type='text/plain', status=400)

    if not token:
        logger.warning("Meta webhook: falta hub.verify_token en el handshake")
        return HttpResponse('missing_verify_token', content_type='text/plain', status=400)

    config = ConfigMeta.objects.filter(webhook_verify_token=token).first()
    if not config:
        logger.warning("Meta webhook verify: token no coincide con ninguna ConfigMeta (token_prefix=%s)",
                       (token or '')[:8])
        return HttpResponse('forbidden', content_type='text/plain', status=403)

    # El webhook de Meta es a nivel APP (un solo endpoint + app_secret org-level
    # compartido por todas las WABAs). Por eso Meta solo expone un verify token
    # en el panel, pero cada ConfigMeta guarda el suyo. Un handshake exitoso
    # verifica el endpoint para TODAS las sesiones, no solo la que casó el token
    # — así el diagnóstico no deja números en "Pendiente" para siempre.
    ahora = timezone.now()
    ConfigMeta.objects.filter(
        webhook_verificado_en__isnull=True,
    ).exclude(pk=config.pk).update(webhook_verificado_en=ahora)
    config.webhook_verificado_en = ahora
    config.save(update_fields=['webhook_verificado_en'])

    logger.info("Meta webhook verificado (handshake casó ConfigMeta id=%s, WABA %s); "
                "marcadas todas las sesiones pendientes como verificadas.",
                config.id, config.waba_id)
    return HttpResponse(challenge, content_type='text/plain', status=200)


# ---------------------------------------------------------------------------
# Pagina informativa HTML — solo para accesos desde navegador/curl
# ---------------------------------------------------------------------------

def _cliente_espera_html(request) -> bool:
    accept = (request.META.get('HTTP_ACCEPT') or '').lower()
    return 'text/html' in accept


def _render_info(request, estado='landing', status_code=200, mensaje_error=None):
    """Pagina informativa para cuando alguien accede al webhook sin ser Meta.
    Muestra metricas agregadas (nunca tokens/access_tokens) y ayuda al dev.
    """
    try:
        from .common_meta import get_meta_app_secret
        total_configs    = ConfigMeta.objects.count()
        verificados      = ConfigMeta.objects.exclude(webhook_verificado_en__isnull=True).count()
        with_app_secret  = total_configs if get_meta_app_secret() else 0
        eventos_total    = EventoMetaRecibido.objects.count()
        eventos_procesados = EventoMetaRecibido.objects.filter(procesado=True).count()
        eventos_con_error  = EventoMetaRecibido.objects.exclude(error_procesamiento__isnull=True).exclude(error_procesamiento='').count()
        ultimos_eventos  = list(
            EventoMetaRecibido.objects.order_by('-fecha_registro')
            .values('id', 'tipo_evento', 'procesado', 'firma_valida', 'fecha_registro', 'error_procesamiento')[:5]
        )
    except Exception as e:
        logger.exception("Error construyendo landing meta_webhook: %s", e)
        total_configs = verificados = with_app_secret = 0
        eventos_total = eventos_procesados = eventos_con_error = 0
        ultimos_eventos = []

    contexto = {
        'estado':             estado,
        'mensaje_error':      mensaje_error,
        'total_configs':      total_configs,
        'verificados':        verificados,
        'sin_verificar':      max(total_configs - verificados, 0),
        'with_app_secret':    with_app_secret,
        'eventos_total':      eventos_total,
        'eventos_procesados': eventos_procesados,
        'eventos_con_error':  eventos_con_error,
        'ultimos_eventos':    ultimos_eventos,
        'webhook_url':        request.build_absolute_uri(request.path),
        'metodo':             request.method,
        'ahora':              timezone.now(),
        'ua_resumido':        (request.META.get('HTTP_USER_AGENT') or '')[:120],
        'query_string':       request.META.get('QUERY_STRING') or '',
    }
    return render(request, 'whatsapp/meta_webhook_info.html', contexto, status=status_code)


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

    from .common_meta import get_meta_app_secret
    app_secret_org = get_meta_app_secret()
    firma_valida = _validar_firma_hmac(raw_body, signature, app_secret_org)

    evento = EventoMetaRecibido.objects.create(
        config_meta=config,
        tipo_evento=_extraer_tipo_evento(payload),
        payload_json=payload,
        firma_valida=firma_valida,
        procesado=False,
    )

    # `_validar_firma_hmac` ya devuelve True en modo permisivo sin secret, así que
    # `not firma_valida` cubre: firma inválida con secret, o secret ausente en
    # modo estricto. En ambos casos rechazamos.
    if not firma_valida:
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

def _validar_firma_hmac(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """Compara X-Hub-Signature-256 contra HMAC(app_secret_org, body).

    Con app_secret: valida y rechaza firmas inválidas (fail-closed). Sin
    app_secret: por defecto acepta con warning; con META_WEBHOOK_FAIL_CLOSED=True
    rechaza (recomendado en producción)."""
    if not app_secret:
        from django.conf import settings
        if getattr(settings, 'META_WEBHOOK_FAIL_CLOSED', False):
            logger.error(
                "Webhook Meta RECHAZADO: app_secret no configurado y modo estricto "
                "activo (META_WEBHOOK_FAIL_CLOSED)."
            )
            return False
        logger.warning(
            "Webhook Meta aceptado SIN validar firma (app_secret no configurado) — "
            "activa META_WEBHOOK_FAIL_CLOSED=True en producción para cerrar el fail-open."
        )
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
    process_incoming_message (webhook_baileys_view) espera, originalmente
    disenado para Baileys."""
    try:
        from_num = msg_meta.get('from', '')
        if not from_num:
            return None

        # Contrato de normalizacion del numero (direcciones opuestas):
        #   ENTRADA (este archivo):  Meta -> Baileys shape
        #     Meta manda "593xxx" plano (wa_id). Lo sufijamos @s.whatsapp.net
        #     para que process_incoming_message y Contacto.from_number casen
        #     con los registros existentes creados por Baileys.
        #   SALIDA (services_meta._normalizar_destinatario):
        #     El CRM envia "593xxx@s.whatsapp.net"; services_meta hace split
        #     y deja solo "593xxx" (lo que Meta exige en Graph API).
        # Edge case: si Meta alguna vez manda '+' o tiene ya sufijo, lo
        # sanitizamos aqui para evitar que el comparador
        # `session.numero == contacto_numero` (en webhook_baileys_view) falle.
        from_num = from_num.strip().lstrip('+')
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
            # Respuesta a botones o listas. Capturamos `id` (clave para matchear
            # contra OpcionDepartamentoChatBot.boton_id en el motor) y `title`
            # (texto visible). Lo expongo como `_boton_id` y `_boton_title` para
            # que process_incoming_message + motor_flujo lo lean.
            interactive = msg_meta.get('interactive') or {}
            kind = interactive.get('type')
            texto_boton = ''
            boton_id = ''
            if kind == 'button_reply':
                br = interactive.get('button_reply') or {}
                texto_boton = br.get('title', '') or ''
                boton_id    = br.get('id', '') or ''
            elif kind == 'list_reply':
                lr = interactive.get('list_reply') or {}
                texto_boton = lr.get('title', '') or ''
                boton_id    = lr.get('id', '') or ''
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
            media_id = media_obj.get('id')
            # Descargamos los bytes de Meta (dos llamadas Graph API) y los
            # codificamos a base64 para que save_media_file (pensado para el
            # formato Baileys) los persista sin cambios en webhook_baileys_view.
            media_data = None
            if media_id:
                try:
                    import base64 as _b64
                    from .services_meta import MetaWhatsAppService
                    bytes_media = MetaWhatsAppService().descargar_media(
                        sesion.session_id, media_id
                    )
                    if bytes_media:
                        media_data = _b64.b64encode(bytes_media).decode('utf-8')
                    else:
                        logger.warning(
                            "Meta media %s no se pudo descargar (sesion %s)",
                            media_id, sesion.session_id,
                        )
                except Exception:
                    logger.exception(
                        "Error descargando media Meta %s (sesion %s)",
                        media_id, sesion.session_id,
                    )
            # Meta rara vez entrega filename para fotos/audio/sticker.
            # Generamos uno con extension acorde al MIME para que el storage lo acepte.
            if not filename:
                ext_por_tipo = {
                    'image': 'jpg', 'video': 'mp4', 'audio': 'ogg',
                    'document': 'bin', 'sticker': 'webp',
                }
                ext = ext_por_tipo.get(tipo_meta, 'bin')
                mime_type = media_obj.get('mime_type') or ''
                if '/' in mime_type:
                    ext_mime = mime_type.split('/', 1)[1].split(';')[0].strip()
                    if ext_mime and len(ext_mime) <= 8:
                        ext = ext_mime
                filename = f"{tipo_meta}_{(msg_meta.get('id') or '')[:32]}.{ext}"
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
        # Botón / list reply — clave para que el motor del flujo
        # tradicional matchee contra OpcionDepartamentoChatBot.boton_id
        # sin depender de adivinar por texto.
        if tipo_meta == 'interactive':
            try:
                if boton_id:
                    evento_interno['_boton_id'] = boton_id
                if texto_boton:
                    evento_interno['_boton_title'] = texto_boton
            except NameError:
                pass

        # Bloque referral: presente cuando el contacto entra desde un anuncio
        # Click-to-WhatsApp (CTWA). Meta lo entrega tanto en el mensaje
        # como, a veces, en el `value.referral` global.
        referral = msg_meta.get('referral') or value.get('referral') or {}
        if referral:
            evento_interno['_referral'] = referral
        # External id (wa_id) + meta_user_id (cross-app identity).
        # Meta puede mandar ambos en contacts[]:
        #   wa_id    → "593994233732" (es el numero, mismo que from_num)
        #   user_id  → "EC.955878333820533" (identidad cross-app del usuario,
        #              mismo si entra por WA / IG / Messenger). Util para
        #              deduplicacion y atribucion CAPI.
        wa_id = None
        meta_user_id = None
        for c in value.get('contacts') or []:
            if c.get('wa_id') and not wa_id:
                wa_id = c['wa_id']
            if c.get('user_id') and not meta_user_id:
                meta_user_id = c['user_id']
        if wa_id:
            evento_interno['_external_id'] = wa_id
        if meta_user_id:
            evento_interno['_meta_user_id'] = meta_user_id
        evento_interno['_canal'] = 'whatsapp'

        return evento_interno

    except Exception:
        logger.exception("Error traduciendo mensaje Meta a formato interno")
        return None


# ---------------------------------------------------------------------------
# Status / ACK (message_ack equivalent)
# ---------------------------------------------------------------------------

def _procesar_status_meta(status: dict, sesion: SesionWhatsApp, evento: EventoMetaRecibido):
    """Meta manda statuses: sent → delivered → read (o failed). Mapeamos al
    MensajeWhatsApp por mensaje_id_externo. 'read' ademas marca leido=True y
    notifica via WebSocket para que la UI actualice el tick azul sin refresh."""
    from asgiref.sync import async_to_sync
    from .models import MensajeWhatsApp

    mid = status.get('id')
    estado = (status.get('status') or '').lower()
    logger.info("Meta status: msg=%s estado=%s sesion=%s", mid, estado, sesion.id)

    mensaje = None
    if mid:
        mensaje = (
            MensajeWhatsApp.objects
            .filter(mensaje_id_externo=mid, conversacion__contacto__sesion=sesion)
            .select_related('conversacion')
            .first()
        )

    # Mapeo status Meta → estado_envio interno
    mapa_estado = {
        'sent':      'enviado',
        'delivered': 'entregado',
        'read':      'leido',
        'failed':    'fallido',
    }
    nuevo_estado_envio = mapa_estado.get(estado)

    # Extraer detalle de error (si aplica) una sola vez — lo usan traza y modelo
    detalle_error = ''
    codigo_meta = None
    if estado == 'failed':
        errors = status.get('errors') or []
        if errors:
            err0 = errors[0] if isinstance(errors[0], dict) else {}
            detalle_error = (
                err0.get('title')
                or err0.get('message')
                or (err0.get('error_data') or {}).get('details')
                or str(errors)[:500]
            )
            codigo_meta = err0.get('code')

    # Actualizar MensajeWhatsApp con el nuevo estado_envio.
    # Preservamos el orden monotonico: no bajamos de 'leido' a 'entregado' si
    # Meta manda los eventos fuera de orden (caso raro pero posible).
    ORDEN = {'': 0, 'pendiente': 1, 'enviado': 2, 'entregado': 3, 'leido': 4, 'fallido': 5}
    if mensaje and nuevo_estado_envio:
        actual = mensaje.estado_envio or ''
        update_fields = []
        # 'fallido' siempre gana — es terminal.
        if nuevo_estado_envio == 'fallido' or ORDEN[nuevo_estado_envio] > ORDEN.get(actual, 0):
            mensaje.estado_envio = nuevo_estado_envio
            update_fields.append('estado_envio')
            if nuevo_estado_envio == 'fallido' and detalle_error:
                mensaje.error_envio = (f"[{codigo_meta}] " if codigo_meta else '') + detalle_error
                update_fields.append('error_envio')
            if nuevo_estado_envio == 'leido' and not mensaje.leido:
                mensaje.leido = True
                mensaje.fecha_leido = timezone.now()
                update_fields += ['leido', 'fecha_leido']
            mensaje.save(update_fields=update_fields)

            # Broadcast WS para refrescar tick sin reload
            try:
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f"chat_{mensaje.conversacion.id}",
                        {
                            'type': 'whatsapp_message',
                            'event': 'message_status',
                            'conversation_id': mensaje.conversacion.id,
                            'message_id': mensaje.id,
                            'estado_envio': mensaje.estado_envio,
                        },
                    )
            except Exception:
                logger.exception("Broadcast ACK Meta fallo msg=%s", mensaje.id)

    # Acciones automáticas según el código de error de Meta (no reintentar,
    # proteger la calidad del número):
    #   131030 → el número no existe en WhatsApp → marcar contacto inválido
    #   131050 → el usuario bloqueó marketing → baja automática (opt-out)
    #   131047 → ventana 24h vencida → requiere plantilla (se anota en la traza)
    accion_codigo = ''
    if estado == 'failed' and codigo_meta and mensaje and mensaje.conversacion_id:
        try:
            contacto = mensaje.conversacion.contacto
            if contacto is not None:
                from .opt_out import marcar_numero_invalido, marcar_opt_out
                if int(codigo_meta) == 131030:
                    marcar_numero_invalido(contacto)
                    accion_codigo = 'contacto_marcado_invalido'
                elif int(codigo_meta) == 131050:
                    marcar_opt_out(contacto, motivo='meta_131050')
                    accion_codigo = 'contacto_opt_out_automatico'
                elif int(codigo_meta) == 131047:
                    accion_codigo = 'requiere_plantilla_reenganche'
        except Exception:
            logger.exception("Accion automatica por codigo Meta %s fallo", codigo_meta)

    # Traza — etapa y nivel segun estado
    if estado == 'sent':
        etapa, nivel = 'mensaje_enviado', 'info'
    elif estado == 'failed':
        etapa, nivel = 'envio_fallido', 'error'
    else:
        etapa, nivel = 'webhook_recibido', 'info'

    detalle = {'meta_status': estado, 'mensaje_id_externo': mid}
    if detalle_error:
        detalle['error'] = detalle_error
        if codigo_meta:
            detalle['codigo_meta'] = codigo_meta
        if accion_codigo:
            detalle['accion_automatica'] = accion_codigo

    _traza(
        etapa=etapa, sesion=sesion,
        conversacion=mensaje.conversacion if mensaje else None,
        mensaje=mensaje, nivel=nivel, detalle=detalle,
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
