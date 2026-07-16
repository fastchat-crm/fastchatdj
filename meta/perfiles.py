"""Verificadores de perfil contra Graph API — uno por canal Meta.

Cada función pingea Graph API con las credenciales guardadas en su Config*
y persiste los datos visibles del perfil (username/page_name/display_phone)
+ ultima_sincronizacion. Devuelve `(ok: bool, info: dict)` para que la
vista pueda armar la respuesta JSON sin lógica adicional.

Movido desde `whatsapp/sesiones_common.py`. El módulo legacy re-exporta
estos nombres para no romper imports existentes.
"""
from __future__ import annotations

import requests

from meta.urls import build_graph_url


def validar_instagram_desde_graph(session, config_ig, timeout=10):
    """Pinguea Graph API contra `ig_user_id` para validar credenciales IG.
    Devuelve `(ok, info_dict)`. Persiste username/ultima_sincronizacion si OK.
    """
    from django.utils import timezone as _tz
    if not (config_ig and config_ig.access_token and config_ig.ig_user_id):
        return False, {'message': 'Faltan credenciales Instagram (access_token / ig_user_id).'}
    try:
        r = requests.get(
            build_graph_url(f'/{config_ig.ig_user_id}'),
            params={
                'access_token': config_ig.access_token,
                'fields': 'username,name,profile_picture_url',
            },
            timeout=timeout,
        )
    except Exception as e:
        return False, {'message': f'Error de conexion con Instagram Graph: {e}'}
    if r.status_code != 200:
        return False, {'message': f'Meta respondio {r.status_code}: {r.text[:400]}'}
    data = r.json()
    if data.get('username') and data['username'] != config_ig.username:
        config_ig.username = data['username']
        config_ig.ultima_sincronizacion = _tz.now()
        config_ig.save(update_fields=['username', 'ultima_sincronizacion'])
    else:
        config_ig.ultima_sincronizacion = _tz.now()
        config_ig.save(update_fields=['ultima_sincronizacion'])
    return True, {
        'message': f'Instagram conectado: @{data.get("username", "?")}',
        'username': data.get('username'),
        'name':     data.get('name'),
        'profile_picture_url': data.get('profile_picture_url'),
    }


def validar_messenger_desde_graph(session, config_fb, timeout=10):
    """Pinguea Graph API contra `page_id` para validar credenciales Messenger.
    Devuelve `(ok, info_dict)`. Persiste page_name/ultima_sincronizacion si OK.
    """
    from django.utils import timezone as _tz
    if not (config_fb and config_fb.access_token and config_fb.page_id):
        return False, {'message': 'Faltan credenciales Messenger (access_token / page_id).'}
    try:
        r = requests.get(
            build_graph_url(f'/{config_fb.page_id}'),
            params={
                'access_token': config_fb.access_token,
                'fields': 'name,category,fan_count,verification_status',
            },
            timeout=timeout,
        )
    except Exception as e:
        return False, {'message': f'Error de conexion con Messenger Graph: {e}'}
    if r.status_code != 200:
        return False, {'message': f'Meta respondio {r.status_code}: {r.text[:400]}'}
    data = r.json()
    if data.get('name') and data['name'] != config_fb.page_name:
        config_fb.page_name = data['name']
        config_fb.ultima_sincronizacion = _tz.now()
        config_fb.save(update_fields=['page_name', 'ultima_sincronizacion'])
    else:
        config_fb.ultima_sincronizacion = _tz.now()
        config_fb.save(update_fields=['ultima_sincronizacion'])
    return True, {
        'message': f'Messenger conectado: {data.get("name", "Page")}',
        'name':                data.get('name'),
        'category':            data.get('category'),
        'fan_count':           data.get('fan_count'),
        'verification_status': data.get('verification_status'),
    }


def obtener_perfil_usuario_messenger(config_fb, psid, timeout=8):
    """User Profile API de Messenger para un PSID.

    Messenger solo expone nombre y foto del usuario (`first_name`, `last_name`,
    `profile_pic`) — NO hay username, email ni teléfono en esta API.
    Devuelve dict {'nombre', 'username', 'foto', 'raw'} o None si falla.
    """
    if not (config_fb and config_fb.access_token and psid):
        return None
    data = None
    for campos in ('first_name,last_name,profile_pic', 'name,profile_pic'):
        try:
            r = requests.get(
                build_graph_url(f'/{psid}'),
                params={'access_token': config_fb.access_token, 'fields': campos},
                timeout=timeout,
            )
        except Exception:
            return None
        if r.status_code == 200:
            data = r.json()
            break
    if not data:
        return None
    nombre = (data.get('name')
              or ' '.join(x for x in (data.get('first_name'), data.get('last_name')) if x)).strip()
    return {
        'nombre':   nombre,
        'username': '',
        'foto':     data.get('profile_pic') or '',
        'raw':      data,
    }


