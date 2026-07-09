"""Sender Instagram Graph API (DMs) — interfaz paralela a WhatsAppService."""
from __future__ import annotations

import logging
from typing import Optional

import requests

from whatsapp.models import ConfigInstagram, SesionWhatsApp
from whatsapp.servicio_canal_base import ServicioCanalBase

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = 'v21.0'
GRAPH_API_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'


class InstagramService(ServicioCanalBase):
    """Envía mensajes desde una cuenta Instagram Business vinculada a una FB Page.

    Docs: https://developers.facebook.com/docs/messenger-platform/instagram/
    """

    def _config(self, session_id: str) -> Optional[ConfigInstagram]:
        try:
            sesion = SesionWhatsApp.objects.select_related('config_instagram').get(
                session_id=session_id
            )
        except SesionWhatsApp.DoesNotExist:
            return None
        return getattr(sesion, 'config_instagram', None)

    _LIMITE_CHARS_MENSAJE = 1000

    def send_text_message(self, session_id, to, text, conversacion_id=None, simularEscritura=False):
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_instagram_no_encontrada'}
        recipient_id = to.split('@')[0] if '@' in (to or '') else to
        # Instagram/Messenger rechazan mensajes > 1000 chars (error 100) y el
        # cliente no recibe nada — se entrega en partes secuenciales.
        from whatsapp.servicio_canal_base import partir_texto_por_limite
        partes = partir_texto_por_limite(text, self._LIMITE_CHARS_MENSAJE) or ['']
        resultado = {'success': False, 'error': 'texto_vacio'}
        for parte in partes:
            payload = {
                'recipient': {'id': recipient_id},
                'message':   {'text': parte},
                'messaging_type': 'RESPONSE',
            }
            try:
                r = requests.post(
                    f'{GRAPH_API_BASE}/{config.page_id}/messages',
                    params={'access_token': config.access_token},
                    json=payload,
                    timeout=15,
                )
                ok = 200 <= r.status_code < 300
                data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
                resultado = {
                    'success':    ok,
                    'status':     r.status_code,
                    'message_id': data.get('message_id'),
                    'error':      None if ok else (data.get('error') or r.text[:400]),
                }
                if not ok:
                    return resultado
            except Exception as e:
                logger.exception("IG send error")
                return {'success': False, 'error': str(e)}
        return resultado

    def send_media_message(self, session_id, to, file_path=None, file_content=None,
                           caption=None, filename=None, media_url=None,
                           media_type='image', conversacion_id=None, **kwargs):
        """media_type: image|video|audio|file. Usa `media_url` (URL pública) en Graph.

        `file_path`/`file_content`/`conversacion_id` forman parte del contrato
        común (`ServicioCanalBase`); Instagram Graph solo acepta URL pública,
        así que sin `media_url` se responde con error claro."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_instagram_no_encontrada'}
        if not media_url:
            return {'success': False, 'error': 'media_url_requerida_en_instagram'}
        recipient_id = to.split('@')[0] if '@' in (to or '') else to
        payload = {
            'recipient': {'id': recipient_id},
            'message': {
                'attachment': {
                    'type':    media_type,
                    'payload': {'url': media_url, 'is_reusable': True},
                },
            },
        }
        r = requests.post(
            f'{GRAPH_API_BASE}/{config.page_id}/messages',
            params={'access_token': config.access_token},
            json=payload,
            timeout=20,
        )
        return {'success': 200 <= r.status_code < 300, 'status': r.status_code, 'body': r.text[:500]}

    def obtener_perfil(self, session_id):
        """Valida el token: GET /{ig_user_id}?fields=username,name,followers_count."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_instagram_no_encontrada'}
        try:
            r = requests.get(
                f'{GRAPH_API_BASE}/{config.ig_user_id}',
                params={
                    'fields': 'username,name,followers_count,media_count,profile_picture_url',
                    'access_token': config.access_token,
                },
                timeout=15,
            )
            ok = 200 <= r.status_code < 300
            data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            return {
                'success': ok,
                'status':  r.status_code,
                'perfil':  data if ok else None,
                'error':   None if ok else (data.get('error') or r.text[:400]),
            }
        except Exception as e:
            logger.exception("IG obtener perfil error")
            return {'success': False, 'error': str(e)}

    def listar_publicaciones(self, session_id, limite=25):
        """GET /{ig_user_id}/media con métricas básicas por publicación."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_instagram_no_encontrada'}
        try:
            r = requests.get(
                f'{GRAPH_API_BASE}/{config.ig_user_id}/media',
                params={
                    'fields': 'id,caption,media_type,media_url,thumbnail_url,'
                              'permalink,timestamp,comments_count,like_count',
                    'limit': limite,
                    'access_token': config.access_token,
                },
                timeout=20,
            )
            ok = 200 <= r.status_code < 300
            data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            return {
                'success':        ok,
                'status':         r.status_code,
                'publicaciones':  data.get('data', []) if ok else [],
                'error':          None if ok else (data.get('error') or r.text[:400]),
            }
        except Exception as e:
            logger.exception("IG listar publicaciones error")
            return {'success': False, 'error': str(e)}

    def responder_comentario(self, session_id, comment_id, texto):
        """Respuesta pública a un comentario: POST /{comment_id}/replies."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_instagram_no_encontrada'}
        try:
            r = requests.post(
                f'{GRAPH_API_BASE}/{comment_id}/replies',
                params={'access_token': config.access_token},
                json={'message': texto},
                timeout=15,
            )
            ok = 200 <= r.status_code < 300
            data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            return {
                'success':  ok,
                'status':   r.status_code,
                'reply_id': data.get('id'),
                'error':    None if ok else (data.get('error') or r.text[:400]),
            }
        except Exception as e:
            logger.exception("IG responder comentario error")
            return {'success': False, 'error': str(e)}

    def ocultar_comentario(self, session_id, comment_id, ocultar=True):
        """Oculta/muestra un comentario: POST /{comment_id} con `hide`."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_instagram_no_encontrada'}
        try:
            r = requests.post(
                f'{GRAPH_API_BASE}/{comment_id}',
                params={'access_token': config.access_token},
                json={'hide': bool(ocultar)},
                timeout=15,
            )
            ok = 200 <= r.status_code < 300
            data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            return {
                'success': ok,
                'status':  r.status_code,
                'error':   None if ok else (data.get('error') or r.text[:400]),
            }
        except Exception as e:
            logger.exception("IG ocultar comentario error")
            return {'success': False, 'error': str(e)}

    def enviar_dm_desde_comentario(self, session_id, comment_id, texto):
        """Private reply: DM al autor de un comentario (ventana de 7 días).
        POST /{page_id}/messages con recipient.comment_id."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_instagram_no_encontrada'}
        payload = {
            'recipient': {'comment_id': comment_id},
            'message':   {'text': texto},
        }
        try:
            r = requests.post(
                f'{GRAPH_API_BASE}/{config.page_id}/messages',
                params={'access_token': config.access_token},
                json=payload,
                timeout=15,
            )
            ok = 200 <= r.status_code < 300
            data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            return {
                'success':      ok,
                'status':       r.status_code,
                'message_id':   data.get('message_id'),
                'recipient_id': data.get('recipient_id'),
                'error':        None if ok else (data.get('error') or r.text[:400]),
            }
        except Exception as e:
            logger.exception("IG private reply error")
            return {'success': False, 'error': str(e)}

    def send_presence_update(self, session_id, to, presence='composing'):
        return {'success': True, 'skipped': 'instagram_presence_no_soportado'}

    def close_session(self, session_id):
        return {'success': True, 'skipped': 'instagram_no_requiere_cierre'}

    def format_phone_number(self, numero):
        return numero


class MessengerService(InstagramService):
    """Messenger = misma API que IG pero sobre `config_messenger`. Reutilizamos
    todo el comportamiento y sólo cambiamos el resolver de config."""

    def _config(self, session_id: str):  # type: ignore[override]
        try:
            sesion = SesionWhatsApp.objects.select_related('config_messenger').get(
                session_id=session_id
            )
        except SesionWhatsApp.DoesNotExist:
            return None
        return getattr(sesion, 'config_messenger', None)
