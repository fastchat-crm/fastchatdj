# whatsapp/views.py (webhook_handler)
from django.db.models import Count, Q, Window
from django.db.models.functions import RowNumber
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from django.utils import timezone
import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import base64
import os
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.conf import settings
from agents_ai.agente_consultor import AgenteConsultor
from crm.acciones_fin import ejecutar_acciones_fin
from crm.models import ReglaFinConversacion, ConsumoTokenIA
from core.funciones import save_log_entry, notificacion
from core.funciones_adicionales import get_image_as_base64, get_numero_emoji_ws
from .models import (
    SesionWhatsApp,
    ConversacionWhatsApp, Contacto,
    MensajeWhatsApp,
    EstadisticasConversacion
)
from .services import WhatsAppService

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def webhook_handler(request):
    """
    Manejador de webhooks para eventos de WhatsApp
    """
    # Verificar la clave API
    whatsapp_service = WhatsAppService()
    try:
        # Parsear los datos recibidos

        data = json.loads(request.body)
        event_type = data.get('type')
        event_data = data.get('data', {})
        session_id = event_data.get('sessionId')
        conversacion_id = event_data.get('conversacion_id')
        msgerror = ''

        # Obtener la sesión
        try:
            session = SesionWhatsApp.objects.get(session_id=session_id)
        except SesionWhatsApp.DoesNotExist:
            logger.error(f"Sesión no encontrada: {session_id}")
            whatsapp_service.close_session(session_id)
            return JsonResponse({'message': 'Sesión no encontrada'}, status=404)

        # Obtener el channel layer para notificaciones en tiempo real
        channel_layer = get_channel_layer()

        # Procesar el evento según su tipo
        if event_type == 'qr_code':
            # Actualizar el código QR en la sesión
            session.qr_code = event_data.get('qrCode')
            session.estado = 'pendiente'
            session.save()

            save_log_entry(f'HS: SESION {session_id} QR CODE GENERADO', request, event_type, obj=session)

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'qr_code',
                    'session_id': session.id,
                    'qr_code': session.qr_code
                }
            )

            logger.info(f"Código QR actualizado para la sesión {session_id}")

        elif event_type == 'ready':
            guardar = True
            # Guardar información del usuario si está disponible
            if 'user' in event_data:
                user_info = event_data.get('user', {})
                if 'userImage' in event_data and event_data.get('userImage'):
                    session.foto = f'data:image/jpg;base64,{get_image_as_base64(event_data.get("userImage"))}'
                if 'id' in user_info:
                    numero_list = []
                    for x in user_info['id']:
                        if not x.isdigit():
                            break
                        numero_list.append(x)
                    numero = "".join(numero_list)
                    whatsapp_id = user_info['id']
                    if session.numero and session.numero != numero:
                        guardar = False
                        msgerror = 'No puede registrar otra cuenta de whatsapp en esta sesión'
                    if guardar:
                        session.numero = numero
                        session.whatsapp_id = whatsapp_id
                        if not session.nombre:
                            session.nombre = user_info.get('pushName') or user_info.get('verifiedBizName') or user_info.get('name') or user_info.get('notify') or user_info.get('verifiedName') or ''

            if guardar:
                session.estado = 'conectado'
                session.ultima_conexion = timezone.now()
                session.error_mensaje = None
                session.save()

                save_log_entry(f'HS: SESION {session_id} READY', request, event_type, obj=session)

                # Notificar a través de WebSockets
                async_to_sync(channel_layer.group_send)(
                    f"whatsapp_session_{session.id}",
                    {
                        'type': 'whatsapp_event',
                        'event': 'ready',
                        'session_id': session.id
                    }
                )

                logger.info(f"Sesión {session_id} conectada correctamente")
            else:
                async_to_sync(channel_layer.group_send)(
                    f"whatsapp_session_{session.id}",
                    {
                        'type': 'whatsapp_event',
                        'event': 'error',
                        'session_id': session.id,
                        'msgerror': msgerror
                    }
                )
                whatsapp_service.close_session(session.session_id)

        elif event_type == 'authenticated':
            # Actualizar el estado de la sesión
            session.estado = 'conectado'
            session.ultima_conexion = timezone.now()
            session.error_mensaje = None
            session.save()

            save_log_entry(f'HS: SESION {session_id} authenticated'.upper(), request, event_type, obj=session)

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'authenticated',
                    'session_id': session.id
                }
            )

            logger.info(f"Sesión {session_id} autenticada")

        elif event_type == 'contacts_list':
            contacts_list = json.loads(session.contacts_list or '[]')
            new_contacts_list = []
            ids = [x["id"] for x in event_data.get('contacts_list') or []]
            numbers = ["".join([y for y in x["id"] if y.isdigit()]) for x in event_data.get('contacts_list') or []]
            for c in contacts_list:
                if not c["id"] in ids:
                    if numbers and c.get("contacto_numero") and c['contacto_numero'] in numbers:
                        continue
                    new_contacts_list.append(c)
            contacts_list = new_contacts_list + event_data.get('contacts_list') or []
            new_contacts_list = []
            for i, c in enumerate(contacts_list):
                contacts_list[i]['contacto_numero'] = contacto_numero = "".join([y for y in (c.get('id') or '') if y.isdigit()])
                if contacto_numero:
                    new_contacts_list.append(contacts_list[i])
            session.contacts_list = json.dumps(new_contacts_list)
            session.contacts_length = len(new_contacts_list)
            session.save()

        elif event_type == 'auth_failure':
            # Actualizar el estado de la sesión
            session.estado = 'error'
            session.error_mensaje = "Error de autenticación"
            session.save()

            save_log_entry(f'HS: SESION {session_id} auth_failure'.upper(), request, event_type, obj=session)

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'auth_failure',
                    'session_id': session.id,
                    'error': session.error_mensaje,
                    'msgerror': msgerror
                }
            )

            logger.error(f"Error de autenticación en la sesión {session_id}")

        elif event_type == 'disconnected':
            # Actualizar el estado de la sesión
            session.estado = 'desconectado'
            session.desconectado_manualmente = False  # desconexión inesperada → reconectable
            session.save()

            save_log_entry(f'HS: SESION {session_id} disconnected'.upper(), request, event_type, obj=session)

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_session_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'disconnected',
                    'session_id': session.id,
                    'reason': event_data.get('reason', 'unknown'),
                    'msgerror': msgerror
                }
            )

            logger.info(f"Sesión {session_id} desconectada")

        elif event_type == 'message':
            if session.estado != 'conectado':
                session.estado = 'pendiente'
                session.save()
            # Procesar mensaje entrante
            if event_data.get('message') and event_data['message'].get('protocolMessage') and event_data['message']['protocolMessage'].get('type') == 'MESSAGE_EDIT':
                process_edited_message(session, event_data['message']['protocolMessage'], event_data['from'], channel_layer)
            elif event_data.get('message') and event_data['message'].get('editedMessage') and event_data['message']['editedMessage']['message']['protocolMessage'].get('type') == 'MESSAGE_EDIT':
                process_edited_message(session, event_data['message']['editedMessage']['message']['protocolMessage'], event_data['from'], channel_layer)
            elif event_data.get('message') and event_data['message'].get('protocolMessage') and event_data['message']['protocolMessage'].get('type') == 'REVOKE':
                process_deleted_message(session, event_data, channel_layer)
            elif event_data.get('fromMe'):
                process_sent_message(session, event_data, channel_layer)
            else:
                process_incoming_message(session, event_data, channel_layer)

        elif event_type == 'message_sent':
            if session.estado != 'conectado':
                session.estado = 'pendiente'
                session.save()
            # Procesar mensaje enviado
            process_sent_message(session, event_data, channel_layer)

        elif event_type == 'message_deleted':
            if session.estado != 'conectado':
                session.estado = 'pendiente'
                session.save()
            # Procesar mensaje eliminado
            process_deleted_message(session, event_data, channel_layer)

        # elif event_type == 'contact_update':
        #     # Procesar actualización de contacto
        #     process_contact_update(session, event_data, channel_layer)

        elif event_type == 'profile_update':
            # Procesar actualización de perfil
            process_profile_update(session, event_data, channel_layer)

        # Responder con éxito
        return JsonResponse({'message': 'Evento procesado correctamente'})

    except json.JSONDecodeError:
        logger.error("Error al decodificar JSON del webhook")
        return JsonResponse({'message': 'JSON inválido'}, status=400)
    except Exception as e:
        logger.exception(f"Error procesando webhook: {str(e)}")
        return JsonResponse({'message': f'Error: {str(e)}'}, status=500)

