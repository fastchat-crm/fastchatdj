"""Sender Instagram Graph API (DMs) — interfaz paralela a WhatsAppService."""
from __future__ import annotations

import logging
from typing import Optional

import requests

from whatsapp.models import ConfigInstagram, SesionWhatsApp

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = 'v21.0'
GRAPH_API_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'


class InstagramService:
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

    def send_text_message(self, session_id, to, text, conversacion_id=None, simularEscritura=False):
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_instagram_no_encontrada'}
        recipient_id = to.split('@')[0] if '@' in (to or '') else to
        payload = {
            'recipient': {'id': recipient_id},
            'message':   {'text': text},
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
            return {
                'success':    ok,
                'status':     r.status_code,
                'message_id': data.get('message_id'),
                'error':      None if ok else (data.get('error') or r.text[:400]),
            }
        except Exception as e:
            logger.exception("IG send error")
            return {'success': False, 'error': str(e)}

    def send_media_message(self, session_id, to, caption=None, file_content=None,
                           filename=None, media_url=None, media_type='image'):
        """media_type: image|video|audio|file. Usa `media_url` (URL pública) en Graph."""
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
