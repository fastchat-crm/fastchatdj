"""Núcleo compartido de procesamiento de mensajes WhatsApp.

Funciones aquí las usan ambos transports:
- Baileys via `webhook_baileys_view.webhook_handler`
- Meta Cloud API via `meta_webhook_view.meta_webhook` y `meta_social_webhook_view`

El payload Meta se traduce al formato Baileys-style en `meta_webhook_view`
antes de llamar `process_incoming_message`, así toda la lógica de IA, motor
tradicional, fuera-de-horario, rate-limit, etc. vive en un solo lugar.
"""
from datetime import timedelta
import base64
import json
import logging
import os

from django.db.models import Count, Q, Window
from django.db.models.functions import RowNumber
from django.http import JsonResponse
from django.utils import timezone
from django.core.files.base import ContentFile
from django.core.cache import cache
from django.conf import settings
from asgiref.sync import async_to_sync

from crm.acciones_fin import ejecutar_acciones_fin
from crm.models import ReglaFinConversacion, ConsumoTokenIA
from core.constantes import PROMPT_TEMPLATES
from core.funciones import notificacion
from core.funciones_adicionales import get_image_as_base64, get_numero_emoji_ws

from .models import (
    ConversacionWhatsApp, Contacto,
    MensajeWhatsApp,
    EstadisticasConversacion,
)
from .services import get_whatsapp_service
from .trazas import registrar as _traza, notificar_superusers_error, fallback_permitido

logger = logging.getLogger(__name__)


