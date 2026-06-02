#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostico de conexion Meta WhatsApp Cloud API — integrado al CRM.

Valida, contra la Graph API REAL de Meta, el estado de un numero y su conexion
(token, numero, WABA, suscripciones, webhook), y compara cada valor con lo que
tiene registrado el CRM. A diferencia de un script suelto, NO hay que editar un
bloque CONFIG: lee todo de la BD (ConfigMeta + credenciales de la Meta App) por
--sesion-id.

Python 3.9 (usa typing.Optional, no str | None). Solo hace GET (lectura) +
un GET de sondeo al webhook. No registra ni modifica nada en Meta.

Uso:
    python prueba_conexion_meta.py --sesion-id 39
    python prueba_conexion_meta.py --sesion-id 39 --sesion-ok 37
        (--sesion-ok = el numero que SI funciona, para confirmar misma WABA)

Que revisa:
    1. Token de acceso        GET /me  +  /debug_token (scopes, expiracion)
    2. Estado del numero      GET /{phone_number_id}  (status, calidad, etc)
    3. WABA y sus numeros     GET /{waba_id}/phone_numbers  (membresia, comparten WABA)
    4. Apps suscritas         GET /{waba_id}/subscribed_apps (+ override_callback_uri)
    5. Webhook a nivel app    GET /{app_id}/subscriptions (campo 'messages')
    6. Sondeo del endpoint     GET challenge al callback (verify_token + WAF)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
django.setup()

import requests  # noqa: E402
from django.conf import settings  # noqa: E402

from meta.urls import build_graph_url  # noqa: E402
from meta.credenciales import get_meta_app_credentials  # noqa: E402
from whatsapp.models import SesionWhatsApp, ConfigMeta  # noqa: E402


# ---------------------------------------------------------------------------
# Salida (sin ANSI para que se vea bien en Windows)
# ---------------------------------------------------------------------------
def title(txt: str) -> None:
    print('\n' + '=' * 64)
    print(txt)
    print('=' * 64)


def ok(txt: str) -> None:
    print(f'  [OK] {txt}')


def fail(txt: str) -> None:
    print(f'  [XX] {txt}')


def warn(txt: str) -> None:
    print(f'  [!!] {txt}')