def construir_chat_history(conversacion, from_number, numero_agente, max_pares=5, max_chars=1000):
    chat_history = []
    pregunta_actual, respuesta_actual = "", ""

    mensajes = MensajeWhatsApp.objects.filter(conversacion=conversacion).order_by("id")

    for m in mensajes:
        if m.remitente == from_number:
            if respuesta_actual:
                chat_history.append((pregunta_actual.strip(), respuesta_actual.strip()))
                pregunta_actual, respuesta_actual = "", ""
            pregunta_actual += f"\n{m.mensaje}"
        elif m.remitente == numero_agente:
            respuesta_actual += f"\n{m.mensaje}"

    if pregunta_actual and respuesta_actual:
        chat_history.append((pregunta_actual.strip(), respuesta_actual.strip()))

    # Filtra pares vacíos y limita longitud por seguridad
    chat_history = [
        (q[:max_chars], a[:max_chars])
        for q, a in chat_history if q.strip() and a.strip()
    ]

    # Limita al máximo de pares permitidos
    return chat_history[-max_pares:]

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

        # Actualizar nombre del contacto si está disponible
        if not contacto.contacto_nombre:
            contacts_list = [c.get('name') or c.get('notify') or '' for c in json.loads(session.contacts_list or '[]') if c["id"] == from_number]
            contacto.contacto_nombre = push_name
            if contacts_list and contacts_list[0]:
                contacto.contacto_nombre = contacts_list[0]
        if not contacto.contacto_numero:
            contacto.contacto_numero = contacto_numero

        if userImage:
            contacto.contacto_foto = f'data:image/jpg;base64,{get_image_as_base64(userImage)}'

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

        # Procesar archivos multimedia
        media_types = {
            'imageMessage': ('imagen', 'fileName', 'mimetype', 'caption'),
            'videoMessage': ('video', 'fileName', 'mimetype', 'caption'),
            'audioMessage': ('audio', 'fileName', 'mimetype', None),
            'documentMessage': ('documento', 'fileName', 'mimetype', 'caption'),
            'stickerMessage': ('sticker', None, 'mimetype', None)
        }

        for media_key, (type_name, filename_key, mimetype_key, caption_key) in media_types.items():
            if media_key in message_content:
                media_msg = message_content.get(media_key, {})
                message_type = type_name

                # Obtener el texto del caption si existe
                if caption_key and caption_key in media_msg:
                    message_text = media_msg.get(caption_key, '') or type_name or ''

                message_text = message_text or type_name

                # Procesar archivo multimedia si hay datos
                if 'mediaData' in event_data and event_data.get('mediaData'):
                    media_data = event_data['mediaData']
                    filename = media_msg.get(filename_key, f"{type_name}_{message_id}")

                    # Guardar el archivo
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

        conversation = ConversacionWhatsApp.objects.sin_expirar.filter(contacto=contacto).first() or \
                       ConversacionWhatsApp.objects.create(contacto=contacto)

        # Renovar ventana de expiración con cada mensaje entrante del cliente
        if from_number != session.numero:  # sólo mensajes del cliente
            min_sesion = getattr(session, 'min_sesion', None)
            if min_sesion:
                from datetime import timedelta
                conversation.fecha_hora_expira = timezone.now() + timedelta(minutes=int(min_sesion))
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

        # Actualizar estadísticas
        update_conversation_stats(conversation)

        whatsapp_service = WhatsAppService()
        primer_mensaje = not conversation.bienvenida_enviado
        numero_opcion_respondido = (message_text or '').replace(' ', '')
        numero_opcion_respondido = numero_opcion_respondido.isdigit() and numero_opcion_respondido or -1
        if not conversation.bienvenida_enviado:
            conversation.bienvenida_enviado = True
            conversation.save()
            if conversation.sesion.mensaje_bienvenida and not (session.agente_ia and session.agente_ia.apikey.exists()):
                whatsapp_service.send_text_message(conversation.sesion.session_id, contacto.from_number, conversation.sesion.mensaje_bienvenida, simularEscritura=True)
        departamentos = conversation.sesion.departamentos.all().annotate(
            numero_opcion=Window(
                expression=RowNumber(),
                order_by='id'
            )
        )
        departamentos_msg = 'Escribe el número del departamento para continuar:\n'
        if session.agente_ia and session.agente_ia.apikey.exists() and conversation.ai_activo:
            agente = session.agente_ia

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
                        conversation.sesion.session_id, contacto.from_number, 'Procesando...', True
                    )
                    message_text = whatsapp_service.sync_transcribe_audio(message)
                    whatsapp_service.send_text_message(
                        conversation.sesion.session_id, contacto.from_number, f'Audio recibido: {message_text}', True
                    )
                    whatsapp_service.send_presence_update(
                        conversation.sesion.session_id, contacto.from_number
                    )
                vs_path = agente.vectorstore_path and os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path) or ''
                vectorstore_enlaces_path = ''
                agente.build_enlaces_vectorstore()
                if agente.vectorstore_enlaces_path:
                    vectorstore_enlaces_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path)
                respuesta_enviada = False
                resultado = None
                for apikey in agente.apikey.filter(estado=True):
                    try:
                        consultor = AgenteConsultor(
                            vectorstore_path=vs_path, vectorstore_enlaces_path=vectorstore_enlaces_path,
                            provider=apikey.proveedor, apikey=apikey.descripcion,
                            conversacion=conversation, prompt_template_text=agente.prompt_template,
                            contexto_estatico=agente.contexto_estatico or None,
                            detectar_fin=detectar_fin_llm,
                        )
                        if agente.anotar_listas:
                            resultado = consultor.consultar_con_listas(message_text, agente.descripcion)
                        else:
                            resultado = consultor.consultar(message_text, agente.descripcion)
                        send_result = whatsapp_service.send_text_message(
                            conversation.sesion.session_id, contacto.from_number, resultado.respuesta
                        )
                        respuesta_enviada = True
                        # Crear mensaje IA inmediatamente para que el webhook no lo duplique sin el flag
                        try:
                            MensajeWhatsApp.objects.create(
                                conversacion=conversation,
                                remitente=session.numero,
                                mensaje=resultado.respuesta,
                                tipo='texto',
                                fecha=timezone.now(),
                                mensaje_id_externo=send_result.get('message_id') if isinstance(send_result, dict) else None,
                                leido=True,
                                fecha_leido=timezone.now(),
                                ia_generado=True,
                                es_automatico=True,
                            )
                        except Exception:
                            pass
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
                                )
                                verificar_alerta_consumo(apikey, resultado.tokens_total)
                            except Exception:
                                pass
                        break
                    except Exception as ex:
                        logger.error("API Key %s falló para agente %s: %s", apikey.id, agente.nombre, ex)
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
                        continue
                if not respuesta_enviada:
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
                logger.error("Error inesperado en agente IA para sesión %s: %s", session.session_id, ex)
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