def process_incoming_message(session, event_data, channel_layer):
    """
    Procesa un mensaje entrante de WhatsApp
    """
    try:
        print('process_incoming_message', event_data)
        # Extraer datos del mensaje
        message_id = event_data.get('id')
        from_number = event_data.get('from')
        timestamp = event_data.get('timestamp')
        push_name = event_data.get('pushName', '')
        message_content = event_data.get('message', {})
        from_me = bool(event_data.get('fromMe', False))
        userImage = event_data.get('userImage')

        # Convertir timestamp a datetime
        if isinstance(timestamp, int):
            message_date = timezone.datetime.fromtimestamp(timestamp, tz=timezone.get_current_timezone())
        else:
            message_date = timezone.now()

        # Limpiar el número de teléfono (quitar el @s.whatsapp.net)
        contacto_numero = ''
        if '@' in from_number:
            contacto_numero = from_number.split('@')[0]

        if session.numero == contacto_numero:
            return

        # Buscar o crear la conversación
        contacto, _ = Contacto.objects.get_or_create(
            sesion=session, from_number=from_number
        )
        contacto.estado = 'activo'

        # Actualizar nombre del contacto si está disponible.
        # contacts_list vive en ConfigBaileys (no en SesionWhatsApp) — solo
        # las sesiones Baileys lo tienen. Para Meta no existe config_baileys
        # y usamos directamente push_name (que Meta ya provee en cada evento).
        if not contacto.contacto_nombre:
            contacto.contacto_nombre = push_name
            cfg_baileys = getattr(session, 'config_baileys', None)
            if cfg_baileys and cfg_baileys.contacts_list:
                try:
                    contacts_list = [
                        c.get('name') or c.get('notify') or ''
                        for c in json.loads(cfg_baileys.contacts_list or '[]')
                        if c.get('id') == from_number
                    ]
                    if contacts_list and contacts_list[0]:
                        contacto.contacto_nombre = contacts_list[0]
                except (ValueError, TypeError):
                    # contacts_list mal formado — nos quedamos con push_name
                    pass
        if not contacto.contacto_numero:
            contacto.contacto_numero = contacto_numero

        if userImage:
            contacto.contacto_foto = f'data:image/jpg;base64,{get_image_as_base64(userImage)}'

        # Multi-canal: marcar canal y external_id la primera vez
        canal_evt = event_data.get('_canal') or 'whatsapp'
        if not contacto.canal or contacto.canal == 'whatsapp':
            contacto.canal = canal_evt
        ext_id = event_data.get('_external_id')
        if ext_id and not contacto.external_id:
            contacto.external_id = ext_id

        # Identidad cross-app de Meta (EC.xxx). Solo se setea la primera vez
        # — si Meta cambia el identificador (raro), no sobreescribimos para
        # no perder el ID original con el que ya construimos historial.
        meta_uid = event_data.get('_meta_user_id')
        if meta_uid and not contacto.meta_user_id:
            contacto.meta_user_id = meta_uid

        # Referral de Click-to-WhatsApp ad — touchpoint de adquisición.
        # Solo se guarda la primera vez para preservarlo aun si después el
        # contacto vuelve por mensaje orgánico. Si necesitamos historial
        # completo de campañas, irá a otra tabla.
        referral = event_data.get('_referral')
        if referral and not contacto.referral_meta:
            contacto.referral_meta = referral

        contacto.save()

        # Determinar el tipo de mensaje y su contenido
        message_type = 'texto'
        message_text = ''
        file_url = None

        # Procesar texto
        if 'conversation' in message_content:
            message_type = 'texto'
            message_text = message_content.get('conversation', '')
        elif 'extendedTextMessage' in message_content:
            message_type = 'texto'
            message_text = message_content.get('extendedTextMessage', {}).get('text', '')

        # Procesar archivos multimedia — soporta formato nuevo (flat: event_data['mediaType'])
        # y antiguo (nested: event_data['message']['imageMessage'], etc.)
        TIPO_MAP = {
            'imageMessage': 'imagen',
            'videoMessage': 'video',
            'audioMessage': 'audio',
            'documentMessage': 'documento',
            'stickerMessage': 'sticker',
        }
        detected_media_key = event_data.get('mediaType')
        if not detected_media_key:
            for k in TIPO_MAP:
                if k in message_content:
                    detected_media_key = k
                    break

        if detected_media_key and detected_media_key in TIPO_MAP:
            type_name = TIPO_MAP[detected_media_key]
            message_type = type_name
            media_msg = message_content.get(detected_media_key, {}) if isinstance(message_content, dict) else {}

            caption = event_data.get('caption') or media_msg.get('caption', '')
            if caption:
                message_text = caption
            message_text = message_text or type_name

            if event_data.get('mediaData'):
                media_data = event_data['mediaData']
                filename = (
                    event_data.get('fileName')
                    or media_msg.get('fileName')
                    or f"{type_name}_{message_id}"
                )
                if detected_media_key == 'stickerMessage' and not filename.lower().endswith('.png'):
                    filename = f'{filename}.png'
                file_url = save_media_file(media_data, filename)

        # Actualizar la conversación con el último mensaje
        contacto.ultimo_mensaje = message_text[:100] + ('...' if len(message_text) > 100 else '')
        contacto.fecha_ultimo_mensaje = message_date
        contacto.save()

        # Guard de idempotencia: si ya procesamos este mensaje_id, no duplicar
        if message_id and MensajeWhatsApp.objects.filter(
            mensaje_id_externo=message_id, conversacion__contacto__sesion=session
        ).exists():
            logger.warning(f"Mensaje duplicado ignorado: {message_id}")
            return

        try:
            conversation, created = ConversacionWhatsApp.obtener_o_crear_activa(contacto)
            if created:
                logger.info("Nueva conversación creada #%s para contacto %s", conversation.id, contacto.id)
                # Hereda canal del contacto
                if contacto.canal and conversation.origen_canal != contacto.canal:
                    conversation.origen_canal = contacto.canal
                # Capturar referral CTWA / CTIG si vino en el evento
                referral = event_data.get('_referral') or {}
                if referral:
                    conversation.referral_payload_json = referral
                    conversation.referral_source_type = (referral.get('source_type') or referral.get('type') or 'AD').upper()[:20]
                    conversation.referral_source_url = referral.get('source_url') or referral.get('url')
                    conversation.referral_headline = (referral.get('headline') or '')[:500]
                    conversation.referral_body = referral.get('body') or referral.get('description')
                    conversation.referral_medium = (referral.get('media_type') or referral.get('image_url') and 'image' or '')[:20] or None
                    conversation.ctwa_clid = (
                        referral.get('ctwa_clid')
                        or referral.get('ad_id')
                        or (referral.get('ref') if isinstance(referral.get('ref'), str) else None)
                    )
                    conversation.ad_id = referral.get('ad_id')
                    conversation.adset_id = referral.get('adset_id')
                    conversation.campaign_id = referral.get('campaign_id') or referral.get('source_id')
                conversation.save(update_fields=[
                    'origen_canal', 'referral_payload_json', 'referral_source_type',
                    'referral_source_url', 'referral_headline', 'referral_body',
                    'referral_medium', 'ctwa_clid', 'ad_id', 'adset_id', 'campaign_id',
                ])
                # Round-robin: auto-asignar agente humano si la sesión lo pide
                if getattr(session, 'auto_asignar_round_robin', False):
                    try:
                        from .services_round_robin import asignar_automaticamente
                        asignar_automaticamente(conversation)
                    except Exception:
                        logger.exception("Round-robin falló para conv=%s", conversation.id)
                # CAPI: reportar Lead si la conversación trae atribución
                if conversation.ctwa_clid or conversation.ad_id:
                    try:
                        from .services_capi import reportar_lead_si_corresponde
                        reportar_lead_si_corresponde(conversation)
                    except Exception:
                        logger.exception("CAPI Lead falló para conv=%s", conversation.id)
        except Exception as create_err:
            logger.error(
                "ERROR obteniendo/creando conversación para contacto %s (sesión %s): %s — "
                "¿Hay migraciones pendientes? Ejecuta: py manage.py migrate",
                contacto.id, session.session_id, create_err, exc_info=True
            )
            _traza(
                etapa='error_general', sesion=session, numero=from_number, nivel='error',
                detalle=f'obtener_o_crear_activa contacto_id={contacto.id}: {type(create_err).__name__}: {str(create_err)[:1500]}',
            )
            raise

        # Renovar ventana de expiración con cada mensaje entrante del cliente
        if from_number != session.numero:  # sólo mensajes del cliente
            min_sesion = int(getattr(session, 'min_sesion', None) or 10)
            conversation.fecha_hora_expira = timezone.now() + timedelta(minutes=min_sesion)
            conversation.save(update_fields=['fecha_hora_expira'])

        # Crear el mensaje
        message = MensajeWhatsApp.objects.create(
            conversacion=conversation,
            remitente=from_number,
            mensaje=message_text,
            tipo=message_type,
            archivo=file_url,
            fecha=message_date,
            mensaje_id_externo=message_id
        )
        _traza(
            etapa='mensaje_guardado', sesion=session, conversacion=conversation, mensaje=message,
            numero=from_number, nivel='info',
            detalle={'tipo': message_type, 'preview': (message_text or '')[:200], 'msg_id_ext': message_id},
        )

        # Actualizar estadísticas
        update_conversation_stats(conversation)

        # ── Cortar envío si Node ya nos avisó que está rate-limited ──
        # Evita amplificar la saturación enviando bienvenida/IA/avisos durante la ventana.
        _rate_info = cache.get(f'wa_rate_limited_{session.id}')
        if _rate_info:
            _retry_s = int(_rate_info.get('retry_after_s', 60) or 60)
            _traza(
                etapa='node_rate_limited', sesion=session, conversacion=conversation, mensaje=message,
                numero=from_number, nivel='warning',
                detalle={
                    'retry_after_s': _retry_s,
                    'count': _rate_info.get('count'),
                    'max': _rate_info.get('max'),
                    'motivo': 'mensaje entrante saltado durante ventana rate-limit',
                },
            )
            _aviso_key = f'aviso_rate_limit_conv_{conversation.id}'
            if not cache.get(_aviso_key):
                cache.set(_aviso_key, 1, timeout=_retry_s)
                try:
                    get_whatsapp_service(session).send_text_message(
                        conversation.sesion.session_id, contacto.from_number,
                        '⏳ Estamos recibiendo muchos mensajes. Te responderemos en unos momentos.',
                    )
                except Exception:
                    logger.exception("No se pudo enviar aviso rate-limit a %s", from_number)
            return JsonResponse({'status': 'ok', 'rate_limited': True, 'retry_after_s': _retry_s})

        whatsapp_service = get_whatsapp_service(session)
        primer_mensaje = not conversation.bienvenida_enviado
        numero_opcion_respondido = (message_text or '').replace(' ', '')
        numero_opcion_respondido = numero_opcion_respondido.isdigit() and numero_opcion_respondido or -1

        # ── GUARD: Horario de atención ───────────────────────────────────
        # Política:
        #   modo_bot = 'tradicional' → SIEMPRE deja correr el motor del flujo
        #     (el flujo puede tener su propia rama "fuera de hora" en el menú).
        #     Solo registra la traza informativa.
        #   modo_bot = 'ia' o 'ninguno' → manda `mensaje_fuera_horario` y corta
        #     ANTES de la IA (evita gastar tokens fuera de hora).
        # Throttle del aviso: 1 vez por conversación cada 6h.
        try:
            from .services_horarios import dentro_de_horario, mensaje_fuera_horario_configurado
            _en_horario = dentro_de_horario(session)
            if not _en_horario:
                _modo_actual = (session.modo_bot or 'ia')
                if _modo_actual == 'tradicional':
                    # Solo log — el motor del flujo se ejecuta normalmente.
                    _traza(
                        etapa='webhook_recibido', sesion=session, conversacion=conversation, mensaje=message,
                        numero=from_number, nivel='info',
                        detalle={'fuera_horario': True, 'modo_bot': 'tradicional',
                                 'accion': 'continua_motor_flujo'},
                    )
                else:
                    # IA o ninguno → enviar aviso + cortar para no invocar LLM.
                    _msg_personalizado = mensaje_fuera_horario_configurado(session)
                    _msg_fuera = _msg_personalizado or (
                        "👋 ¡Gracias por escribirnos! En este momento estamos fuera "
                        "de nuestro horario de atención. Te responderemos en cuanto "
                        "volvamos a estar disponibles. 🕐"
                    )
                    _key_fuera = f'fuera_horario_aviso_{conversation.id}'
                    # cache.add es atómico: solo un proceso/worker gana el lock
                    # cuando llegan webhooks concurrentes del mismo cliente.
                    _lock_aceptado = cache.add(_key_fuera, True, 6 * 3600)
                    _ya_avisado = not _lock_aceptado
                    _envio_ok = None
                    if _lock_aceptado:
                        try:
                            _r = whatsapp_service.send_text_message(
                                session.session_id, contacto.from_number, _msg_fuera, simularEscritura=True
                            )
                            _envio_ok = bool((_r or {}).get('success'))
                            # Persistir en el historial de la conversación
                            # para que aparezca en /whatsapp/conversaciones/<id>/.
                            if _envio_ok:
                                try:
                                    _msg_id_ext = (_r or {}).get('message_id') or ''
                                    MensajeWhatsApp.objects.create(
                                        conversacion=conversation,
                                        remitente=session.numero,
                                        mensaje=_msg_fuera,
                                        tipo='texto',
                                        fecha=timezone.now(),
                                        mensaje_id_externo=_msg_id_ext,
                                        leido=True,
                                        fecha_leido=timezone.now(),
                                        es_automatico=True,
                                    )
                                except Exception as _save_ex:
                                    logger.warning("Fuera_horario: no se pudo persistir aviso: %s", _save_ex)
                        except Exception as _send_ex:
                            logger.exception("Fuera_horario: error enviando aviso: %s", _send_ex)
                            _envio_ok = False
                    _traza(
                        etapa='webhook_recibido', sesion=session, conversacion=conversation, mensaje=message,
                        numero=from_number, nivel='info',
                        detalle={
                            'fuera_horario': True,
                            'modo_bot': _modo_actual,
                            'aviso_throttled': _ya_avisado,
                            'envio_ok': _envio_ok,
                            'mensaje_personalizado': bool(_msg_personalizado),
                            'mensaje_preview': _msg_fuera[:140],
                        },
                    )
                    return JsonResponse({'status': 'ok', 'fuera_horario': True, 'envio_ok': _envio_ok})
        except Exception as _h_ex:
            logger.warning("Guard horario falló (continúa flujo normal): %s", _h_ex)
        # ─────────────────────────────────────────────────────────────────

        _ia_activa = bool(session.agente_ia and session.agente_ia.apikey.filter(estado=True).exists())
        if not conversation.bienvenida_enviado:
            conversation.bienvenida_enviado = True
            conversation.save()
            if conversation.sesion.mensaje_bienvenida:
                whatsapp_service.send_text_message(conversation.sesion.session_id, contacto.from_number, conversation.sesion.mensaje_bienvenida, simularEscritura=True)

        # Auto-respuesta amigable cuando el medio no fue capturado (imagen/video/documento/sticker)
        # Audio se procesa por transcripción; los demás no se leen automáticamente.
        if message_type in ('imagen', 'video', 'documento', 'sticker') and not file_url:
            try:
                _media_key = f'notif_media_skipped_{conversation.id}'
                if not cache.get(_media_key):
                    cache.set(_media_key, True, 300)  # throttle 5 min
                    _tipo_emoji = {'imagen': '📷', 'video': '🎥', 'documento': '📄', 'sticker': '🎨'}.get(message_type, '📎')
                    _tipo_nombre = {'imagen': 'imagen', 'video': 'video', 'documento': 'documento', 'sticker': 'sticker'}.get(message_type, 'archivo')
                    _aviso = (
                        f"{_tipo_emoji} ¡Hola! Recibimos tu {_tipo_nombre}, pero por el momento no podemos "
                        f"procesarla automáticamente. Si necesitas ayuda, por favor descríbenos tu consulta "
                        f"por mensaje de texto y con gusto te atendemos. 🙌"
                    )
                    whatsapp_service.send_text_message(
                        conversation.sesion.session_id, contacto.from_number, _aviso, simularEscritura=True
                    )
            except Exception as _media_ex:
                logger.exception("Error enviando aviso media skipped: %s", _media_ex)

        # Log diagnóstico cuando la IA no está activa — ayuda a detectar cambios de agente sin keys
        if not _ia_activa and session.agente_ia:
            _keys_total = session.agente_ia.apikey.count()
            _keys_activas = session.agente_ia.apikey.filter(estado=True).count()
            logger.warning(
                "Sesión %s: agente '%s' (id=%s) tiene %d/%d API Keys activas — IA desactivada",
                session.session_id, session.agente_ia.nombre, session.agente_ia.id,
                _keys_activas, _keys_total,
            )
            _traza(
                etapa='ia_desactivada', sesion=session, conversacion=conversation, mensaje=message,
                numero=from_number, nivel='warning',
                detalle=f"Agente {session.agente_ia.nombre} tiene {_keys_activas}/{_keys_total} API Keys activas",
            )
            # Notificar al usuario del CRM si el agente no tiene keys activas (una vez cada 10 min)
            if _keys_activas == 0:
                try:
                    _notif_key = f'notif_ia_sin_keys_{session.id}'
                    if not cache.get(_notif_key):
                        cache.set(_notif_key, True, 600)  # throttle 10 minutos
                        notificacion(
                            titulo=f'Agente IA sin API Keys activas — "{session.nombre or session.session_id}"',
                            cuerpo=(
                                f'El agente <strong>{session.agente_ia.nombre}</strong> no tiene API Keys activas '
                                f'({_keys_total} key(s) registradas, todas desactivadas). '
                                f'La IA no responderá hasta que reactives una key en '
                                f'<a href="/crm/entrenamiento/">Entrenamiento IA</a>.'
                            ),
                            destinatario=session.usuario,
                            url='/crm/entrenamiento/',
                            prioridad=1,
                            tipo=4,
                        )
                except Exception:
                    pass

        # ────────────────────────────────────────────────────────────
        # Motor del chatbot TRADICIONAL (flujo/API, estilo n8n).
        # Se activa SÓLO si la sesión lo pide por su `modo_bot`. No
        # interfiere con el pipeline IA: si no maneja el mensaje y el
        # No interfiere con IA: modos 'tradicional' e 'ia' son exclusivos.
        # ────────────────────────────────────────────────────────────
        _modo_bot = (session.modo_bot or 'ia')
        if _modo_bot == 'tradicional':
            _ex_motor = None
            try:
                from crm.motor_flujo_chatbot import procesar_mensaje_tradicional
                # Extraer boton_id si vino de un interactive button/list reply
                # (Meta lo inyecta en `_boton_id` desde meta_webhook_view).
                _boton_id_evt = event_data.get('_boton_id') or ''
                _res_motor = procesar_mensaje_tradicional(
                    session, conversation, contacto, message_text or '',
                    boton_id=_boton_id_evt,
                )
            except Exception as _ex_motor_raised:
                _ex_motor = _ex_motor_raised
                logger.exception("Motor flujo falló conv=%s: %s", conversation.id, _ex_motor)
                _res_motor = None

            _traza(
                etapa='motor_flujo', sesion=session, conversacion=conversation, mensaje=message,
                numero=from_number, nivel=('error' if _ex_motor else 'info'),
                detalle={
                    'modo_bot': _modo_bot,
                    'manejado': bool(_res_motor and _res_motor.manejado),
                    'fallback_ia': bool(_res_motor and _res_motor.fallback_ia),
                    'handoff': bool(_res_motor and _res_motor.handoff),
                    'finalizado': bool(_res_motor and _res_motor.finalizado),
                    'respuestas': len(_res_motor.respuestas) if _res_motor else 0,
                    'error': (
                        f'{type(_ex_motor).__name__}: {str(_ex_motor)[:500]}' if _ex_motor
                        else (getattr(_res_motor, 'error', '') if _res_motor else '')
                    ),
                },
            )

            # El motor manejó la conversación → cortar aquí.
            if _res_motor and (_res_motor.manejado or _res_motor.handoff or _res_motor.finalizado):
                return JsonResponse({'status': 'ok', 'modo': 'tradicional'})

            # Modo tradicional puro: sin match → no delegamos a IA.
            return JsonResponse({'status': 'ok', 'modo': 'tradicional_sin_match'})

        departamentos = conversation.sesion.departamentos.all().annotate(
            numero_opcion=Window(
                expression=RowNumber(),
                order_by='id'
            )
        )
        departamentos_msg = 'Escribe el número del departamento para continuar:\n'
        if _ia_activa and conversation.ai_activo:
            agente = session.agente_ia
            _traza(
                etapa='agente_asignado', sesion=session, conversacion=conversation, mensaje=message,
                numero=from_number, nivel='info',
                detalle={'agente': agente.nombre, 'agente_id': agente.id, 'keys_activas': agente.apikey.filter(estado=True).count()},
            )

            # ── Detección de reintento ────────────────────────────────────
            texto_normalizado = (message_text or '').strip().lower()
            es_reintento = texto_normalizado in ('reintentar', 'reintento', 'retry', 'intentar de nuevo', 'volver a intentar')
            if es_reintento:
                # Buscar el último mensaje del contacto que NO sea una palabra de reintento
                ultimo = (
                    MensajeWhatsApp.objects
                    .filter(conversacion=conversation, remitente=from_number)
                    .exclude(pk=message.pk)
                    .order_by('-fecha')
                    .first()
                )
                if ultimo and ultimo.mensaje:
                    message_text = ultimo.mensaje
                else:
                    whatsapp_service.send_text_message(
                        conversation.sesion.session_id, contacto.from_number,
                        'No encontré un mensaje anterior para reintentar. Por favor escribe tu consulta nuevamente.'
                    )
                    return JsonResponse({'status': 'ok'})

            # ── Detección de fin: sesión propia → plantilla del agente ───
            regla_fin = ReglaFinConversacion.para_sesion(session)
            fin_por_frase = (
                regla_fin is not None
                and regla_fin.detectar_por_frase(message_text or '')
            )
            detectar_fin_llm = (
                regla_fin is not None
                and regla_fin.usar_senal_llm
            )

            whatsapp_service.send_presence_update(
                conversation.sesion.session_id, contacto.from_number
            )
            try:
                if message_type == 'audio' and not es_reintento:
                    whatsapp_service.send_text_message(
                        conversation.sesion.session_id, contacto.from_number, 'Procesando...', simularEscritura=True
                    )
                    message_text = whatsapp_service.sync_transcribe_audio(message) or ''
                    if message_text:
                        whatsapp_service.send_text_message(
                            conversation.sesion.session_id, contacto.from_number,
                            f'Audio recibido: {message_text}', simularEscritura=True
                        )
                    else:
                        whatsapp_service.send_text_message(
                            conversation.sesion.session_id, contacto.from_number,
                            'No pude transcribir el audio. ¿Podrías escribir tu consulta? 🙏',
                            simularEscritura=True,
                        )
                        return JsonResponse({'status': 'ok', 'transcripcion_vacia': True})
                    whatsapp_service.send_presence_update(
                        conversation.sesion.session_id, contacto.from_number
                    )
                vs_path = agente.vectorstore_path and os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path) or ''
                # Enlaces API (tipo=1) se inyectan ahora al vuelo vía fetch_contexto_apis
                # dentro de AgenteConsultor._construir_contexto — sin embeddings.
                # Si hay un vectorstore_enlaces_path pre-existente, se sigue cargando
                # como respaldo para búsqueda semántica.
                vectorstore_enlaces_path = (
                    os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path)
                    if agente.vectorstore_enlaces_path else ''
                )
                respuesta_enviada = False
                resultado = None
                _keys_activas_qs = agente.apikey.filter(estado=True)
                if not _keys_activas_qs.exists():
                    _traza(
                        etapa='sin_respuesta', sesion=session, conversacion=conversation, mensaje=message,
                        numero=from_number, nivel='error',
                        detalle=f'Agente "{agente.nombre}" (id={agente.id}) no tiene API Keys activas.',
                    )
                    notificar_superusers_error(
                        titulo=f'Agente IA sin API Keys activas — {agente.nombre}',
                        cuerpo=(
                            f'El agente <strong>{agente.nombre}</strong> (id {agente.id}) recibió un mensaje '
                            f'de <strong>{from_number}</strong> pero no tiene ninguna API Key activa. '
                            f'Revisa la configuración del agente o las keys desactivadas automáticamente.'
                        ),
                        url=f'/whatsapp/trazas/?numero={from_number}&solo_problemas=1',
                        cache_key=f'ia_sin_keys_agente_{agente.id}',
                        cooldown_segundos=1800,
                    )
                    if fallback_permitido(conversation.id):
                        whatsapp_service.send_text_message(
                            conversation.sesion.session_id, contacto.from_number,
                            'Lo siento, en este momento no puedo procesar tu consulta. Por favor escribe *reintentar* en unos momentos o contacta a un asesor.'
                        )
                    _keys_activas_qs = []  # salta el loop siguiente
                for apikey in _keys_activas_qs:
                    import time as _time
                    _t0 = _time.time()
                    try:
                        from agents_ai.agente_consultor import AgenteConsultor
                        _prompt_tpl = (agente.prompt_template or '').strip()
                        if not _prompt_tpl:
                            _prompt_tpl = PROMPT_TEMPLATES.get('es', '')
                        consultor = AgenteConsultor(
                            vectorstore_path=vs_path, vectorstore_enlaces_path=vectorstore_enlaces_path,
                            provider=apikey.proveedor, apikey=apikey.descripcion,
                            model_name=(apikey.modelo or None),  # vacío → default del provider
                            conversacion=conversation, prompt_template_text=_prompt_tpl,
                            contexto_estatico=agente.contexto_estatico or None,
                            detectar_fin=detectar_fin_llm,
                            perfil=agente.perfil,
                            agente=agente,
                        )
                        _traza(
                            etapa='llm_invocado', sesion=session, conversacion=conversation, mensaje=message,
                            numero=from_number, nivel='info',
                            detalle={'provider': apikey.proveedor, 'apikey_id': apikey.id, 'modelo': getattr(consultor, 'model_name', '')},
                        )
                        if agente.requiere_tools():
                            resultado = consultor.consultar_con_listas(message_text, agente.descripcion)
                        else:
                            resultado = consultor.consultar(message_text, agente.descripcion)
                        _lat_llm = int((_time.time() - _t0) * 1000)
                        _traza(
                            etapa='llm_respondio', sesion=session, conversacion=conversation, mensaje=message,
                            numero=from_number, nivel='success', latencia_ms=_lat_llm,
                            detalle={
                                'preview': (resultado.respuesta or '')[:300],
                                'tokens_total': getattr(resultado, 'tokens_total', 0),
                                'apikey_id': apikey.id,
                            },
                        )
                        # ── Envío humanizado (burbujas + delays) ──────────────
                        # Si humanizar_timing está desactivado, manda todo en una sola burbuja sin sleeps.
                        _humanizar = bool(getattr(agente, 'humanizar_timing', True))
                        if _humanizar:
                            from agents_ai.humanizacion import (
                                dividir_en_burbujas, calcular_delays,
                                params_burbujas_desde_agente, params_delays_desde_agente,
                            )
                            _params_burbujas = params_burbujas_desde_agente(agente)
                            _params_delays   = params_delays_desde_agente(agente)
                            burbujas = dividir_en_burbujas(resultado.respuesta or '', **_params_burbujas)
                        else:
                            burbujas = [resultado.respuesta or '']
                            _params_delays = {}

                        import time as _timing
                        _send_ok = False
                        _ultimo_send = None
                        # La primera "previa" es el mensaje del cliente; luego es la burbuja anterior del bot.
                        _previa = message_text or ''
                        for _idx, _burbuja in enumerate(burbujas):
                            if _humanizar:
                                _lectura, _escritura = calcular_delays(_burbuja, _previa, **_params_delays)
                                if _lectura > 0:
                                    _timing.sleep(_lectura)
                                try:
                                    whatsapp_service.send_presence_update(
                                        conversation.sesion.session_id, contacto.from_number
                                    )
                                except Exception:
                                    pass
                                _timing.sleep(_escritura)
                            _ultimo_send = whatsapp_service.send_text_message(
                                conversation.sesion.session_id, contacto.from_number, _burbuja
                            )
                            _ok_actual = isinstance(_ultimo_send, dict) and _ultimo_send.get('success')
                            _send_ok = _send_ok or _ok_actual
                            _traza(
                                etapa='mensaje_enviado' if _ok_actual else 'envio_fallido',
                                sesion=session, conversacion=conversation, mensaje=message,
                                numero=from_number, nivel='success' if _ok_actual else 'error',
                                detalle={
                                    'burbuja': _idx + 1,
                                    'total_burbujas': len(burbujas),
                                    'message_id': _ultimo_send.get('message_id') if isinstance(_ultimo_send, dict) else None,
                                    'error': _ultimo_send.get('error') if isinstance(_ultimo_send, dict) else None,
                                },
                            )
                            # Persistir cada burbuja como mensaje IA (el webhook de echo
                            # detecta el mensaje_id_externo y evita duplicar).
                            try:
                                MensajeWhatsApp.objects.create(
                                    conversacion=conversation,
                                    remitente=session.numero,
                                    mensaje=_burbuja,
                                    tipo='texto',
                                    fecha=timezone.now(),
                                    mensaje_id_externo=_ultimo_send.get('message_id') if isinstance(_ultimo_send, dict) else None,
                                    leido=True,
                                    fecha_leido=timezone.now(),
                                    ia_generado=True,
                                    es_automatico=True,
                                )
                            except Exception:
                                pass
                            _previa = _burbuja
                        send_result = _ultimo_send
                        respuesta_enviada = True
                        # ── Registrar consumo de tokens ──────────────────────
                        if resultado.tokens_total > 0:
                            try:
                                from crm.alertas_consumo import verificar_alerta_consumo
                                ConsumoTokenIA.objects.create(
                                    apikey=apikey, agente=agente,
                                    conversacion=conversation,
                                    tokens_entrada=resultado.tokens_entrada,
                                    tokens_salida=resultado.tokens_salida,
                                    tokens_total=resultado.tokens_total,
                                    modelo=consultor.model_name,
                                    origen='whatsapp',
                                    prompt_preview=(message_text or '')[:300],
                                )
                                verificar_alerta_consumo(apikey, resultado.tokens_total)
                            except Exception:
                                pass
                        break
                    except Exception as ex:
                        logger.error("API Key %s falló para agente %s: %s", apikey.id, agente.nombre, ex)
                        _traza(
                            etapa='llm_error', sesion=session, conversacion=conversation, mensaje=message,
                            numero=from_number, nivel='error', latencia_ms=int((_time.time() - _t0) * 1000),
                            detalle={'apikey_id': apikey.id, 'provider': apikey.proveedor, 'error': str(ex)[:1500]},
                        )
                        # Solo desactivar la key si el error es de autenticación/cuota de la API,
                        # no por bugs propios del código (NameError, AttributeError, etc.)
                        _es_error_api = any(
                            kw in str(ex).lower()
                            for kw in ('api key', 'invalid api', 'quota', 'unauthorized', '401', '403',
                                       'permission denied', 'api_key', 'authentication')
                        )
                        if not _es_error_api:
                            # Bug de código: avisar a superusers (la key NO se deshabilita y el admin necesita ver la traza)
                            notificar_superusers_error(
                                titulo=f'Bug en pipeline IA — Agente "{agente.nombre}"',
                                cuerpo=(
                                    f'El agente <strong>{agente.nombre}</strong> (id {agente.id}) '
                                    f'falló al responder a <strong>{from_number}</strong>.<br>'
                                    f'<small>Error: {str(ex)[:300]}</small><br>'
                                    f'<small>API Key id {apikey.id} ({apikey.get_proveedor_display()})</small>'
                                ),
                                url=f'/whatsapp/trazas/?numero={from_number}&solo_problemas=1',
                                cache_key=f'ia_bug_agente_{agente.id}_apikey_{apikey.id}',
                                cooldown_segundos=1800,
                            )
                        if _es_error_api:
                            apikey.estado = False
                            apikey.msgerror = str(ex)[:500]
                            apikey.save()
                            try:
                                notificacion(
                                    titulo=f'Error en API Key — Agente "{agente.nombre}"',
                                    cuerpo=(
                                        f'La API Key <strong>{apikey.alias or apikey.get_proveedor_display()}</strong> '
                                        f'(ID {apikey.id}) falló y fue desactivada automáticamente.<br>'
                                        f'<small>{str(ex)[:300]}</small>'
                                    ),
                                    destinatario=session.usuario,
                                    url='/crm/entrenamiento/',
                                    prioridad=1,
                                    tipo=4,
                                )
                            except Exception:
                                pass
                        else:
                            # Error de código — solo loguear, no deshabilitar la key
                            apikey.msgerror = str(ex)[:500]
                            apikey.save(update_fields=['msgerror'])
                        continue
                if not respuesta_enviada and _keys_activas_qs:
                    _traza(
                        etapa='sin_respuesta', sesion=session, conversacion=conversation, mensaje=message,
                        numero=from_number, nivel='error',
                        detalle='Ningun API Key del agente logro responder (ver trazas llm_error previas).',
                    )
                    notificar_superusers_error(
                        titulo=f'Ninguna API Key respondió — Agente "{agente.nombre}"',
                        cuerpo=(
                            f'Todas las API Keys activas del agente <strong>{agente.nombre}</strong> '
                            f'(id {agente.id}) fallaron al responder a <strong>{from_number}</strong>. '
                            f'Abre las trazas filtradas y revisa los errores <code>llm_error</code> previos '
                            f'para diagnosticar el problema (cuota, bug, red).'
                        ),
                        url=f'/whatsapp/trazas/?numero={from_number}&solo_problemas=1',
                        cache_key=f'ia_sin_respuesta_conv_{conversation.id}',
                        cooldown_segundos=900,
                    )
                    if fallback_permitido(conversation.id):
                        whatsapp_service.send_text_message(
                            conversation.sesion.session_id, contacto.from_number,
                            'Lo siento, en este momento no puedo procesar tu consulta. Por favor escribe *reintentar* en unos momentos o contacta a un asesor.'
                        )

                # ── Fin de conversación detectado ─────────────────────────
                fin_detectado = fin_por_frase or (resultado is not None and resultado.fin_detectado)
                if fin_detectado and regla_fin and respuesta_enviada:
                    try:
                        conversation.conversacion_finalizada = True
                        conversation.save(update_fields=['conversacion_finalizada'])
                        contexto_fin = {
                            'nombre_contacto': contacto.contacto_nombre or '',
                            'numero': contacto.contacto_numero or '',
                            'sesion': session.nombre or session.session_id,
                            'sesion_id': session.session_id,
                            'resumen': conversation.resumen_conversacion or '',
                            'agente': agente.nombre,
                        }
                        ejecutar_acciones_fin(regla_fin, contexto_fin)
                    except Exception:
                        logger.exception("Error procesando fin de conversación conv_id=%s", conversation.id)

            except Exception as ex:
                logger.error("Error inesperado en agente IA para sesión %s: %s", session.session_id, ex, exc_info=True)
                _traza(
                    etapa='error_general', sesion=session, conversacion=conversation, mensaje=message,
                    numero=from_number, nivel='error',
                    detalle=str(ex)[:2000],
                )
                whatsapp_service.send_text_message(
                    conversation.sesion.session_id, contacto.from_number,
                    'Lo siento, ocurrió un error inesperado. Escribe *reintentar* para volver a intentarlo.'
                )
            finally:
                whatsapp_service.quit_presence_update(
                    conversation.sesion.session_id, contacto.from_number
                )
        elif departamentos and conversation.estado_mensaje == 'MENU_DEPARTAMENTOS':
            departamentos_msg += '\n'.join([f'{get_numero_emoji_ws(x.numero_opcion)}. {x.nombre}' for x in departamentos])
            departamento = departamentos.filter(numero_opcion=numero_opcion_respondido).first()
            if primer_mensaje:
                whatsapp_service.send_text_message(
                    conversation.sesion.session_id, contacto.from_number,
                    departamentos_msg, not primer_mensaje
                )
            elif not departamento:
                whatsapp_service.send_text_message(
                    conversation.sesion.session_id, contacto.from_number,
                    departamentos_msg, not primer_mensaje
                )
            elif departamento:
                opcionesdepartamento = departamento.opciondepartamentochatbot_set.filter(opcion_padre__isnull=True).annotate(
                    numero_opcion=Window(
                        expression=RowNumber(),
                        order_by='orden'
                    )
                )
                opciones_msg = f'{departamento.mensaje_saludo}\n'
                opciones_msg += "\n".join([f'{get_numero_emoji_ws(x.numero_opcion)}. {x.nombre}' for x in opcionesdepartamento])
                whatsapp_service.send_text_message(
                    conversation.sesion.session_id, contacto.from_number,
                    opciones_msg, True
                )
                if opcionesdepartamento:
                    conversation.estado_mensaje = 'DEPARTAMENTO_ESCOGIDO'
                    conversation.modelo = departamento
                else:
                    conversation.estado_mensaje = 'MENU_DEPARTAMENTOS'
                    conversation.modelo = None
                conversation.save()
        elif conversation.estado_mensaje == 'DEPARTAMENTO_ESCOGIDO':
            departamento = conversation.modelo
            opcionesdepartamento = departamento.opciondepartamentochatbot_set.filter(opcion_padre__isnull=True).annotate(
                numero_opcion=Window(
                    expression=RowNumber(),
                    order_by='orden'
                )
            )
            opcion = opcionesdepartamento.filter(numero_opcion=numero_opcion_respondido).first()
            if opcion:
                subopciones = opcion.subopciones.all().annotate(
                    numero_opcion=Window(
                        expression=RowNumber(),
                        order_by='orden'
                    )
                )
                msg = f'{opcion.respuesta}\n'
                msg += "\n".join([f'{get_numero_emoji_ws(x.numero_opcion)}. {x.nombre}' for x in subopciones])
                whatsapp_service.send_text_message(
                    conversation.sesion.session_id, contacto.from_number,
                    msg, True
                )
                if subopciones:
                    conversation.estado_mensaje = 'OPCION_ESCOGIDA'
                    conversation.modelo = opcion
                else:
                    conversation.estado_mensaje = 'MENU_DEPARTAMENTOS'
                    conversation.modelo = None
                conversation.save()
        elif conversation.estado_mensaje == 'OPCION_ESCOGIDA':
            opcion = conversation.modelo
            opciones = opcion.subopciones.annotate(
                numero_opcion=Window(
                    expression=RowNumber(),
                    order_by='orden'
                )
            )
            opcion = opciones.filter(numero_opcion=numero_opcion_respondido).first()
            if opcion:
                subopciones = opcion.subopciones.all().annotate(
                    numero_opcion=Window(
                        expression=RowNumber(),
                        order_by='orden'
                    )
                )
                msg = f'{opcion.respuesta}\n'
                msg += "\n".join([f'{get_numero_emoji_ws(x.numero_opcion)}. {x.nombre}' for x in subopciones])
                whatsapp_service.send_text_message(
                    conversation.sesion.session_id, contacto.from_number,
                    msg, True
                )
                if subopciones:
                    conversation.estado_mensaje = 'OPCION_ESCOGIDA'
                    conversation.modelo = opcion
                else:
                    conversation.estado_mensaje = 'MENU_DEPARTAMENTOS'
                    conversation.modelo = None
                conversation.save()




            # Notificar a través de WebSockets
        async_to_sync(channel_layer.group_send)(
            f"chat_{conversation.id}",
            {
                'type': 'whatsapp_message',
                'event': 'new_message',
                'conversation_id': conversation.id,
                'message_id': message.id,
                'message_type': message_type,
                'message_text': message_text,
                'sender': from_number,
                'timestamp': message_date.isoformat()
            }
        )

        async_to_sync(channel_layer.group_send)(
            f"whatsapp_sessionroom_{session.id}",
            {
                'type': 'whatsapp_event',
                'event': 'new_message',
                'conversation_id': conversation.id,
                'from_me': False,
                'timestamp': message_date.isoformat()
            }
        )

        logger.info(f"Mensaje recibido de {from_number} en la sesión {session.session_id}")

    except Exception as e:
        logger.exception(f"Error procesando mensaje entrante: {str(e)}")
        try:
            _traza(
                etapa='error_general',
                sesion=session,
                conversacion=locals().get('conversation'),
                mensaje=locals().get('message'),
                numero=locals().get('from_number'),
                nivel='error',
                detalle=f'process_incoming_message: {type(e).__name__}: {str(e)[:1500]}',
            )
        except Exception:
            pass


