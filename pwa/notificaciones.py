import json
import logging

logger = logging.getLogger(__name__)


def _payload(head, body, url=None, icon=None, badge=None, image=None, tag=None,
             require_interaction=False, extra=None):
    data = {'head': head, 'body': body}
    if url:
        data['url'] = url
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
