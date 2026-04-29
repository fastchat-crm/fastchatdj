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
# Verificadores de perfil contra Graph API — movidos a meta.perfiles.
# Re-exportamos para no romper imports legacy.
# ---------------------------------------------------------------------------
from meta.perfiles import (
    validar_instagram_desde_graph,
    validar_messenger_desde_graph,
    sincronizar_meta_desde_graph,
)