def process_sent_message(session, event_data, channel_layer):
    """
    Procesa un mensaje enviado a través de WhatsApp
    """
    try:
        print('process_sent_message', event_data)
        # Extraer datos del mensaje
        message_id = event_data.get('messageId') or event_data.get('id')
        from_number = event_data.get('to') or event_data.get('from')
        to_number = from_number.split('@')[0]
        message_data = event_data.get('message', {})
        message_content = event_data.get('message', {})
        conversacion_id = event_data.get('conversacion_id') or 0

        if session.numero == to_number:
            return

        # Buscar la conversación
        try:
            contacto = Contacto.objects.get(
                sesion=session,
                contacto_numero=to_number
            )
        except Contacto.DoesNotExist:
            # Crear una nueva conversación si no existe
            contacto = Contacto.objects.create(
                sesion=session,
                contacto_numero=to_number,
                from_number=from_number,
                estado='activo',
                fecha_ultimo_mensaje=timezone.now()
            )

        # Determinar el tipo y contenido del mensaje
        message_type = message_data.get('type', 'texto')
        message_text = message_data.get('caption', '') or message_data.get('text', '') or message_data.get('conversation', '')


        # Procesar texto
        if 'conversation' in message_content:
            message_type = 'texto'
            message_text = message_content.get('conversation', '')
        elif 'extendedTextMessage' in message_content:
            message_type = 'texto'
            message_text = message_content.get('extendedTextMessage', {}).get('text', '')

        file_url = None
        # Procesar archivos multimedia
        media_types = {
            'imageMessage': ('imagen', 'fileName', 'mimetype', 'caption'),
            'videoMessage': ('video', 'fileName', 'mimetype', 'caption'),
            'audioMessage': ('audio', 'fileName', 'mimetype', None),
            'documentMessage': ('documento', 'fileName', 'mimetype', 'caption'),
            'stickerMessage': ('sticker', None, 'mimetype', None)
        }

        for media_key, (type_name, filename_key, mimetype_key, caption_key) in media_types.items():
            if media_key in message_content:
                media_msg = message_content.get(media_key, {})
                message_type = type_name

                # Obtener el texto del caption si existe
                if caption_key and caption_key in media_msg:
                    message_text = media_msg.get(caption_key, '') or type_name or ''

                message_text = message_text or type_name

                # Procesar archivo multimedia si hay datos
                if 'mediaData' in event_data:
                    media_data = event_data.get('mediaData')
                    filename = media_msg.get(filename_key, f"{type_name}_{message_id}")

                    if media_key == 'stickerMessage':
                        filename = f'{filename}.png'

                    # Guardar el archivo
                    file_url = save_media_file(media_data, filename)

        # Actualizar la conversación
        contacto.ultimo_mensaje = message_text[:100] + ('...' if len(message_text) > 100 else '')
        contacto.fecha_ultimo_mensaje = timezone.now()
        contacto.save()

        # Guard de idempotencia: si ya procesamos este mensaje_id, no duplicar
        if message_id and MensajeWhatsApp.objects.filter(
            mensaje_id_externo=message_id, conversacion__contacto__sesion=session
        ).exists():
            logger.warning(f"Mensaje enviado duplicado ignorado: {message_id}")
            return

        conversation = ConversacionWhatsApp.objects.filter(id=conversacion_id).first() or\
                       ConversacionWhatsApp.objects.sin_expirar.filter(contacto=contacto).order_by('-id').first() or \
                       ConversacionWhatsApp.objects.create(contacto=contacto, fromMe=True)

        # Crear el mensaje
        message = MensajeWhatsApp.objects.create(
            conversacion=conversation,
            remitente=session.numero,  # El remitente es el número de la sesión
            mensaje=message_text,
            tipo=message_type,
            archivo=file_url,  # No tenemos la URL del archivo en este punto
            fecha=timezone.now(),
            mensaje_id_externo=message_id,
            leido=True,  # Marcamos como leído ya que lo enviamos nosotros
            fecha_leido=timezone.now()
        )

        if not conversation.bienvenida_enviado:
            conversation.bienvenida_enviado = True
            conversation.save()

        # Actualizar estadísticas
        update_conversation_stats(conversation)

        # Notificar a través de WebSockets
        async_to_sync(channel_layer.group_send)(
            f"chat_{conversation.id}",
            {
                'type': 'whatsapp_message',
                'event': 'message_sent',
                'conversation_id': conversation.id,
                'message_id': message.id,
                'message_type': message_type,
                'message_text': message_text,
                'sender': session.numero,
                'timestamp': timezone.now().isoformat()
            }
        )
        async_to_sync(channel_layer.group_send)(
            f"whatsapp_sessionroom_{session.id}",
            {
                'type': 'whatsapp_event',
                'event': 'new_message',
                'conversation_id': conversation.id,
                'from_me': True,
            }
        )

        logger.info(f"Mensaje enviado a {to_number} desde la sesión {session.session_id}")

    except Exception as e:
        logger.exception(f"Error procesando mensaje enviado: {str(e)}")

