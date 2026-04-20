"""Sender contra Meta Cloud API (Graph API).

Expone la misma interfaz publica que `whatsapp.services.WhatsAppService` para
que el resto del codigo sea agnostico al transporte. El dispatcher
`get_whatsapp_service(sesion)` en `services.py` devuelve esta clase o la de
Baileys segun `sesion.proveedor`.

Documentacion Meta:
    https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
"""
import logging

import requests

from .models import ConfigMeta, PlantillaWhatsApp, SesionWhatsApp

logger = logging.getLogger(__name__)

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

    # -----------------------------------------------------------------------
    # API publica (espejo de WhatsAppService)
    # -----------------------------------------------------------------------

    def send_text_message(self, session_id, to, text, conversacion_id=None, simularEscritura=False):
        config = self._get_config(session_id)
        if not config:
            return {'success': False, 'error': 'config_meta_no_encontrada'}

        data = {
            'messaging_product': 'whatsapp',
            'recipient_type':    'individual',
            'to':                self._normalizar_destinatario(to),
            'type':              'text',
            'text':              {'body': text, 'preview_url': True},
        }
        return self._post_mensaje(config, data)

    def send_template(self, session_id, to, plantilla_nombre, idioma='es', parametros_cuerpo=None, parametros_header=None):
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
        resultado = self._post_mensaje(config, data)

        if resultado.get('success'):
            # Actualizar metricas de uso de la plantilla
            PlantillaWhatsApp.objects.filter(
                config_meta=config, nombre=plantilla_nombre, idioma=idioma
            ).update(
                veces_enviada=PlantillaWhatsApp.objects.filter(
                    config_meta=config, nombre=plantilla_nombre, idioma=idioma
                ).values_list('veces_enviada', flat=True).first() or 0,
            )
        return resultado

    def _formatear_parametros(self, params) -> list:
        """Convierte una lista simple de strings a la forma que espera Meta."""
        if not params:
            return []
        if isinstance(params, list) and params and isinstance(params[0], str):
            return [{'type': 'text', 'text': str(p)} for p in params]
        if isinstance(params, dict):
            if params.get('image_url'):
                return [{'type': 'image', 'image': {'link': params['image_url']}}]
            if params.get('document_url'):
                return [{'type': 'document', 'document': {'link': params['document_url']}}]
        return params  # ya viene con forma correcta

    def send_presence_update(self, session_id, to):
        """Meta no expone 'escribiendo...' via API publica, es no-op."""
        return {'success': True, 'skipped': 'not_supported_by_meta'}

    def quit_presence_update(self, session_id, to):
        return {'success': True, 'skipped': 'not_supported_by_meta'}

    def send_media_message(self, session_id, to, file_path=None, file_content=None,
                           caption=None, filename=None, tipo='image', media_url=None,
                           conversacion_id=None):
        """Envia media. Preferentemente por URL (mas simple). Si se pasa file_path
        o file_content, primero se sube a Meta via /media y se usa el media_id.
        """
        config = self._get_config(session_id)
        if not config:
            return {'success': False, 'error': 'config_meta_no_encontrada'}

        if media_url:
            media_payload = {'link': media_url}
            if caption and tipo in ('image', 'video', 'document'):
                media_payload['caption'] = caption
            if filename and tipo == 'document':
                media_payload['filename'] = filename
            data = {
                'messaging_product': 'whatsapp',
                'to':                self._normalizar_destinatario(to),
                'type':              tipo,
                tipo:                media_payload,
            }
            return self._post_mensaje(config, data)

        if file_path or file_content:
            media_id = self._subir_media(config, file_path, file_content, filename, tipo)
            if not media_id:
                return {'success': False, 'error': 'upload_media_fallo'}
            media_payload = {'id': media_id}
            if caption and tipo in ('image', 'video', 'document'):
                media_payload['caption'] = caption
            if filename and tipo == 'document':
                media_payload['filename'] = filename
            data = {
                'messaging_product': 'whatsapp',
                'to':                self._normalizar_destinatario(to),
                'type':              tipo,
                tipo:                media_payload,
            }
            return self._post_mensaje(config, data)

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
        from .services import WhatsAppService
        return WhatsAppService().sync_transcribe_audio(message)

    # -----------------------------------------------------------------------
    # API especifica de Meta (solo disponible en este proveedor)
    # -----------------------------------------------------------------------

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
                header_comp['text'] = plantilla.header_contenido
            components.append(header_comp)

        components.append({'type': 'BODY', 'text': plantilla.cuerpo})

        if plantilla.footer:
            components.append({'type': 'FOOTER', 'text': plantilla.footer})

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

    def _post_mensaje(self, config: ConfigMeta, data: dict) -> dict:
        url = f'{GRAPH_API_BASE}/{config.phone_number_id}/messages'
        try:
            r = requests.post(url, headers=self._headers(config), json=data, timeout=15)
        except Exception as e:
            logger.exception("Error enviando mensaje a Meta")
            return {'success': False, 'error': str(e)}

        if r.status_code == 200:
            body = r.json()
            msg_id = ''
            if body.get('messages'):
                msg_id = body['messages'][0].get('id', '')
            return {'success': True, 'message_id': msg_id}
        return {'success': False, 'error': f"{r.status_code}: {r.text[:500]}"}

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
