"""Sender contra Meta Cloud API (Graph API).

Expone la misma interfaz publica que `whatsapp.services.WhatsAppService` para
que el resto del codigo sea agnostico al transporte. El dispatcher
`get_whatsapp_service(sesion)` en `services.py` devuelve esta clase o la de
Baileys segun `sesion.proveedor`.

Documentacion Meta:
    https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
"""
import json as _json_audit
import logging
import time as _time_audit

import requests
from django.db.models import F
from django.utils import timezone

from whatsapp.models import ConfigMeta, PlantillaWhatsApp, SesionWhatsApp

logger = logging.getLogger(__name__)


def _log_outbound(method: str, url: str, body=None, response=None,
                  started_at: float | None = None, nota: str = ''):
    """Registra un hit OUTBOUND a Graph API en MetaWebhookHit.

    Best-effort — nunca rompe el flujo del envio si la BD esta caida.
    Sanea body/response a strings <600 chars para preview.
    """
    try:
        from whatsapp.models import MetaWebhookHit

        # Body preview
        body_preview = ''
        body_length = 0
        if body is not None:
            if isinstance(body, (dict, list)):
                try:
                    body_str = _json_audit.dumps(body, ensure_ascii=False)
                except Exception:
                    body_str = repr(body)
            elif isinstance(body, bytes):
                body_str = body.decode('utf-8', errors='replace')
            else:
                body_str = str(body)
            body_length = len(body_str.encode('utf-8'))
            body_preview = body_str[:600]

        # Response preview + status
        status_code = 0
        response_preview = ''
        if response is not None:
            try:
                status_code = response.status_code
                response_preview = (response.text or '')[:600]
            except Exception:
                pass

        latencia_ms = None
        if started_at is not None:
            latencia_ms = max(0, int((_time_audit.time() - started_at) * 1000))

        MetaWebhookHit.objects.create(
            direccion='out',
            method=(method or '').upper()[:10],
            url=(url or '')[:500],
            status_code=status_code,
            body_length=body_length,
            body_preview=body_preview,
            response_preview=response_preview,
            latencia_ms=latencia_ms,
            nota=(nota or '')[:200],
        )
    except Exception:
        logger.exception("MetaWebhookHit outbound: fallo registrando (ignorando)")


import re as _re

# Emojis y caracteres de formato que Meta rechaza en headers/footers de plantillas.
# Meta exige headers en texto plano 1 linea, sin negritas, sin markdown, sin emojis.
# Ref: https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates#header
_EMOJI_RE = _re.compile(
    "["
    "\U0001F600-\U0001F64F"   # emoticons
    "\U0001F300-\U0001F5FF"   # simbolos y pictogramas
    "\U0001F680-\U0001F6FF"   # transporte y mapas
    "\U0001F1E0-\U0001F1FF"   # banderas
    "\U00002500-\U00002BEF"   # simbolos adicionales
    "\U00002702-\U000027B0"   # dingbats
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\U00010000-\U0010ffff"
    "\u2640-\u2642"
    "\u2600-\u2B55"
    "\u200d"
    "\u23cf"
    "\u23e9"
    "\u231a"
    "\ufe0f"                   # VS16 — forzador de render emoji
    "\u3030"
    "]+",
    flags=_re.UNICODE,
)

_FORMATO_MARKDOWN_RE = _re.compile(r'[\*_~`]')  # negrita / cursiva / tachado / monospace


def _sanitizar_header_meta(texto: str) -> str:
    """Limpia un string para cumplir reglas de HEADER/FOOTER de plantillas Meta:
    - Sin newlines (\\n, \\r, tab).
    - Sin formato markdown (*, _, ~, `).
    - Sin emojis.
    - Max 60 caracteres.
    Espacios multiples se colapsan a uno.
    """
    if not texto:
        return ''
    s = texto
    s = s.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    s = _EMOJI_RE.sub('', s)
    s = _FORMATO_MARKDOWN_RE.sub('', s)
    s = _re.sub(r'\s+', ' ', s).strip()
    return s[:60]