def process_deleted_message(session, event_data, channel_layer):
    """
    Procesa un mensaje eliminado en WhatsApp
    """
    try:
        # Extraer datos del mensaje
        message_id = event_data['message']['protocolMessage']['key']['id']
        chat = event_data['from']

        # Limpiar el número de teléfono
        if '@' in chat:
            chat = chat.split('@')[0]

        # Buscar el mensaje por su ID externo
        try:
            message = MensajeWhatsApp.objects.get(
                mensaje_id_externo=message_id,
                conversacion__sesion=session,
                conversacion__contacto_numero=chat
            )

            # Marcar como eliminado
            message.eliminado = True
            message.fecha_eliminacion = timezone.now()
            message.save()

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"chat_{message.conversacion.id}",
                {
                    'type': 'whatsapp_message',
                    'event': 'message_deleted',
                    'conversation_id': message.conversacion.id,
                    'message_id': message.id,
                    'external_message_id': message_id
                }
            )
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_sessionroom_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'new_message',
                    'conversation_id': message.conversacion.id
                }
            )

            logger.info(f"Mensaje {message_id} marcado como eliminado")

        except MensajeWhatsApp.DoesNotExist:
            logger.warning(f"No se encontró el mensaje {message_id} para marcar como eliminado")

    except Exception as e:
        logger.exception(f"Error procesando mensaje eliminado: {str(e)}")

