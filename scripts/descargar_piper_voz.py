"""Descarga voz Piper para TTS espanol.

Uso:
    python scripts/descargar_piper_voz.py
    python scripts/descargar_piper_voz.py --voz es_ES-davefx-medium

Voces espanol disponibles (rhasspy/piper-voices):
    es_MX-ald-medium           (Mexico, recomendada)
    es_ES-davefx-medium        (Espana)
    es_ES-sharvard-medium      (Espana)
    es_ES-mls_9972-low         (Espana, liviana)
    es_ES-carlfm-x_low         (Espana, muy liviana)

Catalogo completo:
    https://huggingface.co/rhasspy/piper-voices/tree/main/es
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/es'

VOCES = {
    'es_MX-ald-medium':      f'{BASE}/es_MX/ald/medium/es_MX-ald-medium',
    'es_ES-davefx-medium':   f'{BASE}/es_ES/davefx/medium/es_ES-davefx-medium',
    'es_ES-sharvard-medium': f'{BASE}/es_ES/sharvard/medium/es_ES-sharvard-medium',
    'es_ES-mls_9972-low':    f'{BASE}/es_ES/mls_9972/low/es_ES-mls_9972-low',
    'es_ES-carlfm-x_low':    f'{BASE}/es_ES/carlfm/x_low/es_ES-carlfm-x_low',
}

BASE_DIR = Path(__file__).resolve().parent.parent
DEST_DIR = BASE_DIR / 'media' / 'piper'


def _descargar(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        size_mb = dest.stat().st_size / 1024 / 1024
        print(f'  ya existe: {dest.name} ({size_mb:.1f} MB) - saltando')
        return
    print(f'  descargando: {url}')
    print(f'  -> {dest}')
    with urllib.request.urlopen(url) as resp, open(dest, 'wb') as fp:
        total = int(resp.headers.get('Content-Length', 0))
        leido = 0
        chunk = 1024 * 64
        while True:
            data = resp.read(chunk)
            if not data:
                break
            fp.write(data)
            leido += len(data)
            if total:
                pct = leido * 100 / total
                mb = leido / 1024 / 1024
                print(f'\r  {pct:5.1f}%  {mb:6.1f} MB', end='', flush=True)
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--voz', default='es_MX-ald-medium', choices=list(VOCES.keys()))
    args = ap.parse_args()

    url_base = VOCES[args.voz]
    onnx_path = DEST_DIR / f'{args.voz}.onnx'
    json_path = DEST_DIR / f'{args.voz}.onnx.json'

    print(f'Voz: {args.voz}')
    print(f'Destino: {DEST_DIR}')
    try:
        _descargar(f'{url_base}.onnx', onnx_path)
        _descargar(f'{url_base}.onnx.json', json_path)
    except Exception as exc:  # noqa: BLE001
        print(f'\n[error] {exc}', file=sys.stderr)
        sys.exit(1)

    rel = onnx_path.relative_to(BASE_DIR).as_posix()
    print('\nListo. Configura en settings.py (o env):')
    print(f'    VOZ_PIPER_MODEL = "{rel}"')


if __name__ == '__main__':
    main()