GRAPH_API_VERSION = 'v22.0'
GRAPH_API_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'


class MetaWhatsAppService:
    """Interfaz paralela a WhatsAppService pero contra Meta Cloud API.

    Los metodos aceptan `session_id` como primer parametro para mantener la
    firma compatible con el servicio Baileys. Para Meta, `session_id` se mapea
    a `SesionWhatsApp.session_id` (el ID agnostico que guardamos al conectar)
    y desde ahi se resuelve `ConfigMeta.phone_number_id` y `access_token`.
    """

    def _get_config(self, session_id: str) -> ConfigMeta | None:
        try:
            sesion = SesionWhatsApp.objects.select_related('config_meta').get(
                session_id=session_id
            )
        except SesionWhatsApp.DoesNotExist:
            logger.error("MetaService: sesion %s no existe", session_id)
            return None
        config = getattr(sesion, 'config_meta', None)
        if not config:
            logger.error("MetaService: sesion %s no tiene ConfigMeta (proveedor=%s)",
                         session_id, sesion.proveedor)
        return config

    def _headers(self, config: ConfigMeta) -> dict:
        return {
            'Authorization': f'Bearer {config.access_token}',
            'Content-Type':  'application/json',
        }

    def _normalizar_destinatario(self, to: str) -> str:
        """Meta quiere el numero plano sin '@s.whatsapp.net'. El resto del CRM
        usa el formato Baileys — lo limpiamos aqui."""
        if '@' in to:
            return to.split('@')[0]
        return to

    def _estado_cuenta_ok(self, config: ConfigMeta) -> tuple[bool, str | None]:
        """Chequea el estado de la WABA antes de intentar un envio.

        - quality_rating=RED: Meta esta a punto de suspender el numero o ya lo
          hizo parcialmente. Bloqueamos para no acelerar la degradacion.
        - YELLOW: pasa, pero queda registrado en la traza (el detalle lo nota).
        - GREEN/UNKNOWN: pasa sin ruido.

        Devuelve (ok, motivo). Fail-open si algun chequeo falla.
        """
        try:
            rating = (config.quality_rating or 'UNKNOWN').upper()
            if rating == 'RED':
                return False, 'quality_rating=RED: numero degradado por Meta, revisar calidad antes de enviar'
            return True, None
        except Exception as ex:
            logger.warning("Meta quality check fallo: %s", ex)
            return True, None

    def _dentro_ventana_24h(self, conversacion_id) -> tuple[bool, str | None]:
        """Meta prohibe contenido libre (texto/media) si han pasado >24h desde
        el ultimo mensaje entrante del cliente. Fuera de ventana hay que usar
        plantilla pre-aprobada (send_template).

        Devuelve (ok, motivo). Fail-open: si no se puede determinar, permite
        el envio para no romper llamadas legacy sin conversacion_id.
        """
        if not conversacion_id:
            return True, None
        try:
            from whatsapp.models import MensajeWhatsApp, ConversacionWhatsApp
            from django.utils import timezone
            from datetime import timedelta
            conv = (
                ConversacionWhatsApp.objects
                .filter(pk=conversacion_id)
                .select_related('contacto__sesion')
                .first()
            )
            if not conv:
                return True, None
            numero_sesion = (conv.contacto.sesion.numero or '').strip()
            ultimo_in = (
                MensajeWhatsApp.objects
                .filter(conversacion=conv)
                .exclude(remitente=numero_sesion)
                .order_by('-fecha')
                .first()
            )
            if not ultimo_in:
                return False, 'El cliente aún no ha enviado ningún mensaje. Para iniciar la conversación, envía una plantilla aprobada desde el botón 📋.'
            if timezone.now() - ultimo_in.fecha > timedelta(hours=24):
                return False, 'Ya pasaron más de 24 horas desde el último mensaje del cliente. Envía una plantilla aprobada desde el botón 📋.'
            return True, None
        except Exception as ex:
            logger.warning("Meta ventana24h check fallo: %s", ex)
            return True, None

    # -----------------------------------------------------------------------
    # API publica (espejo de WhatsAppService)
    # -----------------------------------------------------------------------

    def send_text_message(self, session_id, to, text, conversacion_id=None, simularEscritura=False):
        config = self._get_config(session_id)
        if not config:
            return {'success': False, 'error': 'config_meta_no_encontrada'}

        ok, motivo = self._estado_cuenta_ok(config)
        if not ok:
            return self._registrar_traza_bloqueo(
                config, to, 'text',
                {'success': False, 'error': motivo, 'cuenta_degradada': True},
                conversacion_id,
            )

        ok, motivo = self._dentro_ventana_24h(conversacion_id)
        if not ok:
            return self._registrar_traza_bloqueo(
                config, to, 'text',
                {'success': False, 'error': motivo, 'requiere_plantilla': True},
                conversacion_id,
            )

        data = {
            'messaging_product': 'whatsapp',
            'recipient_type':    'individual',
            'to':                self._normalizar_destinatario(to),
            'type':              'text',
            'text':              {'body': text, 'preview_url': True},
        }
        return self._post_mensaje(config, data, conversacion_id=conversacion_id)

    def send_template(self, session_id, to, plantilla_nombre, idioma='es', parametros_cuerpo=None, parametros_header=None, conversacion_id=None):
        """Envia una plantilla pre-aprobada. Esencial para iniciar conversaciones
        fuera de la ventana de 24h o para marketing/auth.

        Args:
            plantilla_nombre: nombre slug de la plantilla en Meta.
            idioma: codigo ISO (ej 'es', 'es_MX').
            parametros_cuerpo: lista de strings en orden {{1}}, {{2}}, ...
            parametros_header: lista de strings o dict con 'image_url', 'document_url', etc.
        """
        config = self._get_config(session_id)
        if not config:
            return {'success': False, 'error': 'config_meta_no_encontrada'}

        ok, motivo = self._estado_cuenta_ok(config)
        if not ok:
            return self._registrar_traza_bloqueo(
                config, to, 'template',
                {'success': False, 'error': motivo, 'cuenta_degradada': True},
                conversacion_id,
            )

        components = []
        if parametros_header:
            components.append({
                'type':       'header',
                'parameters': self._formatear_parametros(parametros_header),
            })
        if parametros_cuerpo:
            components.append({
                'type':       'body',
                'parameters': self._formatear_parametros(parametros_cuerpo),
            })

        data = {
            'messaging_product': 'whatsapp',
            'to':                self._normalizar_destinatario(to),
            'type':              'template',
            'template': {
                'name':       plantilla_nombre,
                'language':   {'code': idioma},
                'components': components,
            },
        }
        resultado = self._post_mensaje(config, data, conversacion_id=conversacion_id)

        if resultado.get('success'):
            PlantillaWhatsApp.objects.filter(
                config_meta=config, nombre=plantilla_nombre, idioma=idioma
            ).update(
                veces_enviada=F('veces_enviada') + 1,
                ultimo_envio=timezone.now(),
            )
        return resultado

    def _formatear_parametros(self, params) -> list:
        """Convierte parametros de usuario al formato que espera Meta.

        Acepta:
        - lista de strings (header TEXT o cuerpo): [{type:text, text:...}, ...]
        - dict con image_url / video_url / document_url / filename (header media)
        - lista de dicts ya formateados (pass-through)
        """
        if not params:
            return []
        if isinstance(params, list) and params and isinstance(params[0], str):
            return [{'type': 'text', 'text': str(p)} for p in params]
        if isinstance(params, dict):
            if params.get('image_url'):
                return [{'type': 'image', 'image': {'link': params['image_url']}}]
            if params.get('video_url'):
                return [{'type': 'video', 'video': {'link': params['video_url']}}]
            if params.get('document_url'):
                doc = {'link': params['document_url']}
                if params.get('filename'):
                    doc['filename'] = params['filename']
                return [{'type': 'document', 'document': doc}]
        return params  # ya viene con forma correcta

    def send_presence_update(self, session_id, to):
        """Meta no expone 'escribiendo...' via API publica, es no-op."""
        return {'success': True, 'skipped': 'not_supported_by_meta'}

    def quit_presence_update(self, session_id, to):
        return {'success': True, 'skipped': 'not_supported_by_meta'}

    def send_media_message(self, session_id, to, file_path=None, file_content=None,
                           caption=None, filename=None, media_type='image', media_url=None,
                           conversacion_id=None, **kwargs):
        """Envia media. Preferentemente por URL (mas simple). Si se pasa file_path
        o file_content, primero se sube a Meta via /media y se usa el media_id.

        `media_type` unifica la firma con WhatsAppService (Baileys). Valores
        aceptados: 'image', 'video', 'audio', 'document', 'sticker'. Por compat,
        tambien acepta `tipo=` como alias via kwargs.
        """
        # Alias legacy: 'tipo' era el nombre original en Meta.
        if 'tipo' in kwargs and kwargs['tipo']:
            media_type = kwargs['tipo']

        config = self._get_config(session_id)
        if not config:
            return {'success': False, 'error': 'config_meta_no_encontrada'}

        ok, motivo = self._estado_cuenta_ok(config)
        if not ok:
            return self._registrar_traza_bloqueo(
                config, to, media_type,
                {'success': False, 'error': motivo, 'cuenta_degradada': True},
                conversacion_id,
            )

        ok, motivo = self._dentro_ventana_24h(conversacion_id)
        if not ok:
            return self._registrar_traza_bloqueo(
                config, to, media_type,
                {'success': False, 'error': motivo, 'requiere_plantilla': True},
                conversacion_id,
            )

        if media_url:
            media_payload = {'link': media_url}
            if caption and media_type in ('image', 'video', 'document'):
                media_payload['caption'] = caption
            if filename and media_type == 'document':
                media_payload['filename'] = filename
            data = {
                'messaging_product': 'whatsapp',
                'to':                self._normalizar_destinatario(to),
                'type':              media_type,
                media_type:          media_payload,
            }
            return self._post_mensaje(config, data, conversacion_id=conversacion_id)

        if file_path or file_content:
            media_id = self._subir_media(config, file_path, file_content, filename, media_type)
            if not media_id:
                return {'success': False, 'error': 'upload_media_fallo'}
            media_payload = {'id': media_id}
            if caption and media_type in ('image', 'video', 'document'):
                media_payload['caption'] = caption
            if filename and media_type == 'document':
                media_payload['filename'] = filename
            data = {
                'messaging_product': 'whatsapp',
                'to':                self._normalizar_destinatario(to),
                'type':              media_type,
                media_type:          media_payload,
            }
            return self._post_mensaje(config, data, conversacion_id=conversacion_id)

        return {'success': False, 'error': 'falta_origen_media'}

    def descargar_media(self, session_id: str, media_id: str) -> bytes | None:
        """Meta entrega media por media_id; hay que hacer dos llamadas: primero
        resolver la URL de descarga, luego descargar los bytes autenticado."""
        config = self._get_config(session_id)
        if not config:
            return None
        try:
            meta_resp = requests.get(
                f'{GRAPH_API_BASE}/{media_id}', headers=self._headers(config), timeout=15,
            )
            if meta_resp.status_code != 200:
                logger.warning("Meta media GET meta %s: %s", media_id, meta_resp.status_code)
                return None
            url = meta_resp.json().get('url')
            if not url:
                return None
            bin_resp = requests.get(url, headers=self._headers(config), timeout=30)
            if bin_resp.status_code != 200:
                logger.warning("Meta media GET bin %s: %s", media_id, bin_resp.status_code)
                return None
            return bin_resp.content
        except Exception:
            logger.exception("Error descargando media %s", media_id)
            return None

    def close_session(self, session_id):
        """Meta no tiene concepto de 'cerrar sesion' — la WABA vive en sus
        servidores. No-op por compatibilidad con la interfaz Baileys."""
        return {'success': True, 'skipped': 'meta_session_managed_by_meta'}

    def get_user_image(self, session_id, to):
        """Meta no expone foto de perfil del contacto via API publica."""
        return {'success': False, 'skipped': 'not_supported_by_meta'}

    def sync_transcribe_audio(self, message):
        """La transcripcion la maneja el mismo helper que Baileys — reusamos."""
        from whatsapp.services import WhatsAppService
        return WhatsAppService().sync_transcribe_audio(message)

    # -----------------------------------------------------------------------
    # API especifica de Meta (solo disponible en este proveedor)
    # -----------------------------------------------------------------------

    def actualizar_foto_perfil(self, session_id: str, file_bytes: bytes,
                               mime_type: str = 'image/jpeg') -> dict:
        """Actualiza la foto de perfil del WhatsApp Business via Meta Graph API.

        Meta exige el flujo de **Resumable Upload** (NO el endpoint normal de
        media), porque el handle resultante es de tipo "App-scoped" y caduca
        rápido — solo sirve para una llamada inmediata a `business_profile`.

        Pasos:
        1. POST `/{app_id}/uploads?file_length=N&file_type=...&access_token=`
           → devuelve `{id: "upload:abc..."}` (sesión de upload)
        2. POST `/{upload_session_id}` con header `Authorization: OAuth <token>`
           y `file_offset: 0`, body crudo de bytes → devuelve `{h: "..."}`
        3. POST `/{phone_number_id}/whatsapp_business_profile` con
           `messaging_product=whatsapp` y `profile_picture_handle=h`

        Devuelve `{'success': bool, 'message': str, 'handle'?: str}`.
        Limitaciones de Meta: imagen cuadrada recomendada, JPG/PNG, mínimo
        192x192 px, máximo 5MB. Validación liviana del lado nuestro — Meta
        responde con error explícito si algo no cumple.
        """
        config = self._get_config(session_id)
        if not config:
            return {'success': False, 'message': 'Sesión sin ConfigMeta.'}

        from meta.credenciales import get_meta_app_credentials
        app_id, _ = get_meta_app_credentials()
        if not app_id:
            return {'success': False, 'message': 'Falta Meta App ID en CredencialMetaApp.'}

        if not file_bytes:
            return {'success': False, 'message': 'Archivo vacío.'}
        if len(file_bytes) > 5 * 1024 * 1024:
            return {'success': False, 'message': 'La imagen supera 5MB. Reduzcala antes de subir.'}

        access_token = config.access_token
        try:
            # Paso 1 — abrir upload session
            r1 = requests.post(
                f'{GRAPH_API_BASE}/{app_id}/uploads',
                params={
                    'file_length': len(file_bytes),
                    'file_type':   mime_type,
                    'access_token': access_token,
                },
                timeout=15,
            )
            if r1.status_code != 200:
                msg = self._parse_error_meta(r1, 'No pude abrir upload session')
                logger.warning("Meta foto upload step1: %s", msg)
                return {'success': False, 'message': msg}
            upload_session_id = (r1.json() or {}).get('id')
            if not upload_session_id:
                return {'success': False, 'message': 'Meta no devolvió upload_session_id.'}

            # Paso 2 — subir bytes y obtener handle
            r2 = requests.post(
                f'{GRAPH_API_BASE}/{upload_session_id}',
                headers={
                    'Authorization': f'OAuth {access_token}',
                    'file_offset':   '0',
                },
                data=file_bytes,
                timeout=60,
            )
            if r2.status_code != 200:
                msg = self._parse_error_meta(r2, 'Falló la subida de bytes')
                logger.warning("Meta foto upload step2: %s", msg)
                return {'success': False, 'message': msg}
            handle = (r2.json() or {}).get('h')
            if not handle:
                return {'success': False, 'message': 'Meta no devolvió handle.'}

            # Paso 3 — asignar al business profile
            r3 = requests.post(
                f'{GRAPH_API_BASE}/{config.phone_number_id}/whatsapp_business_profile',
                headers=self._headers(config),
                json={
                    'messaging_product':       'whatsapp',
                    'profile_picture_handle':  handle,
                },
                timeout=20,
            )
            if r3.status_code != 200:
                msg = self._parse_error_meta(r3, 'Meta rechazó la foto')
                logger.warning("Meta foto upload step3: %s", msg)
                return {'success': False, 'message': msg}

            return {'success': True, 'message': 'Foto actualizada en Meta.', 'handle': handle}
        except requests.RequestException as ex:
            logger.exception("Error de red actualizando foto Meta")
            return {'success': False, 'message': f'Error de red: {ex}'}
        except Exception as ex:
            logger.exception("Error inesperado actualizando foto Meta")
            return {'success': False, 'message': f'Error: {ex}'}

    def _parse_error_meta(self, response, fallback: str) -> str:
        """Extrae el mensaje de error de una respuesta Meta (formato estándar
        `{error: {message, code, ...}}`); si no se puede, devuelve `fallback`."""
        try:
            data = response.json() or {}
            err = data.get('error') or {}
            return err.get('message') or err.get('error_user_msg') or fallback
        except Exception:
            return f'{fallback} (HTTP {response.status_code})'

    def crear_plantilla_en_meta(self, session_id, plantilla: PlantillaWhatsApp) -> dict:
        """Envia la plantilla a Meta para aprobacion. Guarda `id_meta` y marca
        estado PENDING si Meta acepta el envio."""
        config = self._get_config(session_id)
        if not config:
            return {'success': False, 'error': 'config_meta_no_encontrada'}

        payload = self._construir_payload_plantilla(plantilla)
        try:
            r = requests.post(
                f'{GRAPH_API_BASE}/{config.waba_id}/message_templates',
                headers=self._headers(config), json=payload, timeout=20,
            )
        except Exception as e:
            logger.exception("Error creando plantilla en Meta")
            return {'success': False, 'error': str(e)}

        if r.status_code in (200, 201):
            data = r.json()
            from django.utils import timezone
            plantilla.id_meta = data.get('id', '')
            plantilla.estado_meta = 'PENDING'
            plantilla.ultima_sincronizacion = timezone.now()
            plantilla.save(update_fields=['id_meta', 'estado_meta', 'ultima_sincronizacion'])
            return {'success': True, 'id_meta': data.get('id')}
        return {'success': False, 'error': f"{r.status_code}: {r.text[:500]}"}

    def sincronizar_plantillas(self, session_id) -> dict:
        """Trae el listado de plantillas desde Meta y actualiza los estados
        locales. Util como cron o boton 'Sincronizar' en la UI."""
        config = self._get_config(session_id)
        if not config:
            return {'success': False, 'error': 'config_meta_no_encontrada'}

        try:
            r = requests.get(
                f'{GRAPH_API_BASE}/{config.waba_id}/message_templates',
                headers=self._headers(config), params={'limit': 200}, timeout=20,
            )
        except Exception as e:
            logger.exception("Error listando plantillas en Meta")
            return {'success': False, 'error': str(e)}

        if r.status_code != 200:
            return {'success': False, 'error': f"{r.status_code}: {r.text[:500]}"}

        remotas = r.json().get('data', [])
        from django.utils import timezone
        ahora = timezone.now()
        actualizadas = 0
        for t in remotas:
            nombre = t.get('name')
            idioma = t.get('language', 'es')
            estado_meta = (t.get('status') or 'PENDING').upper()
            motivo = t.get('rejected_reason') or ''
            pl = PlantillaWhatsApp.objects.filter(
                config_meta=config, nombre=nombre, idioma=idioma
            ).first()
            if pl:
                pl.id_meta = t.get('id', pl.id_meta)
                pl.estado_meta = estado_meta
                pl.motivo_rechazo = motivo
                pl.ultima_sincronizacion = ahora
                if estado_meta == 'APPROVED' and not pl.fecha_aprobacion:
                    pl.fecha_aprobacion = ahora
                pl.save(update_fields=[
                    'id_meta', 'estado_meta', 'motivo_rechazo',
                    'ultima_sincronizacion', 'fecha_aprobacion',
                ])
                actualizadas += 1
        return {'success': True, 'actualizadas': actualizadas, 'total_remoto': len(remotas)}

    def _construir_payload_plantilla(self, plantilla: PlantillaWhatsApp) -> dict:
        components = []
        if plantilla.header_tipo and plantilla.header_tipo != 'NONE':
            header_comp = {'type': 'HEADER', 'format': plantilla.header_tipo}
            if plantilla.header_tipo == 'TEXT' and plantilla.header_contenido:
                # Meta rechaza el header con newlines, **negritas**, emojis o
                # formato markdown. Sanitizamos antes de enviar.
                header_comp['text'] = _sanitizar_header_meta(plantilla.header_contenido)
            components.append(header_comp)

        # Cuerpo: max 1024 chars segun Meta. Si hay markdown tipo *negrita*
        # Meta lo acepta — no lo limpiamos aca.
        cuerpo = (plantilla.cuerpo or '')[:1024]
        components.append({'type': 'BODY', 'text': cuerpo})

        if plantilla.footer:
            # Footer: max 60 chars, sin newlines ni emojis.
            components.append({'type': 'FOOTER', 'text': _sanitizar_header_meta(plantilla.footer)[:60]})

        if plantilla.botones_json:
            components.append({'type': 'BUTTONS', 'buttons': plantilla.botones_json})

        return {
            'name':       plantilla.nombre,
            'language':   plantilla.idioma,
            'category':   plantilla.categoria,
            'components': components,
        }

    # -----------------------------------------------------------------------
    # Internos
    # -----------------------------------------------------------------------

    def _post_mensaje(self, config: ConfigMeta, data: dict, conversacion_id=None) -> dict:
        import time as _time
        url = f'{GRAPH_API_BASE}/{config.phone_number_id}/messages'
        t0 = _time.monotonic()
        # Usado tambien para log outbound — wallclock para timestamps absolutos.
        wall_t0 = _time_audit.time()
        nota_op = f"send_{(data.get('type') or 'unknown')}"
        r = None
        try:
            r = requests.post(url, headers=self._headers(config), json=data, timeout=15)
        except Exception as e:
            logger.exception("Error enviando mensaje a Meta")
            resultado = {'success': False, 'error': str(e)}
            self._registrar_traza(config, data, resultado, conversacion_id, int((_time.monotonic() - t0) * 1000))
            _log_outbound('POST', url, body=data, response=None,
                          started_at=wall_t0, nota=f"{nota_op}_network_error")
            return resultado

        if r.status_code == 200:
            body = r.json()
            msg_id = ''
            if body.get('messages'):
                msg_id = body['messages'][0].get('id', '')
            resultado = {'success': True, 'message_id': msg_id}
        else:
            resultado = {'success': False, 'error': f"{r.status_code}: {r.text[:500]}"}

        self._registrar_traza(config, data, resultado, conversacion_id, int((_time.monotonic() - t0) * 1000))
        _log_outbound('POST', url, body=data, response=r,
                      started_at=wall_t0, nota=nota_op)
        return resultado

    def _registrar_traza_bloqueo(self, config: ConfigMeta, to: str, tipo: str,
                                  resultado: dict, conversacion_id) -> dict:
        """Para guardas que rechazan el envio antes de contactar a Meta
        (ventana 24h, cuenta degradada). Registra traza con latencia 0 y
        devuelve el resultado tal cual para que el caller lo retorne."""
        payload = {'to': self._normalizar_destinatario(to), 'type': tipo}
        self._registrar_traza(config, payload, resultado, conversacion_id, 0)
        return resultado

    def _registrar_traza(self, config: ConfigMeta, payload: dict, resultado: dict,
                         conversacion_id, latencia_ms: int) -> None:
        """Escribe una fila en TrazaMensajeIA para que /whatsapp/trazas/ muestre
        los envios Meta igual que los de Baileys (Node emite su propia traza)."""
        try:
            from whatsapp.models import TrazaMensajeIA, ConversacionWhatsApp
            conv = None
            if conversacion_id:
                conv = ConversacionWhatsApp.objects.filter(pk=conversacion_id).first()
            ok = bool(resultado.get('success'))
            etapa = 'mensaje_enviado' if ok else 'envio_fallido'
            # Si la cuenta viene en YELLOW, bajamos el nivel a warning aunque
            # el envio haya sido exitoso — asi se ve rapido en la UI.
            rating = (config.quality_rating or 'UNKNOWN').upper()
            if ok:
                nivel = 'warning' if rating == 'YELLOW' else 'success'
            else:
                nivel = 'error'
            detalle_parts = [
                f"transporte=meta",
                f"tipo={payload.get('type', '')}",
                f"quality={rating}",
            ]
            if config.messaging_limit_tier:
                detalle_parts.append(f"tier={config.messaging_limit_tier}")
            if ok:
                detalle_parts.append(f"message_id={resultado.get('message_id', '')}")
            else:
                detalle_parts.append(f"error={str(resultado.get('error', ''))[:500]}")
                if resultado.get('requiere_plantilla'):
                    detalle_parts.append('requiere_plantilla=True')
                if resultado.get('cuenta_degradada'):
                    detalle_parts.append('cuenta_degradada=True')
            TrazaMensajeIA.objects.create(
                sesion=config.sesion,
                conversacion=conv,
                numero=payload.get('to', '') or (conv.contacto.from_number if conv else ''),
                etapa=etapa,
                nivel=nivel,
                detalle=' | '.join(detalle_parts)[:4000],
                latencia_ms=latencia_ms,
            )
        except Exception:
            logger.exception("Error registrando traza Meta")

    def _subir_media(self, config: ConfigMeta, file_path, file_content, filename, tipo) -> str | None:
        url = f'{GRAPH_API_BASE}/{config.phone_number_id}/media'
        headers = {'Authorization': f'Bearer {config.access_token}'}
        mime_map = {
            'image':    'image/jpeg',
            'video':    'video/mp4',
            'audio':    'audio/mpeg',
            'document': 'application/pdf',
            'sticker':  'image/webp',
        }
        try:
            if file_path:
                with open(file_path, 'rb') as f:
                    files = {'file': (filename or 'file', f, mime_map.get(tipo, 'application/octet-stream'))}
                    data = {'messaging_product': 'whatsapp', 'type': tipo}
                    r = requests.post(url, headers=headers, data=data, files=files, timeout=60)
            else:
                files = {'file': (filename or 'file', file_content, mime_map.get(tipo, 'application/octet-stream'))}
                data = {'messaging_product': 'whatsapp', 'type': tipo}
                r = requests.post(url, headers=headers, data=data, files=files, timeout=60)
        except Exception:
            logger.exception("Error subiendo media a Meta")
            return None

        if r.status_code == 200:
            return r.json().get('id')
        logger.warning("Meta upload media: %s %s", r.status_code, r.text[:300])
        return None