def process_edited_message(session, event_data, fromchat, channel_layer):
    """
    Procesa un mensaje editado en WhatsApp
    """
    try:
        # Extraer datos del mensaje
        message_id = event_data['key']['id']
        chat = fromchat
        edited_message = event_data['editedMessage']

        # Limpiar el número de teléfono
        if '@' in chat:
            chat = chat.split('@')[0]

        # Buscar el mensaje por su ID externo
        try:
            message = MensajeWhatsApp.objects.get(
                mensaje_id_externo=message_id,
                conversacion__sesion=session,
                conversacion__contacto_numero=chat
            )

            # Guardar el mensaje original
            if not message.mensaje_original:
                message.mensaje_original = message.mensaje

            # Actualizar con el mensaje editado
            new_text = ''
            if 'conversation' in edited_message:
                new_text = edited_message.get('conversation', '')
            elif 'extendedTextMessage' in edited_message:
                new_text = edited_message.get('extendedTextMessage', {}).get('text', '')

            message.mensaje = new_text
            message.editado = True
            message.fecha_edicion = timezone.now()
            message.save()

            # Notificar a través de WebSockets
            async_to_sync(channel_layer.group_send)(
                f"chat_{message.conversacion.id}",
                {
                    'type': 'whatsapp_message',
                    'event': 'message_edited',
                    'conversation_id': message.conversacion.id,
                    'message_id': message.id,
                    'external_message_id': message_id,
                    'new_text': new_text,
                    'original_text': message.mensaje_original
                }
            )
            async_to_sync(channel_layer.group_send)(
                f"whatsapp_sessionroom_{session.id}",
                {
                    'type': 'whatsapp_event',
                    'event': 'new_message',
                    'conversation_id': message.conversacion.id
                }
            )

            logger.info(f"Mensaje {message_id} editado")

        except MensajeWhatsApp.DoesNotExist:
            logger.warning(f"No se encontró el mensaje {message_id} para editar")

    except Exception as e:
        logger.exception(f"Error procesando mensaje editado: {str(e)}")