def obtener_perfil_usuario_instagram(config_ig, igsid, timeout=8):
    """User Profile API de Instagram Messaging para un IGSID.

    Expone `name`, `username`, `profile_pic` y (según permisos de la app)
    `follower_count`, `is_user_follow_business`, `is_business_follow_user`.
    NO hay email ni teléfono. Si el set completo falla (permisos), reintenta
    con el set mínimo. Devuelve dict {'nombre', 'username', 'foto', 'raw'} o None.
    """
    if not (config_ig and config_ig.access_token and igsid):
        return None
    data = None
    for campos in (
        'name,username,profile_pic,follower_count,is_user_follow_business,is_business_follow_user',
        'name,username,profile_pic',
    ):
        try:
            r = requests.get(
                build_graph_url(f'/{igsid}'),
                params={'access_token': config_ig.access_token, 'fields': campos},
                timeout=timeout,
            )
        except Exception:
            return None
        if r.status_code == 200:
            data = r.json()
            break
    if not data:
        return None
    username = data.get('username') or ''
    nombre = (data.get('name') or '').strip()
    if nombre and username:
        nombre = f'{nombre} (@{username})'
    elif username:
        nombre = f'@{username}'
    return {
        'nombre':   nombre,
        'username': username,
        'foto':     data.get('profile_pic') or '',
        'raw':      data,
    }


def sincronizar_meta_desde_graph(session, config, timeout=10):
    """Consulta Graph API con `config.access_token + phone_number_id` y persiste
    `display_phone_number` / `quality_rating` / `messaging_limit_tier` /
    `ultima_sincronizacion`. Si obtiene `display_phone_number` válido, también
    actualiza `session.numero` y marca la sesión como `'conectado'`.

    Devuelve `(ok: bool, payload: dict)`.
    """
    from django.utils import timezone as _tz

    if not (config and config.access_token and config.phone_number_id):
        return False, {'message': 'Faltan credenciales Meta (access_token / phone_number_id).'}
    try:
        r = requests.get(
            build_graph_url(f'/{config.phone_number_id}'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            params={'fields': 'display_phone_number,verified_name,quality_rating,messaging_limit_tier'},
            timeout=timeout,
        )
    except Exception as e:
        return False, {'message': f'Error de conexion con Meta: {str(e)}'}
    if r.status_code != 200:
        return False, {'message': f'Meta respondio {r.status_code}: {r.text[:400]}'}
    data = r.json()
    config.display_phone_number = data.get('display_phone_number') or config.display_phone_number
    config.quality_rating = (data.get('quality_rating') or 'UNKNOWN').upper()
    if data.get('messaging_limit_tier'):
        config.messaging_limit_tier = data.get('messaging_limit_tier')
    if data.get('verified_name'):
        config.verified_name = data.get('verified_name')
    config.ultima_sincronizacion = _tz.now()
    config.save(update_fields=[
        'display_phone_number', 'quality_rating',
        'messaging_limit_tier', 'verified_name', 'ultima_sincronizacion',
    ])
    numero_sincronizado = None
    if config.display_phone_number:
        numero_limpio = ''.join(c for c in config.display_phone_number if c.isdigit())
        updates = set()
        if numero_limpio and session.numero != numero_limpio:
            session.numero = numero_limpio
            updates.add('numero')
        if session.estado != 'conectado':
            session.estado = 'conectado'
            updates.add('estado')
        if updates:
            session.save(update_fields=list(updates))
        numero_sincronizado = numero_limpio or None
    return True, {
        'message': 'Conexion con Meta verificada correctamente.',
        'display_phone_number': config.display_phone_number,
        'quality_rating': config.get_quality_rating_display(),
        'messaging_limit_tier': config.get_messaging_limit_tier_display() if config.messaging_limit_tier else None,
        'verified_name': data.get('verified_name'),
        'numero': numero_sincronizado,
    }
