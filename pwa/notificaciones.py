import json
import logging

logger = logging.getLogger(__name__)


_ICONOS_CACHE = {'icon': None, 'badge': None, 'cargado': False}

_FALLBACK_ICON_URL = '/static/iconos/logo.png'
_FALLBACK_BADGE_URL = '/static/iconos/logo.png'


def _resolver_iconos_plataforma():
    if _ICONOS_CACHE['cargado']:
        return _ICONOS_CACHE['icon'], _ICONOS_CACHE['badge']
    icon_url = None
    badge_url = None
    try:
        from django.conf import settings as _settings
        icon_url = getattr(_settings, 'PWA_PUSH_DEFAULT_ICON', None) or None
        badge_url = getattr(_settings, 'PWA_PUSH_DEFAULT_BADGE', None) or None
    except Exception:
        pass
    if not icon_url or not badge_url:
        try:
            from seguridad.models import Configuracion
            confi = Configuracion.get_instancia()
            if confi:
                if not icon_url and confi.logo_sistema:
                    try:
                        icon_url = confi.logo_sistema.url
                    except Exception:
                        icon_url = None
                if not badge_url and confi.ico:
                    try:
                        badge_url = confi.ico.url
                    except Exception:
                        badge_url = None
        except Exception:
            pass
    if not icon_url:
        icon_url = _FALLBACK_ICON_URL
    if not badge_url:
        badge_url = icon_url or _FALLBACK_BADGE_URL
    _ICONOS_CACHE['icon'] = icon_url
    _ICONOS_CACHE['badge'] = badge_url
    _ICONOS_CACHE['cargado'] = True
    return icon_url, badge_url


def invalidar_iconos_cache():
    _ICONOS_CACHE['icon'] = None
    _ICONOS_CACHE['badge'] = None
    _ICONOS_CACHE['cargado'] = False


def _payload(head, body, url=None, icon=None, badge=None, image=None, tag=None,
             require_interaction=False, extra=None):
    data = {'head': head, 'body': body}
    if url:
        data['url'] = url
    if not icon or not badge:
        plat_icon, plat_badge = _resolver_iconos_plataforma()
        if not icon:
            icon = plat_icon
        if not badge:
            badge = plat_badge
    if icon:
        data['icon'] = icon
    if badge:
        data['badge'] = badge
    if image:
        data['image'] = image
    if tag:
        data['tag'] = tag
    if require_interaction:
        data['requireInteraction'] = True
    if extra is not None:
        data['extra'] = extra
    return data


def enviar_push_usuario(user, head, body, url=None, icon=None, badge=None,
                        image=None, tag=None, require_interaction=False,
                        extra=None, ttl=60):
    try:
        from webpush import send_user_notification
    except ImportError:
        logger.warning('django-webpush not installed; skipping push')
        return False
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    payload = _payload(head, body, url=url, icon=icon, badge=badge, image=image,
                       tag=tag, require_interaction=require_interaction, extra=extra)
    try:
        send_user_notification(user=user, payload=json.dumps(payload), ttl=ttl)
        return True
    except Exception as ex:
        logger.error('enviar_push_usuario failed for user=%s: %s', getattr(user, 'pk', None), ex)
        return False


def enviar_push_grupo(group_name, head, body, url=None, **kwargs):
    try:
        from webpush import send_group_notification
    except ImportError:
        logger.warning('django-webpush not installed; skipping group push')
        return False
    payload = _payload(head, body, url=url, **kwargs)
    try:
        send_group_notification(group_name=group_name, payload=json.dumps(payload),
                                ttl=kwargs.get('ttl', 60))
        return True
    except Exception as ex:
        logger.error('enviar_push_grupo failed for group=%s: %s', group_name, ex)
        return False