def info(txt: str) -> None:
    print(f'       {txt}')


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------
def graph_get(path: str, token: str,
              params: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    p: Dict[str, Any] = dict(params or {})
    p['access_token'] = token
    try:
        resp = requests.get(build_graph_url(f'/{path.lstrip("/")}'), params=p, timeout=30)
        try:
            data = resp.json()
        except ValueError:
            data = {'_raw': resp.text}
        return resp.status_code, data
    except requests.RequestException as e:
        return 0, {'error': {'message': f'Excepcion de red: {e}'}}


def norm_phone(value: Optional[str]) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def compare(label: str, crm_val: Any, meta_val: Any, phone: bool = False) -> bool:
    if phone:
        eq = norm_phone(crm_val) == norm_phone(meta_val)
    else:
        eq = str(crm_val).strip() == str(meta_val).strip()
    if eq:
        ok(f'{label}: coincide ({meta_val})')
    else:
        fail(f'{label}: DISCREPANCIA')
        info(f'CRM : {crm_val}')
        info(f'Meta: {meta_val}')
    return eq


# ---------------------------------------------------------------------------
# Chequeos
# ---------------------------------------------------------------------------
def check_token(config: ConfigMeta, app_id: str, app_secret: str) -> None:
    title('1. TOKEN DE ACCESO  (GET /me  +  /debug_token)')
    token = config.access_token
    if not token:
        fail('La sesion no tiene access_token cargado.')
        return

    code, data = graph_get('me', token, params={'fields': 'id,name'})
    if code == 200:
        ok(f"Token valido. Identidad: {data.get('name')} (id={data.get('id')})")
    else:
        fail(f'Token NO valido (HTTP {code})')
        info(json.dumps(data.get('error', data), ensure_ascii=False))
        return

    app_tok = f'{app_id}|{app_secret}' if (app_id and app_secret) else token
    code, data = graph_get('debug_token', app_tok,
                           params={'input_token': token})
    if code == 200 and 'data' in data:
        d = data['data']
        scopes = d.get('scopes', [])
        ok(f"App ID del token: {d.get('app_id')}")
        info(f"Tipo: {d.get('type')} | Valido: {d.get('is_valid')}")
        exp = d.get('expires_at')
        info(f"Expira: {'nunca' if exp == 0 else exp}")
        for s in ('whatsapp_business_messaging', 'whatsapp_business_management'):
            (ok if s in scopes else warn)(
                f"Permiso {'presente' if s in scopes else 'NO visible'}: {s}")
        if app_id:
            compare('App ID (token vs CRM)', app_id, d.get('app_id'))
    else:
        warn('No se pudo inspeccionar con /debug_token (falta app_secret de la '
             'Meta App o token de otra app). No es critico.')


def check_phone_number(config: ConfigMeta) -> None:
    title('2. ESTADO DEL NUMERO  (GET /{PHONE_NUMBER_ID})')
    fields = ('display_phone_number,verified_name,quality_rating,'
              'code_verification_status,name_status,status,platform_type,'
              'messaging_limit_tier,throughput')
    code, data = graph_get(config.phone_number_id, config.access_token,
                           params={'fields': fields})
    if code != 200:
        fail(f'No se pudo leer el numero (HTTP {code})')
        info(json.dumps(data.get('error', data), ensure_ascii=False))
        return

    ok('Numero leido desde Meta:')
    info(f"status            : {data.get('status')}")
    info(f"platform_type     : {data.get('platform_type', '(no informado)')}")
    info(f"quality_rating    : {data.get('quality_rating')}")
    info(f"messaging tier    : {data.get('messaging_limit_tier')}")
    info(f"throughput        : {data.get('throughput')}")
    info(f"name_status       : {data.get('name_status')}")
    info(f"code_verification : {data.get('code_verification_status')}")

    print()
    compare('display_phone_number', config.display_phone_number,
            data.get('display_phone_number'), phone=True)

    status = str(data.get('status', '')).upper()
    if status == 'CONNECTED':
        ok('status = CONNECTED -> registrado en Cloud API.')
    else:
        fail(f'status = {status} -> NO CONNECTED. Revisa /register.')

    platform = str(data.get('platform_type', '') or '')
    if platform and platform not in ('CLOUD_API',):
        warn(f'platform_type = {platform} -> posible COEXISTENCIA con la app de '
             'WhatsApp (la app se come los entrantes).')


def check_waba_numbers(config: ConfigMeta, phone_id_ok: str) -> None:
    title('3. WABA Y SUS NUMEROS  (GET /{WABA_ID}/phone_numbers)')
    code, data = graph_get(config.waba_id, config.access_token,
                           params={'fields': 'id,name,timezone_id,'
                                             'business_verification_status,'
                                             'account_review_status'})
    if code == 200:
        ok(f"WABA leida: {data.get('name')} (id={data.get('id')})")
        info(f"business_verification_status: {data.get('business_verification_status')}")
        info(f"account_review_status: {data.get('account_review_status')}")
    else:
        warn(f'No se pudieron leer datos de la WABA (HTTP {code})')
        info(json.dumps(data.get('error', data), ensure_ascii=False))

    code, data = graph_get(f'{config.waba_id}/phone_numbers', config.access_token,
                           params={'fields': 'id,display_phone_number,'
                                             'verified_name,status,quality_rating'})
    if code != 200:
        fail(f'No se pudo listar phone_numbers (HTTP {code})')
        info(json.dumps(data.get('error', data), ensure_ascii=False))
        return

    numeros: List[Dict[str, Any]] = data.get('data', [])
    ok(f'La WABA tiene {len(numeros)} numero(s):')
    ids: List[str] = []
    for n in numeros:
        ids.append(str(n.get('id')))
        info(f"- {n.get('display_phone_number')}  id={n.get('id')}  "
             f"status={n.get('status')}  name='{n.get('verified_name')}'")

    print()
    if str(config.phone_number_id) in ids:
        ok(f'El numero ({config.phone_number_id}) pertenece a esta WABA.')
    else:
        fail(f'El numero ({config.phone_number_id}) NO aparece en esta WABA. '
             'Revisa phone_number_id o waba_id.')

    if phone_id_ok:
        if phone_id_ok in ids:
            ok(f'El numero que SI funciona ({phone_id_ok}) tambien esta en esta '
               'WABA -> comparten WABA. Si uno recibe y el otro no, el corte es '
               'a nivel NUMERO (coexistencia), no de suscripcion.')
        else:
            warn(f'El numero que funciona ({phone_id_ok}) NO esta en esta WABA '
                 '-> WABAs distintas. Revisa la suscripcion de ESTA WABA.')


def check_subscribed_apps(config: ConfigMeta, app_id: str) -> None:
    title('4. APPS SUSCRITAS A LA WABA  (GET /{WABA_ID}/subscribed_apps)')
    code, data = graph_get(f'{config.waba_id}/subscribed_apps', config.access_token)
    if code != 200:
        fail(f'No se pudo leer subscribed_apps (HTTP {code})')
        info(json.dumps(data.get('error', data), ensure_ascii=False))
        return

    apps: List[Dict[str, Any]] = data.get('data', [])
    if not apps:
        fail('NINGUNA app suscrita a esta WABA. Los entrantes no llegan a ningun webhook.')
        info('Suscribi con: POST /{WABA_ID}/subscribed_apps')
        return

    ok(f'{len(apps)} app(s) suscrita(s):')
    found = False
    for a in apps:
        wad = a.get('whatsapp_business_api_data', {})
        a_id = str(wad.get('id', a.get('id', '')))
        info(f"- app id={a_id}  name='{wad.get('name', '?')}'")
        override = wad.get('override_callback_uri')
        if override:
            warn(f'  override_callback_uri: {override} '
                 '(los eventos de esta WABA van a esa URL, no al callback app-level)')
        if a_id == str(app_id):
            found = True

    print()
    if found:
        ok(f'Tu app del CRM ({app_id}) esta suscrita a la WABA.')
    else:
        warn(f'Tu app del CRM ({app_id}) NO aparece. Verifica el app_id.')


def check_app_webhook_fields(config: ConfigMeta, app_id: str, app_secret: str) -> None:
    title('5. CAMPOS DEL WEBHOOK A NIVEL APP  (GET /{APP_ID}/subscriptions)')
    if not (app_id and app_secret):
        warn('Faltan App ID / App Secret (Seguridad -> Credenciales Meta App). '
             'Se omite. El campo "messages" se ve en developers.facebook.com > '
             'WhatsApp > Configuration.')
        return

    app_tok = f'{app_id}|{app_secret}'
    code, data = graph_get(f'{app_id}/subscriptions', app_tok)
    if code != 200:
        warn(f'No se pudo leer /subscriptions (HTTP {code})')
        info(json.dumps(data.get('error', data), ensure_ascii=False))
        return

    subs: List[Dict[str, Any]] = data.get('data', [])
    wa_sub = next((s for s in subs if s.get('object') == 'whatsapp_business_account'), None)
    if not wa_sub:
        fail("La app NO tiene suscripcion al objeto 'whatsapp_business_account'.")
        return

    ok("Suscripcion 'whatsapp_business_account' encontrada:")
    info(f"callback_url: {wa_sub.get('callback_url')}")
    field_names = []
    for f in wa_sub.get('fields', []):
        field_names.append(f.get('name') if isinstance(f, dict) else str(f))
    info(f"fields: {', '.join(str(x) for x in field_names)}")

    if 'messages' in field_names:
        ok("Campo 'messages' SUSCRITO -> los entrantes deben llegar.")
    else:
        fail("Campo 'messages' NO suscrito -> Meta NO envia entrantes. Tildalo "
             'en developers.facebook.com > WhatsApp > Configuration.')

    callback_crm = (settings.URL_GENERAL or '').rstrip('/') + '/whatsapp/meta_webhook/'
    compare('callback_url', callback_crm, wa_sub.get('callback_url'))


def check_webhook_endpoint(config: ConfigMeta) -> None:
    title('6. SONDEO DEL ENDPOINT DEL WEBHOOK  (GET challenge)')
    url = (settings.URL_GENERAL or '').rstrip('/') + '/whatsapp/meta_webhook/'
    challenge = '12345_test_diagnostico'
    params = {
        'hub.mode': 'subscribe',
        'hub.verify_token': config.webhook_verify_token,
        'hub.challenge': challenge,
    }
    info(f'GET {url}')
    try:
        resp = requests.get(url, params=params, timeout=20)
    except requests.RequestException as e:
        fail(f'No se pudo alcanzar el endpoint: {e}')
        info('Si esto falla, Cloudflare/WAF o el servidor estan bloqueando.')
        return

    info(f'HTTP {resp.status_code}')
    body = (resp.text or '').strip()
    if resp.status_code == 200 and body == challenge:
        ok('El endpoint responde el challenge (verify_token OK, ruta GET funciona).')
    elif resp.status_code == 200:
        warn('Responde 200 pero el body no es el challenge esperado.')
        info(f'Esperado: {challenge} | Recibido: {body[:120]}')
    elif resp.status_code in (401, 403):
        warn(f'HTTP {resp.status_code}: verify_token rechazado o WAF bloqueando el GET.')
    else:
        warn(f'Respuesta inesperada (HTTP {resp.status_code}).')


def resumen(config: ConfigMeta) -> None:
    title('RESUMEN / SIGUIENTE PASO')
    info('Si TODO sale OK arriba pero los entrantes de ESTE numero no llegan al')
    info('CRM, y el otro numero (misma WABA) SI recibe -> NO es tu codigo ni la')
    info('suscripcion. La causa tipica es COEXISTENCIA: el numero esta logueado')
    info('en la app de WhatsApp y la app intercepta los entrantes.')
    print()
    info('Pista clave: el chequeo 2 (platform_type) y el status. Si status=CONNECTED')
    info(f"y platform_type != CLOUD_API para {config.phone_number_id} -> coexistencia.")
    info('Fix: sacar el numero de la app de WhatsApp y re-registrar en Cloud API.')


def main() -> None:
    parser = argparse.ArgumentParser(description='Diagnostico de conexion Meta del CRM.')
    parser.add_argument('--sesion-id', type=int, required=True,
                        help='ID de la sesion Meta a diagnosticar.')
    parser.add_argument('--sesion-ok', type=int, default=None,
                        help='ID de la sesion que SI funciona (para comparar WABA).')
    args = parser.parse_args()

    sesion = SesionWhatsApp.objects.filter(id=args.sesion_id, proveedor='meta').first()
    if not sesion:
        print(f'No existe sesion Meta con id={args.sesion_id}.')
        sys.exit(1)
    config = getattr(sesion, 'config_meta', None)
    if not config:
        print(f'La sesion {args.sesion_id} no tiene ConfigMeta.')
        sys.exit(1)

    phone_id_ok = ''
    if args.sesion_ok:
        s_ok = SesionWhatsApp.objects.filter(id=args.sesion_ok, proveedor='meta').first()
        cfg_ok = getattr(s_ok, 'config_meta', None) if s_ok else None
        phone_id_ok = str(cfg_ok.phone_number_id) if cfg_ok else ''

    try:
        app_id, app_secret = get_meta_app_credentials()
    except Exception:
        app_id, app_secret = '', ''

    print('Diagnostico Meta WhatsApp Cloud API')
    print(f'Sesion {sesion.id} · {sesion.nombre or sesion.numero}')
    print(f'phone_number_id={config.phone_number_id} | waba={config.waba_id} | app_id={app_id}')

    check_token(config, app_id, app_secret)
    check_phone_number(config)
    check_waba_numbers(config, phone_id_ok)
    check_subscribed_apps(config, app_id)
    check_app_webhook_fields(config, app_id, app_secret)
    check_webhook_endpoint(config)
    resumen(config)
    print()


if __name__ == '__main__':
    main()