def save_media_file(media_base64, filename):
    try:
        file_data = base64.b64decode(media_base64)
        return ContentFile(file_data, filename)
    except Exception as e:
        logger.exception(f"Error guardando archivo multimedia: {str(e)}")
        return None


def update_conversation_stats(conversation):
    """
    Actualiza las estadísticas de una conversación en una sola query aggregate.
    """
    try:
        stats, _ = EstadisticasConversacion.objects.get_or_create(conversacion=conversation)

        contacto_numero = conversation.contacto_numero

        agg = MensajeWhatsApp.objects.filter(conversacion=conversation).aggregate(
            total=Count('id'),
            cliente=Count('id', filter=Q(remitente=contacto_numero)),
            automaticos=Count('id', filter=Q(es_automatico=True)),
            ia=Count('id', filter=Q(ia_generado=True)),
        )

        stats.total_mensajes = agg['total']
        stats.mensajes_cliente = agg['cliente']
        stats.mensajes_automaticos = agg['automaticos']
        stats.mensajes_ia = agg['ia']
        # Asesor = no-cliente y no-automático
        stats.mensajes_asesor = agg['total'] - agg['cliente'] - agg['automaticos']

        # Tiempo de primera respuesta (solo si hay mensajes de ambos lados)
        if agg['cliente'] > 0 and stats.mensajes_asesor > 0:
            first_client = (
                MensajeWhatsApp.objects
                .filter(conversacion=conversation, remitente=contacto_numero)
                .order_by('fecha')
                .values('fecha')
                .first()
            )
            if first_client:
                first_response = (
                    MensajeWhatsApp.objects
                    .filter(conversacion=conversation, fecha__gt=first_client['fecha'])
                    .exclude(remitente=contacto_numero)
                    .order_by('fecha')
                    .values('fecha')
                    .first()
                )
                if first_response:
                    stats.tiempo_primera_respuesta = (
                        first_response['fecha'] - first_client['fecha']
                    )

        stats.save()

    except Exception as e:
        logger.exception(f"Error actualizando estadísticas de conversación: {str(e)}")
        try:
            _traza(
                etapa='error_general',
                sesion=getattr(conversation, 'sesion', None) if 'conversation' in locals() else None,
                conversacion=locals().get('conversation'),
                nivel='error',
                detalle=f'update_conversation_stats: {type(e).__name__}: {str(e)[:1500]}',
            )
        except Exception:
            pass
