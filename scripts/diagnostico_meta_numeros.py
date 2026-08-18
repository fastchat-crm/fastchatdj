"""Diagnostico comparativo de numeros Meta Cloud API.

Consulta Graph API para CADA sesion Meta del CRM y muestra lado a lado el
estado real del numero + la suscripcion de su WABA, para identificar cual de
los numeros es el problematico (envia pero no recibe, no esta CONNECTED,
coexistencia con la app, override de webhook, etc).

Que revisa por numero:
  - GET /{phone_number_id}  -> status, calidad, platform_type (clave para
    detectar coexistencia con la app de WhatsApp), name_status, throughput.
  - GET /{waba_id}/subscribed_apps -> apps suscritas + override_callback_uri
    (si una WABA tiene override, sus eventos van a otra URL, no al callback
    app-level).
  - Opcional: envia un texto de prueba con --enviar <numero_destino> para
    comparar el envio de cada numero (devuelve wamid o el error de Meta).

Uso:
    python scripts/diagnostico_meta_numeros.py
    python scripts/diagnostico_meta_numeros.py --sesion-id 37 39
    python scripts/diagnostico_meta_numeros.py --enviar 593987654321

NO modifica nada (salvo que uses --enviar, que manda un mensaje real). Solo
lee de la BD y consulta Graph.
"""
import argparse
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
application = get_wsgi_application()

import requests

from meta.urls import build_graph_url
from whatsapp.models import SesionWhatsApp, ConfigMeta


PHONE_FIELDS = (
    'display_phone_number,verified_name,quality_rating,status,name_status,'
    'platform_type,code_verification_status,throughput'
)


def _err(r):
    try:
        return r.json().get('error', {}).get('message', r.text[:300])
    except Exception:
        return r.text[:300]


