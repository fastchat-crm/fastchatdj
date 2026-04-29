"""Auto-detección de campos Meta a partir de App ID + Secret (+ opcional
System User Token).

Devuelve nombres de App, Business, System User ID, scopes, expiración del
token y — si Meta lo expone — el `config_id` del Embedded Signup de
WhatsApp Business.

Movido desde `seguridad/view_credencial_meta.py:_auto_detectar_meta`. La
firma es la misma; el legacy view re-exporta esta función con un alias
privado para no romper el código existente.
"""
from __future__ import annotations

import requests

from meta.urls import build_graph_url


# Endpoints conocidos de Meta para listar las Embedded Signup configurations.
# El nombre cambia entre versiones del Graph; probamos ambos.
_ENDPOINTS_CONFIG = (
    '/whatsapp_business_solution_configurations',
    '/whatsapp_solution_configurations',
)


def auto_detectar_meta(app_id: str, app_secret: str, system_user_token: str = '') -> dict:
    """Consulta Graph API y devuelve campos detectables.

    Retorna `{'error': bool, 'message'?: str, 'detectado'?: dict}`.

    Sólo App ID + App Secret → nombre de app + owner_business + intento de
    listar Embedded Signup configurations.
    Con `system_user_token` → también `system_user_id`, scopes, expiración.
    """
    if not app_id or not app_secret:
        return {'error': True, 'message': 'Falta App ID o App Secret.'}

    app_token = f'{app_id}|{app_secret}'
    detectado = {
        'app_name': '',
        'business_id': '',
        'business_name': '',
        'system_user_id': '',
        'scopes': [],
        'expires_at': 0,
        'config_id': '',
        'config_options': [],   # lista de {id, name} si Meta devuelve varias
        'hint': '',
    }

    try:
        r = requests.get(
            build_graph_url(f'/{app_id}'),
            params={'access_token': app_token, 'fields': 'id,name,namespace,category'},
            timeout=12,
        )
    except Exception as ex:
        return {'error': True, 'message': f'No pude llamar Graph API: {ex}'}

    if r.status_code != 200:
        try:
            err = r.json().get('error', {}).get('message', r.text[:200])
        except Exception:
            err = r.text[:200]
        return {'error': True, 'message': f'Meta rechazó las credenciales: {err}'}

    payload = r.json() or {}
    detectado['app_name'] = payload.get('name', '') or ''

    # Owner business: el field cambia entre versiones. Probamos varios.
    for biz_field in ('business', 'owner_business'):
        try:
            br = requests.get(
                build_graph_url(f'/{app_id}'),
                params={'access_token': app_token, 'fields': f'{biz_field}{{id,name}}'},
                timeout=10,
            )
            if br.status_code == 200:
                biz = (br.json() or {}).get(biz_field) or {}
                if biz.get('id'):
                    detectado['business_id'] = str(biz['id'])
                    detectado['business_name'] = biz.get('name') or ''
                    break
        except Exception:
            pass

    # Fallback: con system_user_token, listamos /me/businesses.
    if not detectado['business_id'] and system_user_token:
        try:
            mb = requests.get(
                build_graph_url('/me/businesses'),
                params={'access_token': system_user_token, 'fields': 'id,name'},
                timeout=10,
            )
            if mb.status_code == 200:
                lista = (mb.json() or {}).get('data') or []
                if lista:
                    detectado['business_id'] = str(lista[0].get('id') or '')
                    detectado['business_name'] = lista[0].get('name') or ''
        except Exception:
            pass

    if not detectado['business_id'] and not system_user_token:
        detectado['hint'] = (
            'App validada. Para detectar Business ID y System User ID necesitamos un '
            '<b>System User Token</b>. Generalo así: '
            '<a href="https://business.facebook.com/settings/system-users" target="_blank" rel="noopener">'
            'business.facebook.com/settings/system-users</a> '
            '→ tu System User → <b>Generate New Token</b> → seleccioná tu app '
            '<i>(la que detectamos arriba)</i> → marcá los scopes '
            '<code>business_management</code> + <code>whatsapp_business_management</code> + '
            '<code>whatsapp_business_messaging</code> → <b>Never expires</b> → copiá el token '
            '(Meta solo lo muestra una vez), pegalo en el campo de abajo y volvé a pulsar el botón.'
        )

    if system_user_token:
        try:
            d = requests.get(
                build_graph_url('/debug_token'),
                params={
                    'input_token': system_user_token,
                    'access_token': app_token,
                }, timeout=12,
            )
            if d.status_code == 200:
                data = (d.json() or {}).get('data', {}) or {}
                detectado['system_user_id'] = str(data.get('user_id') or '')
                detectado['scopes'] = data.get('scopes') or []
                detectado['expires_at'] = int(data.get('expires_at') or 0)
                if not data.get('is_valid', False):
                    return {'error': True, 'message': 'El System User Token no es válido (Meta lo rechazó).'}
            else:
                return {'error': True, 'message': f'debug_token falló: {d.status_code}'}
        except Exception as ex:
            return {'error': True, 'message': f'Error validando System User Token: {ex}'}

    # ── Embedded Signup config_id ──
    for ep in _ENDPOINTS_CONFIG:
        try:
            cr = requests.get(
                build_graph_url(f'/{app_id}{ep}'),
                params={'access_token': app_token, 'fields': 'id,name,description'},
                timeout=10,
            )
            if cr.status_code != 200:
                continue
            lista = (cr.json() or {}).get('data') or []
            if not lista:
                continue
            opts = []
            for item in lista:
                cid = str(item.get('id') or '').strip()
                if not cid:
                    continue
                opts.append({'id': cid, 'name': item.get('name') or '(sin nombre)'})
            if opts:
                detectado['config_options'] = opts
                if len(opts) == 1:
                    detectado['config_id'] = opts[0]['id']
                break
        except Exception:
            continue

    if not detectado['config_id'] and not detectado['config_options']:
        existing_hint = detectado.get('hint') or ''
        meta_url = (
            f'https://developers.facebook.com/apps/{app_id}/'
            'whatsapp-business/wa-embedded-signup/'
        )
        extra = (
            '<b>No pude obtener el Embedded Signup Config ID vía API</b> '
            '(Meta lo gatea — sólo Tech Providers lo ven). '
            'Sacalo manualmente:<br>'
            '<ol class="mb-0 mt-1 ps-3">'
            f'<li>Abrí <a href="{meta_url}" target="_blank" rel="noopener">'
            'developers.facebook.com → tu App → WhatsApp → Embedded Signup</a> '
            '<i>(en algunas cuentas: <code>WhatsApp → Configuration</code>)</i>.</li>'
            '<li>Si no hay ninguna, click <b>"Create configuration"</b>:<ul class="mb-0">'
            '<li>Setup type: <code>WhatsApp Business App Onboarding</code>.</li>'
            '<li>Features: <code>cloud_api</code> + <code>marketing_messages_lite</code> + '
            '<code>conversions_api</code>.</li>'
            '<li>Permissions: <code>whatsapp_business_management</code>, '
            '<code>whatsapp_business_messaging</code>, <code>business_management</code>.</li>'
            '<li>Guardar.</li></ul></li>'
            '<li>Copiá el <b>Configuration ID</b> (número largo ~16 dígitos) y pegalo '
            'en el campo de abajo.</li>'
            '</ol>'
        )
        detectado['hint'] = (existing_hint + '<br><br>' + extra) if existing_hint else extra

    return {'error': False, 'detectado': detectado}
