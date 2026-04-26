"""Checklist completo de credenciales Meta — verifica App ID + Secret,
System User Token, scopes, Business Manager y WABAs accesibles.

Movido desde `seguridad/view_credencial_meta.py:_validar_credenciales`.
El view legacy re-exporta como alias privado para compat.
"""
from __future__ import annotations

import requests

from meta.urls import build_graph_url


SCOPES_REQUERIDOS = (
    'whatsapp_business_management',
    'whatsapp_business_messaging',
    'business_management',
)


def _check(label: str, ok: bool, detalle: str = '', severidad: str = 'ok') -> dict:
    """Estructura uniforme para cada item del validador."""
    return {
        'label': label,
        'ok': bool(ok),
        'detalle': detalle,
        'severidad': severidad if not ok else 'ok',
    }


_ENDPOINTS_CONFIG = (
    '/whatsapp_business_solution_configurations',
    '/whatsapp_solution_configurations',
)


def validar_credenciales(app_id: str, app_secret: str, business_id: str,
                         system_user_id: str, system_user_token: str,
                         config_id: str = '') -> list[dict]:
    """Corre todas las verificaciones contra Graph API y devuelve lista de checks."""
    checks: list[dict] = []

    if not app_id or not app_secret:
        checks.append(_check('App ID + Secret', False, 'Faltan App ID o App Secret.', 'error'))
        return checks

    app_token = f'{app_id}|{app_secret}'

    # 1) App ID + Secret
    try:
        r = requests.get(build_graph_url(f'/{app_id}'),
                         params={'access_token': app_token, 'fields': 'id,name'},
                         timeout=10)
        if r.status_code == 200 and (r.json() or {}).get('id'):
            checks.append(_check('App ID + Secret', True,
                                 f"App: {(r.json() or {}).get('name', '')}"))
        else:
            try:
                err = r.json().get('error', {}).get('message', r.text[:120])
            except Exception:
                err = r.text[:120]
            checks.append(_check('App ID + Secret', False, err, 'error'))
            return checks
    except Exception as ex:
        checks.append(_check('App ID + Secret', False, f'Error de red: {ex}', 'error'))
        return checks

    # 2) System User Token
    token_valido = False
    token_scopes: list = []
    token_user_id = ''
    if system_user_token:
        try:
            d = requests.get(build_graph_url('/debug_token'),
                             params={'input_token': system_user_token, 'access_token': app_token},
                             timeout=10)
            if d.status_code == 200:
                data = (d.json() or {}).get('data', {}) or {}
                if data.get('is_valid'):
                    token_valido = True
                    token_scopes = data.get('scopes') or []
                    token_user_id = str(data.get('user_id') or '')
                    expira = int(data.get('expires_at') or 0)
                    detalle = 'Never expires' if expira == 0 else f'Expira: {expira}'
                    checks.append(_check('System User Token', True, detalle))
                else:
                    checks.append(_check('System User Token', False,
                                         data.get('error', {}).get('message', 'Token inválido'), 'error'))
            else:
                checks.append(_check('System User Token', False, f'debug_token HTTP {d.status_code}', 'error'))
        except Exception as ex:
            checks.append(_check('System User Token', False, f'Error: {ex}', 'error'))
    else:
        checks.append(_check('System User Token', False, 'No configurado.', 'warning'))

    # 3) Scopes requeridos
    if token_valido:
        faltantes = [s for s in SCOPES_REQUERIDOS if s not in token_scopes]
        if not faltantes:
            checks.append(_check('Scopes requeridos', True,
                                 f'{len(SCOPES_REQUERIDOS)}/{len(SCOPES_REQUERIDOS)} presentes'))
        else:
            checks.append(_check('Scopes requeridos', False,
                                 'Faltan: ' + ', '.join(faltantes), 'error'))

    # 4) System User ID coincide con el del token
    if system_user_id and token_user_id:
        if system_user_id == token_user_id:
            checks.append(_check('System User ID', True, f'Coincide con el token (ID {token_user_id})'))
        else:
            checks.append(_check('System User ID', False,
                                 f'Discrepancia: form={system_user_id} vs token={token_user_id}', 'error'))
    elif system_user_id and not token_valido:
        checks.append(_check('System User ID', False,
                             'No verificable sin un System User Token válido.', 'warning'))
    elif not system_user_id:
        checks.append(_check('System User ID', False, 'No configurado.', 'warning'))

    # 5) Business Manager ID
    if business_id:
        if token_valido:
            try:
                br = requests.get(build_graph_url(f'/{business_id}'),
                                  params={'access_token': system_user_token, 'fields': 'id,name'},
                                  timeout=10)
                if br.status_code == 200 and (br.json() or {}).get('id'):
                    checks.append(_check('Business Manager ID', True,
                                         f"Business: {(br.json() or {}).get('name', '')}"))
                else:
                    try:
                        err = br.json().get('error', {}).get('message', br.text[:120])
                    except Exception:
                        err = br.text[:120]
                    checks.append(_check('Business Manager ID', False, err, 'error'))
            except Exception as ex:
                checks.append(_check('Business Manager ID', False, f'Error: {ex}', 'error'))
        else:
            checks.append(_check('Business Manager ID', False,
                                 'No verificable sin un System User Token válido.', 'warning'))
    else:
        checks.append(_check('Business Manager ID', False, 'No configurado (opcional).', 'warning'))

    # 6) Acceso a WhatsApp (lista de WABAs propiedad del business)
    if business_id and token_valido:
        try:
            w = requests.get(build_graph_url(f'/{business_id}/owned_whatsapp_business_accounts'),
                             params={'access_token': system_user_token, 'fields': 'id,name'},
                             timeout=10)
            if w.status_code == 200:
                wabas = (w.json() or {}).get('data') or []
                if wabas:
                    nombres = ', '.join(f"{wa.get('name', '')} ({wa.get('id', '')})" for wa in wabas[:3])
                    extra = '' if len(wabas) <= 3 else f' (+{len(wabas) - 3} más)'
                    checks.append(_check('WABAs accesibles', True,
                                         f"{len(wabas)} encontrada(s): {nombres}{extra}"))
                else:
                    checks.append(_check('WABAs accesibles', False,
                                         'El Business no tiene WhatsApp Business Accounts asociadas.',
                                         'warning'))
            else:
                checks.append(_check('WABAs accesibles', False,
                                     f'HTTP {w.status_code}', 'warning'))
        except Exception as ex:
            checks.append(_check('WABAs accesibles', False, f'Error: {ex}', 'warning'))

    # 7) Embedded Signup Config ID
    if config_id:
        # Listamos configurations de la app y vemos si el ID esta entre ellas.
        # El endpoint puede estar gateado (Tech Providers) — si Meta no nos
        # deja listar, no es error duro: emitimos warning explicativo.
        config_listed = False
        config_match = False
        config_match_name = ''
        last_err = ''
        for ep in _ENDPOINTS_CONFIG:
            try:
                cr = requests.get(build_graph_url(f'/{app_id}{ep}'),
                                  params={'access_token': app_token,
                                          'fields': 'id,name'},
                                  timeout=10)
                if cr.status_code == 200:
                    config_listed = True
                    lista = (cr.json() or {}).get('data') or []
                    for item in lista:
                        if str(item.get('id') or '').strip() == config_id:
                            config_match = True
                            config_match_name = item.get('name') or ''
                            break
                    if config_match:
                        break
                else:
                    try:
                        last_err = cr.json().get('error', {}).get('message', cr.text[:100])
                    except Exception:
                        last_err = cr.text[:100]
            except Exception as ex:
                last_err = str(ex)
        if config_match:
            detalle = f'Configuration: {config_match_name} (ID {config_id})' if config_match_name else f'ID {config_id} válido'
            checks.append(_check('Embedded Signup Config ID', True, detalle))
        elif config_listed:
            checks.append(_check('Embedded Signup Config ID', False,
                                 f'El ID {config_id} no aparece entre las configurations de la app.',
                                 'error'))
        else:
            # Meta gateó el endpoint — no podemos confirmar ni rechazar.
            checks.append(_check('Embedded Signup Config ID', False,
                                 'No verificable vía API (Meta gatea el endpoint para Tech Providers). '
                                 'El valor está cargado pero no podemos confirmar que sea válido. '
                                 + (f'[{last_err}]' if last_err else ''),
                                 'warning'))
    else:
        checks.append(_check('Embedded Signup Config ID', False,
                             'No configurado. Necessario para el flow Embedded Signup. '
                             'Sacalo en Meta For Developers → tu App → WhatsApp → Embedded Signup.',
                             'warning'))

    return checks
