"""Sender Instagram Graph API (DMs) — interfaz paralela a WhatsAppService."""
from __future__ import annotations

import logging
from typing import Optional

import requests

from whatsapp.models import ConfigInstagram, SesionWhatsApp
from whatsapp.servicio_canal_base import ServicioCanalBase

from .urls import GRAPH_API_VERSION

logger = logging.getLogger(__name__)

GRAPH_API_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'


class InstagramService(ServicioCanalBase):
    """Envía mensajes desde una cuenta Instagram Business vinculada a una FB Page.

    Docs: https://developers.facebook.com/docs/messenger-platform/instagram/
    """

    _ERROR_CONFIG = 'config_instagram_no_encontrada'
    _LIMITE_CHARS_MENSAJE = 1000

    def _config(self, session_id: str) -> Optional[ConfigInstagram]:
        try:
            sesion = SesionWhatsApp.objects.select_related('config_instagram').get(
                session_id=session_id
            )
        except SesionWhatsApp.DoesNotExist:
            return None
        return getattr(sesion, 'config_instagram', None)

    def _graph_request(self, metodo, path, config, json=None, params=None, timeout=15):
        """Llamada Graph con el shape de respuesta estándar del paquete:
        {'success', 'status', 'data', 'error'} — nunca lanza al caller."""
        try:
            r = requests.request(
                metodo,
                f'{GRAPH_API_BASE}/{path}',
                params={'access_token': config.access_token, **(params or {})},
                json=json,
                timeout=timeout,
            )
            ok = 200 <= r.status_code < 300
            data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
            return {
                'success': ok,
                'status':  r.status_code,
                'data':    data,
                'error':   None if ok else (data.get('error') or r.text[:400]),
            }
        except Exception as e:
            logger.exception("Graph API error %s /%s", metodo, path)
            return {'success': False, 'data': {}, 'error': str(e)}

    def send_text_message(self, session_id, to, text, conversacion_id=None, simularEscritura=False):
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
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
            resultado = self._graph_request('post', f'{config.page_id}/messages', config, json=payload)
            resultado['message_id'] = resultado.pop('data').get('message_id')
            if not resultado['success']:
                return resultado
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
            return {'success': False, 'error': self._ERROR_CONFIG}
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
        res = self._graph_request('post', f'{config.page_id}/messages', config, json=payload, timeout=20)
        res.pop('data')
        return res

    def obtener_perfil(self, session_id):
        """Valida el token: GET /{ig_user_id}?fields=username,name,followers_count."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('get', config.ig_user_id, config, params={
            'fields': 'username,name,followers_count,media_count,profile_picture_url',
        })
        data = res.pop('data')
        res['perfil'] = data if res['success'] else None
        return res

    def listar_publicaciones(self, session_id, limite=25):
        """GET /{ig_user_id}/media con métricas básicas por publicación."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('get', f'{config.ig_user_id}/media', config, timeout=20, params={
            'fields': 'id,caption,media_type,media_url,thumbnail_url,'
                      'permalink,timestamp,comments_count,like_count',
            'limit': limite,
        })
        data = res.pop('data')
        res['publicaciones'] = data.get('data', []) if res['success'] else []
        return res

    def listar_comentarios_publicacion(self, session_id, media_id):
        """GET /{media_id}/comments — comentarios en vivo de una publicación,
        normalizados a {id, texto, autor_id, autor_nombre, fecha, parent_id}."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('get', f'{media_id}/comments', config, timeout=20, params={
            'fields': 'id,text,username,from,timestamp,parent_id,hidden',
            'limit': 100,
        })
        data = res.pop('data')
        comentarios = []
        if res['success']:
            for c in data.get('data', []):
                autor = c.get('from') or {}
                comentarios.append({
                    'id':           c.get('id'),
                    'texto':        c.get('text') or '',
                    'autor_id':     str(autor.get('id') or ''),
                    'autor_nombre': c.get('username') or autor.get('username') or '',
                    'fecha':        c.get('timestamp') or '',
                    'parent_id':    str(c.get('parent_id') or ''),
                })
        res['comentarios'] = comentarios
        return res

    def publicar_post(self, session_id, mensaje, foto_url=None, link=None):
        """Publica en el feed de Instagram (flujo de 2 pasos: container →
        media_publish). Instagram exige una imagen con URL pública; `link`
        no está soportado (va dentro del caption si se necesita)."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        if not foto_url:
            return {'success': False, 'error': 'Instagram requiere una imagen (URL pública) para publicar.'}
        res1 = self._graph_request('post', f'{config.ig_user_id}/media', config, timeout=30, json={
            'image_url': foto_url,
            'caption': mensaje or '',
        })
        data1 = res1.pop('data')
        if not res1['success']:
            return res1
        creation_id = data1.get('id')
        if not creation_id:
            return {'success': False, 'error': 'Meta no devolvió el creation_id del container.'}
        res2 = self._graph_request('post', f'{config.ig_user_id}/media_publish', config, timeout=30, json={
            'creation_id': creation_id,
        })
        data2 = res2.pop('data')
        res2['post_id'] = data2.get('id')
        return res2

    def responder_comentario(self, session_id, comment_id, texto):
        """Respuesta pública a un comentario: POST /{comment_id}/replies."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('post', f'{comment_id}/replies', config, json={'message': texto})
        res['reply_id'] = res.pop('data').get('id')
        return res

    def ocultar_comentario(self, session_id, comment_id, ocultar=True):
        """Oculta/muestra un comentario: POST /{comment_id} con `hide`."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('post', str(comment_id), config, json={'hide': bool(ocultar)})
        res.pop('data')
        return res

    def enviar_dm_desde_comentario(self, session_id, comment_id, texto):
        """Private reply: DM al autor de un comentario (ventana de 7 días).
        POST /{page_id}/messages con recipient.comment_id."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        payload = {
            'recipient': {'comment_id': comment_id},
            'message':   {'text': texto},
        }
        res = self._graph_request('post', f'{config.page_id}/messages', config, json=payload)
        data = res.pop('data')
        res['message_id'] = data.get('message_id')
        res['recipient_id'] = data.get('recipient_id')
        return res

    def send_presence_update(self, session_id, to, presence='composing'):
        return {'success': True, 'skipped': 'instagram_presence_no_soportado'}

    def close_session(self, session_id):
        return {'success': True, 'skipped': 'instagram_no_requiere_cierre'}

    def format_phone_number(self, numero):
        return numero


class MessengerService(InstagramService):
    """Messenger = misma API que IG pero sobre `config_messenger`. Reutilizamos
    todo el comportamiento y solo cambiamos el resolver de config, más los
    endpoints que difieren para páginas de Facebook (perfil, feed y comentarios
    del feed: responder es `/{comment_id}/comments` y ocultar usa `is_hidden`)."""

    _ERROR_CONFIG = 'config_messenger_no_encontrada'

    def _config(self, session_id: str):  # type: ignore[override]
        try:
            sesion = SesionWhatsApp.objects.select_related('config_messenger').get(
                session_id=session_id
            )
        except SesionWhatsApp.DoesNotExist:
            return None
        return getattr(sesion, 'config_messenger', None)

    def obtener_perfil(self, session_id):
        """Valida el token de página: GET /{page_id} con campos de página."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('get', config.page_id, config, params={
            'fields': 'id,name,category,fan_count,verification_status,picture',
        })
        data = res.pop('data')
        if res['success']:
            data['username'] = data.get('name', '')
            data['followers_count'] = data.get('fan_count', 0)
        res['perfil'] = data if res['success'] else None
        return res

    def listar_comentarios_publicacion(self, session_id, post_id):  # type: ignore[override]
        """GET /{post_id}/comments (filter=stream incluye respuestas anidadas),
        normalizado a {id, texto, autor_id, autor_nombre, fecha, parent_id}."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('get', f'{post_id}/comments', config, timeout=20, params={
            'fields': 'id,message,from{id,name},created_time,parent{id}',
            'limit': 100,
            'filter': 'stream',
        })
        data = res.pop('data')
        comentarios = []
        if res['success']:
            for c in data.get('data', []):
                autor = c.get('from') or {}
                comentarios.append({
                    'id':           c.get('id'),
                    'texto':        c.get('message') or '',
                    'autor_id':     str(autor.get('id') or ''),
                    'autor_nombre': autor.get('name') or '',
                    'fecha':        c.get('created_time') or '',
                    'parent_id':    str(((c.get('parent') or {}).get('id')) or ''),
                })
        res['comentarios'] = comentarios
        return res

    def publicar_post(self, session_id, mensaje, foto_url=None, link=None):  # type: ignore[override]
        """Publica en la página: con `foto_url` → POST /{page_id}/photos;
        sin foto → POST /{page_id}/feed con message (+ link opcional)."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        if foto_url:
            res = self._graph_request('post', f'{config.page_id}/photos', config, timeout=30, json={
                'url': foto_url,
                'caption': mensaje or '',
            })
        else:
            if not (mensaje or link):
                return {'success': False, 'error': 'La publicación necesita un texto, un link o una imagen.'}
            payload = {'message': mensaje or ''}
            if link:
                payload['link'] = link
            res = self._graph_request('post', f'{config.page_id}/feed', config, timeout=30, json=payload)
        data = res.pop('data')
        res['post_id'] = data.get('post_id') or data.get('id')
        return res

    _CAMPOS_POSTS_BASE = ('id,message,full_picture,permalink_url,created_time,shares,'
                          'comments.summary(true).limit(0),likes.summary(true).limit(0)')
    _CAMPOS_POSTS_INSIGHTS = ',insights.metric(post_impressions,post_impressions_unique,post_clicks){name,values}'

    def listar_publicaciones(self, session_id, limite=25):
        """GET /{page_id}/posts normalizado al shape de IG para reusar la grilla.
        Pide insights (impresiones/alcance/clics) en el mismo request; si la app
        no tiene `read_insights`, reintenta sin insights para no romper la grilla."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('get', f'{config.page_id}/posts', config, timeout=20, params={
            'fields': self._CAMPOS_POSTS_BASE + self._CAMPOS_POSTS_INSIGHTS,
            'limit': limite,
        })
        if not res['success']:
            res = self._graph_request('get', f'{config.page_id}/posts', config, timeout=20, params={
                'fields': self._CAMPOS_POSTS_BASE,
                'limit': limite,
            })
        data = res.pop('data')
        publicaciones = []
        if res['success']:
            for post in data.get('data', []):
                comments = ((post.get('comments') or {}).get('summary') or {})
                likes = ((post.get('likes') or {}).get('summary') or {})
                metricas = {}
                for m in ((post.get('insights') or {}).get('data') or []):
                    valores = m.get('values') or []
                    if valores:
                        metricas[m.get('name')] = valores[0].get('value')
                publicaciones.append({
                    'id':             post.get('id'),
                    'caption':        post.get('message') or '',
                    'media_type':     'IMAGE' if post.get('full_picture') else 'TEXT',
                    'media_url':      post.get('full_picture') or '',
                    'thumbnail_url':  post.get('full_picture') or '',
                    'permalink':      post.get('permalink_url') or '',
                    'timestamp':      post.get('created_time') or '',
                    'comments_count': comments.get('total_count', 0),
                    'like_count':     likes.get('total_count', 0),
                    'shares_count':   (post.get('shares') or {}).get('count', 0),
                    'impresiones':    metricas.get('post_impressions'),
                    'alcance':        metricas.get('post_impressions_unique'),
                    'clics':          metricas.get('post_clicks'),
                })
        res['publicaciones'] = publicaciones
        return res

    def responder_comentario(self, session_id, comment_id, texto):
        """Respuesta pública en el feed de página: POST /{comment_id}/comments."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('post', f'{comment_id}/comments', config, json={'message': texto})
        res['reply_id'] = res.pop('data').get('id')
        return res

    def ocultar_comentario(self, session_id, comment_id, ocultar=True):
        """Oculta/muestra un comentario del feed: POST /{comment_id} con `is_hidden`."""
        config = self._config(session_id)
        if not config:
            return {'success': False, 'error': self._ERROR_CONFIG}
        res = self._graph_request('post', str(comment_id), config, json={'is_hidden': bool(ocultar)})
        res.pop('data')
        return res