def process_contact_update(session, event_data, channel_layer):
    """
    Procesa una actualización de contacto en WhatsApp
    """
    try:
        contact_data = event_data.get('contact', {})
        contact_id = contact_data.get('id', '')

        # Limpiar el ID del contacto
        if '@' in contact_id:
            contact_id = contact_id.split('@')[0]

        # Buscar conversaciones con este contacto
        contactos = Contacto.objects.filter(
            sesion=session,
            contacto_numero=contact_id
        )

        for contacto in contactos:
            # Actualizar nombre si está disponible
            if 'notify' in contact_data:
                contacto.contacto_nombre = contact_data.get('notify')
                contacto.save()

        logger.info(f"Contacto {contact_id} actualizado")

    except Exception as e:
        logger.exception(f"Error procesando actualización de contacto: {str(e)}")

def process_profile_update(session, event_data, channel_layer):
    """
    Procesa una actualización de perfil en WhatsApp
    """
    try:
        presence_data = event_data.get('presence', {})
        user_id = presence_data.get('id', '')

        # Limpiar el ID del usuario
        if '@' in user_id:
            user_id = user_id.split('@')[0]

        # Buscar conversaciones con este usuario
        contactos = Contacto.objects.filter(
            sesion=session,
            contacto_numero=user_id
        )

        logger.info(f"Perfil de {user_id} actualizado")

    except Exception as e:
        logger.exception(f"Error procesando actualización de perfil: {str(e)}")

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