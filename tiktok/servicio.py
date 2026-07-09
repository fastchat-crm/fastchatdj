"""Sender TikTok Business Messaging API — interfaz paralela a WhatsAppService.

Estado: la API está en beta y requiere aprobación de TikTok. Este servicio
queda pre-construido con la interfaz estándar del dispatcher
(`get_whatsapp_service`); los endpoints siguen la doc v1.3 de
business-api.tiktok.com y pueden requerir ajuste fino cuando la app sea
aprobada y se pruebe contra el sandbox real.

Docs: https://business-api.tiktok.com/portal/docs (Business Messaging v1.3)
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from whatsapp.models import ConfigTikTok, SesionWhatsApp
from whatsapp.servicio_canal_base import ServicioCanalBase

logger = logging.getLogger(__name__)

TIKTOK_API_VERSION = 'v1.3'
TIKTOK_API_BASE = f'https://business-api.tiktok.com/open_api/{TIKTOK_API_VERSION}'


class TikTokService(ServicioCanalBase):
    """Envía DMs desde una cuenta TikTok Business autorizada por OAuth."""

    def _config(self, session_id: str) -> Optional[ConfigTikTok]:
        try:
            sesion = SesionWhatsApp.objects.select_related('config_tiktok').get(
                session_id=session_id
            )
        except SesionWhatsApp.DoesNotExist:
            return None
        return getattr(sesion, 'config_tiktok', None)

    _LIMITE_CHARS_MENSAJE = 1000

    def send_text_message(self, session_id, to, text, conversacion_id=None, simularEscritura=False):
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': 'config_tiktok_no_encontrada'}
        if not config.access_token:
            return {'success': False, 'error': 'cuenta_tiktok_sin_token_oauth'}
        recipient_id = to.split('@')[0] if '@' in (to or '') else to
        from whatsapp.servicio_canal_base import partir_texto_por_limite
        partes = partir_texto_por_limite(text, self._LIMITE_CHARS_MENSAJE) or ['']
        resultado = {'success': False, 'error': 'texto_vacio'}
        for parte in partes:
            payload = {
                'business_id': config.business_id,
                'recipient':   {'open_id': recipient_id},
                'message':     {'type': 'text', 'text': parte},
            }
            try:
                r = requests.post(
                    f'{TIKTOK_API_BASE}/business/message/send/',
                    headers={'Access-Token': config.access_token},
                    json=payload,
                    timeout=15,
                )
                data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
                ok = r.status_code == 200 and data.get('code') == 0
                if not ok:
                    config.error_mensaje = str(data.get('message') or r.text[:400])
                    config.save()
                resultado = {
                    'success':    ok,
                    'status':     r.status_code,
                    'message_id': (data.get('data') or {}).get('message_id'),
                    'error':      None if ok else (data.get('message') or r.text[:400]),
                }
                if not ok:
                    return resultado
            except Exception as e:
                logger.exception("TikTok send error")
                return {'success': False, 'error': str(e)}
        return resultado

    def send_media_message(self, session_id, to, file_path=None, file_content=None,
                           caption=None, filename=None, media_url=None,
                           media_type='image', conversacion_id=None, **kwargs):
        return {'success': False, 'error': 'Envío de archivos no disponible en TikTok (API en beta).'}

    def send_presence_update(self, session_id, to, presence='composing'):
        return {'success': True, 'skipped': 'tiktok_presence_no_soportado'}

    def close_session(self, session_id):
        return {'success': True, 'skipped': 'tiktok_no_requiere_cierre'}

    def format_phone_number(self, numero):
        return numero