def consultar_numero(config):
    """GET /{phone_number_id} con los campos de salud."""
    try:
        r = requests.get(
            build_graph_url(f'/{config.phone_number_id}'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            params={'fields': PHONE_FIELDS},
            timeout=15,
        )
    except Exception as ex:
        return {'ok': False, 'error': f'red: {ex}'}
    if r.status_code != 200:
        return {'ok': False, 'error': _err(r)}
    return {'ok': True, 'data': r.json() or {}}


def consultar_subscribed_apps(config):
    """GET /{waba_id}/subscribed_apps con override_callback_uri."""
    try:
        r = requests.get(
            build_graph_url(f'/{config.waba_id}/subscribed_apps'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            timeout=15,
        )
    except Exception as ex:
        return {'ok': False, 'error': f'red: {ex}'}
    if r.status_code != 200:
        return {'ok': False, 'error': _err(r)}
    return {'ok': True, 'data': (r.json() or {}).get('data') or []}


def enviar_prueba(config, destino):
    """POST /{phone_number_id}/messages -> texto de prueba."""
    destino_limpio = ''.join(ch for ch in destino if ch.isdigit())
    try:
        r = requests.post(
            build_graph_url(f'/{config.phone_number_id}/messages'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            json={
                'messaging_product': 'whatsapp',
                'to': destino_limpio,
                'type': 'text',
                'text': {'body': 'Prueba de conexion Cloud API (diagnostico).'},
            },
            timeout=20,
        )
    except Exception as ex:
        return {'ok': False, 'error': f'red: {ex}'}
    if r.status_code != 200:
        return {'ok': False, 'error': _err(r)}
    data = r.json() or {}
    wamid = ''
    if data.get('messages'):
        wamid = data['messages'][0].get('id', '')
    return {'ok': True, 'wamid': wamid}


def linea(txt=''):
    print(txt)


def diagnosticar(sesion, destino_envio=None):
    config = getattr(sesion, 'config_meta', None)
    linea('=' * 70)
    linea(f'SESION {sesion.id} · {sesion.nombre or sesion.numero}')
    linea('=' * 70)
    if not config:
        linea('  [X] Sin ConfigMeta. No es una sesion Meta valida.')
        return {'sesion': sesion, 'problema': True, 'motivo': 'sin ConfigMeta'}

    linea(f'  Numero (CRM):     {sesion.numero}')
    linea(f'  WABA ID:          {config.waba_id}')
    linea(f'  Phone Number ID:  {config.phone_number_id}')
    linea(f'  Access token:     ...{(config.access_token or "")[-4:]}')
    linea('')

    problemas = []

    # 1) Estado del numero en Graph
    info = consultar_numero(config)
    linea('  --- Estado del numero en Meta (Graph) ---')
    if not info['ok']:
        linea(f'  [X] No pude consultar el numero: {info["error"]}')
        problemas.append(f'GET numero fallo: {info["error"]}')
    else:
        d = info['data']
        status = d.get('status', '?')
        platform = d.get('platform_type', '(no informado)')
        linea(f'  Display:          {d.get("display_phone_number", "?")}')
        linea(f'  Nombre verif.:    {d.get("verified_name", "?")}')
        linea(f'  Status:           {status}')
        linea(f'  platform_type:    {platform}')
        linea(f'  Calidad:          {d.get("quality_rating", "?")}')
        linea(f'  name_status:      {d.get("name_status", "?")}')
        linea(f'  code_verif:       {d.get("code_verification_status", "?")}')
        if status != 'CONNECTED':
            problemas.append(f'status={status} (no CONNECTED)')
        # platform_type CLOUD_API es lo esperado. Otra cosa sugiere coexistencia
        # con la app de WhatsApp (los entrantes los agarra la app).
        if platform and platform not in ('CLOUD_API', '(no informado)'):
            problemas.append(f'platform_type={platform} (posible coexistencia con la app)')
    linea('')

    # 2) Suscripcion de la WABA
    subs = consultar_subscribed_apps(config)
    linea('  --- Suscripcion de la WABA (subscribed_apps) ---')
    if not subs['ok']:
        linea(f'  [X] No pude consultar subscribed_apps: {subs["error"]}')
        problemas.append(f'subscribed_apps fallo: {subs["error"]}')
    else:
        apps = subs['data']
        if not apps:
            linea('  [X] NINGUNA app suscrita a esta WABA -> no llegan webhooks.')
            problemas.append('WABA sin apps suscritas')
        for app in apps:
            api_data = app.get('whatsapp_business_api_data') or {}
            override = api_data.get('override_callback_uri') or '(ninguno)'
            linea(f'  App suscrita:     {api_data.get("name", "?")} (id={api_data.get("id", "?")})')
            linea(f'  override_callback_uri: {override}')
            if override and override != '(ninguno)':
                problemas.append(f'override_callback_uri seteado: {override} '
                                 '(los eventos van a esa URL, no al callback app-level)')
    linea('')

    # 3) Envio opcional
    if destino_envio:
        linea(f'  --- Envio de prueba -> {destino_envio} ---')
        env = enviar_prueba(config, destino_envio)
        if env['ok']:
            linea(f'  [OK] Meta acepto el envio. wamid={env["wamid"]}')
            linea('  (wamid = aceptado, NO necesariamente entregado)')
        else:
            linea(f'  [X] Envio rechazado: {env["error"]}')
            problemas.append(f'envio fallo: {env["error"]}')
        linea('')

    if problemas:
        linea('  >>> PROBLEMAS DETECTADOS:')
        for p in problemas:
            linea(f'      - {p}')
    else:
        linea('  >>> Sin problemas obvios en Graph. Si igual no recibe, revisar '
              'coexistencia (numero logueado en la app de WhatsApp).')
    linea('')
    return {'sesion': sesion, 'problema': bool(problemas), 'motivos': problemas}


def main():
    parser = argparse.ArgumentParser(description='Diagnostico comparativo de numeros Meta.')
    parser.add_argument('--sesion-id', nargs='*', type=int, default=None,
                        help='IDs de sesion a diagnosticar (default: todas las Meta).')
    parser.add_argument('--enviar', type=str, default=None,
                        help='Numero destino E.164 sin + para probar el envio de cada numero.')
    args = parser.parse_args()

    qs = SesionWhatsApp.objects.filter(proveedor='meta')
    if args.sesion_id:
        qs = qs.filter(id__in=args.sesion_id)
    sesiones = list(qs.order_by('id'))

    if not sesiones:
        linea('No se encontraron sesiones Meta.')
        return

    linea('')
    linea(f'Diagnosticando {len(sesiones)} sesion(es) Meta...')
    if args.enviar:
        linea(f'(con envio de prueba a {args.enviar})')
    linea('')

    resultados = [diagnosticar(s, destino_envio=args.enviar) for s in sesiones]

    linea('#' * 70)
    linea('RESUMEN')
    linea('#' * 70)
    for res in resultados:
        s = res['sesion']
        etiqueta = 'PROBLEMA' if res.get('problema') else 'OK'
        linea(f'  [{etiqueta:8}] Sesion {s.id} · {s.nombre or s.numero}')
        for m in res.get('motivos', []):
            linea(f'             - {m}')
    linea('')
    linea('Nota: si dos numeros comparten WABA y uno recibe y el otro no, sin '
          'problemas en Graph, la causa tipica es COEXISTENCIA: el numero esta '
          'logueado en la app de WhatsApp y la app intercepta los entrantes.')


if __name__ == '__main__':
    main()
