"""Helpers compartidos por sesiones_baileys_view.py y sesiones_meta_view.py.

Aca viven las utilidades que no son especificas de un proveedor:
- Parser de errores Meta con hints + link CTA.
- Sincronizador de credenciales Meta con Graph API.

Se mantienen aca para que cada view especializado importe solo lo que necesita
sin tocar el codigo del otro proveedor.
"""
from __future__ import annotations

import json
import logging
import re

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hints de error Meta
# ---------------------------------------------------------------------------

def hint_error_meta(error_text: str) -> dict:
    """Decodifica el error de Graph API y devuelve:
        {'text': str, 'link': str|None, 'link_label': str|None}
    `text` es la recomendacion en prosa. `link` es una URL CTA opcional para
    que la UI arme un boton. Si no hay match devuelve {'text': '', ...}.
    """
    EMPTY = {'text': '', 'link': None, 'link_label': None}
    if not error_text:
        return EMPTY
    try:
        m = re.search(r'\{.*\}', str(error_text), flags=re.DOTALL)
        if not m:
            return EMPTY
        err = json.loads(m.group(0)).get('error') or {}
    except Exception:
        return EMPTY
    code = err.get('code')
    sub = err.get('error_subcode')

    # Catalogo de hints por codigo Meta. Ref:
    # developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
    if code == 133010:
        return {
            'text': ('El phone_number_id no esta registrado en Cloud API. Tenes que darle '
                     '"Register" en el Developer Portal → WhatsApp → API Setup e ingresar '
                     'un PIN de 6 digitos. Si el boton "Register" no aparece, tu WABA aun no '
                     'esta verificado por Meta.'),
            'link': 'https://developers.facebook.com/apps',
            'link_label': 'Abrir Developer Portal → API Setup',
        }
    if code == 131030:
        return {
            'text': ('El numero destino no esta en la lista de "test recipients" (sandbox). '
                     'En API Setup agregalo en "To" antes de enviar, y aceptalo desde WhatsApp '
                     'cuando llegue la primera invitacion.'),
            'link': 'https://developers.facebook.com/apps',
            'link_label': 'Abrir API Setup',
        }
    if code == 132000:
        return {
            'text': 'La plantilla no existe o el idioma no coincide. Verifica que "hello_world" + "en_US" esten aprobadas para este WABA.',
            'link': 'https://business.facebook.com/wa/manage/message-templates/',
            'link_label': 'Abrir gestor de plantillas',
        }
    if code == 132001:
        return {'text': 'Plantilla no aprobada por Meta aun. Esta en estado PENDING o REJECTED.',
                'link': 'https://business.facebook.com/wa/manage/message-templates/',
                'link_label': 'Ver estado de plantillas'}
    if code == 132005:
        return {'text': 'Numero de parametros en la plantilla no coincide con los placeholders {{1}}, {{2}}, etc.',
                'link': None, 'link_label': None}
    if code == 131051:
        return {'text': 'El tipo de mensaje no es soportado para este numero (seguramente no es WhatsApp Business).',
                'link': None, 'link_label': None}
    if code == 100 and sub == 2388072:
        return {'text': 'Meta rechaza el formato. En header/footer no se admiten newlines, negritas, emojis ni asteriscos.',
                'link': None, 'link_label': None}
    if code == 190:
        return {'text': 'Access Token invalido o expirado. Regeneralo (idealmente con System User para que sea permanente).',
                'link': 'https://business.facebook.com/latest/settings/system_users',
                'link_label': 'Abrir System Users'}
    if code == 1 and 'unknown error' in (err.get('message') or '').lower():
        return {'text': ('Probablemente falta scope en el token. Regeneralo desde Business Settings → '
                         'System Users con los permisos whatsapp_business_management + '
                         'whatsapp_business_messaging + business_management.'),
                'link': 'https://business.facebook.com/latest/settings/system_users',
                'link_label': 'Abrir System Users'}
    if code == 10 or code == 200:
        return {'text': 'Tu token no tiene el permiso necesario para esta operacion. Revisa los scopes asignados al System User.',
                'link': 'https://business.facebook.com/latest/settings/system_users',
                'link_label': 'Abrir System Users'}
    return EMPTY


def hint_como_texto(hint: dict) -> str:
    """Devuelve el hint como prefijo legible para concatenar al `message`."""
    if not hint or not hint.get('text'):
        return ''
    return ' Hint: ' + hint['text']


def adjuntar_hint_a_response(base: dict, err_raw) -> dict:
    """Agrega a `base` (dict para JsonResponse) los campos hint/hint_link/raw.
    Uso: `return JsonResponse(adjuntar_hint_a_response({'error': True, 'message': ...}, err_raw))`.
    """
    hint = hint_error_meta(err_raw) if err_raw else {}
    base = dict(base)
    base['hint'] = hint.get('text') or None
    base['hint_link'] = hint.get('link') or None
    base['hint_link_label'] = hint.get('link_label') or None
    base['raw'] = err_raw
    return base


# ---------------------------------------------------------------------------
# Sincronizador Meta → Graph API
# ---------------------------------------------------------------------------

def validar_instagram_desde_graph(session, config_ig, timeout=10):
    """Pinguea Graph API contra `ig_user_id` para validar credenciales IG.
    Devuelve (ok, info_dict). Persiste username/ultima_sincronizacion si OK.
    """
    from django.utils import timezone as _tz
    if not (config_ig and config_ig.access_token and config_ig.ig_user_id):
        return False, {'message': 'Faltan credenciales Instagram (access_token / ig_user_id).'}
    try:
        r = requests.get(
            f'https://graph.facebook.com/v22.0/{config_ig.ig_user_id}',
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
    Devuelve (ok, info_dict). Persiste page_name/ultima_sincronizacion si OK.
    """
    from django.utils import timezone as _tz
    if not (config_fb and config_fb.access_token and config_fb.page_id):
        return False, {'message': 'Faltan credenciales Messenger (access_token / page_id).'}
    try:
        r = requests.get(
            f'https://graph.facebook.com/v22.0/{config_fb.page_id}',
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


def sincronizar_meta_desde_graph(session, config, timeout=10):
    """Consulta Graph API con config.access_token + phone_number_id y persiste
    display_phone_number / quality_rating / messaging_limit_tier / ultima_sincronizacion.
    Si obtiene display_phone_number valido, tambien actualiza session.numero y marca la sesion
    como 'conectado'. Devuelve (ok: bool, payload: dict).
    """
    from django.utils import timezone as _tz
    from .services_meta import GRAPH_API_BASE

    if not (config and config.access_token and config.phone_number_id):
        return False, {'message': 'Faltan credenciales Meta (access_token / phone_number_id).'}
    try:
        r = requests.get(
            f'{GRAPH_API_BASE}/{config.phone_number_id}',
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
    config.ultima_sincronizacion = _tz.now()
    config.save(update_fields=[
        'display_phone_number', 'quality_rating',
        'messaging_limit_tier', 'ultima_sincronizacion',
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
            session.error_mensaje = None
            updates.add('estado')
            updates.add('error_mensaje')
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
