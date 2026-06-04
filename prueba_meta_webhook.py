"""Probador del webhook Meta — sin necesidad de Meta ni de curl.

Uso (desde la raíz del proyecto, con la venv activa):

    python prueba_meta_webhook.py                # Test handshake (GET) sobre todas las ConfigMeta
    python prueba_meta_webhook.py --evento       # Además simula un evento POST con HMAC valido
    python prueba_meta_webhook.py --sesion 22    # Solo prueba la ConfigMeta de esa sesión
    python prueba_meta_webhook.py --sesion 39 --evento --from 593987654321 --texto "hola"
                                                 # Inyecta un entrante simulado a la sesión 39
                                                 # con remitente/texto reales (dispara el bot)

Casos que cubre:
  1. GET handshake con verify_token de cada ConfigMeta — confirma 200 y devuelve challenge.
  2. (Opcional) POST evento simulado de mensaje entrante — confirma que el webhook
     valida HMAC, guarda EventoMetaRecibido, y dispara process_incoming_message.

Si tu producción está detrás de Cloudflare/WAF y no podés alcanzar Django desde
la red pública, podés pasar --base http://127.0.0.1:8003 para probar local.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time

import django
import requests

# ── Bootstrap Django ────────────────────────────────────────────────────────
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
django.setup()

from django.conf import settings  # noqa: E402
from whatsapp.models import ConfigMeta, EventoMetaRecibido  # noqa: E402
from whatsapp.common_meta import get_meta_app_secret  # noqa: E402


def base_url(override: str | None) -> str:
    if override:
        return override.rstrip('/')
    return (getattr(settings, 'URL_GENERAL', '') or 'http://127.0.0.1:8000').rstrip('/')


def listar_configs(sesion_id: int | None) -> list[ConfigMeta]:
    qs = ConfigMeta.objects.all()
    if sesion_id:
        qs = qs.filter(sesion_id=sesion_id)
    return list(qs)


def probar_handshake(base: str, config: ConfigMeta) -> bool:
    challenge = f"prueba-{int(time.time())}"
    url = f"{base}/whatsapp/meta_webhook/"
    params = {
        'hub.mode':         'subscribe',
        'hub.verify_token': config.webhook_verify_token,
        'hub.challenge':    challenge,
    }
    print(f"\n  GET → {url}")
    print(f"        verify_token = {config.webhook_verify_token[:14]}…")
    try:
        r = requests.get(url, params=params, timeout=10)
    except Exception as ex:
        print(f"  ❌ Error de red: {ex}")
        return False

    print(f"        HTTP {r.status_code} | body={r.text[:120]!r}")
    if r.status_code == 200 and r.text.strip() == challenge:
        print("  ✅ Handshake OK — Meta podría verificar este webhook.")
        return True
    if r.status_code == 403:
        print("  ❌ 403 Forbidden — el verify_token de BD no coincide con el que aceptó Django.")
        print("     Probable: Django apunta a otra BD o hay caché en algún proxy.")
        return False
    if r.status_code == 404:
        print("  ❌ 404 — la URL del webhook no está enrutada. Verificá whatsapp/urls.py.")
        return False
    print("  ⚠️  Respuesta inesperada (revisar manualmente).")
    return False


def construir_evento_simulado(config: ConfigMeta, from_num: str = '593999999999',
                              texto: str = '[PRUEBA] hola desde prueba_meta_webhook.py') -> dict:
    """Payload Meta-shape de un mensaje entrante simulado.

    from_num y texto se pueden personalizar (--from / --texto) para reproducir
    un mensaje real y disparar el bot/flujo de la sesion."""
    ts = str(int(time.time()))
    return {
        'object': 'whatsapp_business_account',
        'entry': [{
            'id': config.waba_id,
            'changes': [{
                'field': 'messages',
                'value': {
                    'messaging_product': 'whatsapp',
                    'metadata': {
                        'display_phone_number': config.display_phone_number or '',
                        'phone_number_id':      config.phone_number_id,
                    },
                    'contacts': [{
                        'profile': {'name': 'Probador Webhook'},
                        'wa_id':   from_num,
                    }],
                    'messages': [{
                        'from':      from_num,
                        'id':        f'wamid.PRUEBA_{ts}',
                        'timestamp': ts,
                        'type':      'text',
                        'text':      {'body': texto},
                    }],
                },
            }],
        }],
    }


def probar_post_evento(base: str, config: ConfigMeta, from_num: str, texto: str) -> bool:
    app_secret = get_meta_app_secret()
    if not app_secret:
        print("  ⚠️  Sin app_secret cargado — Django acepta sin firmar (modo permisivo).")

    payload = construir_evento_simulado(config, from_num=from_num, texto=texto)
    raw_body = json.dumps(payload, separators=(',', ':')).encode('utf-8')

    headers = {'Content-Type': 'application/json'}
    if app_secret:
        sig = 'sha256=' + hmac.new(
            app_secret.encode('utf-8'), raw_body, hashlib.sha256,
        ).hexdigest()
        headers['X-Hub-Signature-256'] = sig

    url = f"{base}/whatsapp/meta_webhook/"
    print(f"\n  POST → {url}")
    print(f"         payload preview: {raw_body[:120]!r}…")
    print(f"         X-Hub-Signature-256: {headers.get('X-Hub-Signature-256', '(sin firma)')[:30]}…")

    eventos_antes = EventoMetaRecibido.objects.count()
    try:
        r = requests.post(url, data=raw_body, headers=headers, timeout=15)
    except Exception as ex:
        print(f"  ❌ Error de red: {ex}")
        return False

    eventos_despues = EventoMetaRecibido.objects.count()
    delta = eventos_despues - eventos_antes
    print(f"         HTTP {r.status_code} | body={r.text[:200]}")
    print(f"         EventoMetaRecibido +{delta} (de {eventos_antes} a {eventos_despues})")

    if r.status_code != 200:
        print("  ❌ Backend rechazó el POST.")
        return False
    if delta < 1:
        print("  ⚠️  HTTP 200 pero no se creó registro — algo raro (¿BD distinta?).")
        return False

    ult = EventoMetaRecibido.objects.order_by('-recibido_en').first()
    print(f"  ✅ Evento registrado id={ult.id} firma_valida={ult.firma_valida} procesado={ult.procesado}")
    if not ult.firma_valida and app_secret:
        print(f"     ❌ Firma HMAC inválida — chequeá que app_secret de BD = el de la Meta App.")
    return True


def main():
    p = argparse.ArgumentParser(description='Probador del webhook Meta del CRM.')
    p.add_argument('--base',   help='URL base (default: settings.URL_GENERAL)')
    p.add_argument('--sesion', type=int, help='Probar solo esta sesion_id')
    p.add_argument('--evento', action='store_true', help='Simular POST de mensaje entrante')
    p.add_argument('--from', dest='from_num', default='593999999999',
                   help='Numero remitente (wa_id) del mensaje simulado')
    p.add_argument('--texto', default='[PRUEBA] hola desde prueba_meta_webhook.py',
                   help='Texto del mensaje entrante simulado')
    args = p.parse_args()

    base = base_url(args.base)
    print(f"== Probador Meta Webhook ==")
    print(f"   Base URL: {base}")
    print(f"   Endpoint: {base}/whatsapp/meta_webhook/")

    configs = listar_configs(args.sesion)
    if not configs:
        print("\n❌ No hay ConfigMeta cargadas (o el --sesion no existe).")
        sys.exit(1)

    print(f"\nConfigMeta encontradas: {len(configs)}")
    for c in configs:
        print(f"  [{c.sesion_id}] {c.sesion.nombre} · WABA {c.waba_id} · token {c.webhook_verify_token[:10]}…")

    ok_handshake = 0
    ok_post = 0
    for c in configs:
        print(f"\n────── Sesión {c.sesion_id}: {c.sesion.nombre} ──────")
        if probar_handshake(base, c):
            ok_handshake += 1
            if args.evento:
                if probar_post_evento(base, c, args.from_num, args.texto):
                    ok_post += 1

    print("\n=== Resumen ===")
    print(f"  Handshakes OK: {ok_handshake}/{len(configs)}")
    if args.evento:
        print(f"  POST eventos OK: {ok_post}/{len(configs)}")
    if ok_handshake == len(configs):
        print("✅ Webhook accesible. Si Meta no manda eventos, faltan tildar campos en developers.facebook.com.")
    else:
        print("❌ Hay fallas — revisar el detalle de cada sesión arriba.")


if __name__ == '__main__':
    main()
