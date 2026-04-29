"""Prueba rápida del webhook de envío a conversación contra producción.

Por defecto corre los DOS ejemplos: primero solo texto, después texto+archivo.
SIN auth — el endpoint es público; lo único que valida es que la conversación
no esté finalizada.

Ejecutar:
    python prueba_webhook.py              # ambos ejemplos (texto + archivo)
    python prueba_webhook.py --solo-texto
    python prueba_webhook.py --solo-archivo
    python prueba_webhook.py --archivo otro.pdf
    python prueba_webhook.py --info

Editar las variables de abajo:
    ID_CHAT   → id de la ConversacionWhatsApp objetivo
    BASE_URL  → dominio de producción (sin barra final)
    TEXTO     → cuerpo del mensaje
    ARCHIVO   → ruta por defecto del adjunto
"""
import argparse
import os
import sys

import requests


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
ID_CHAT = 1103
BASE_URL = "https://mensajeria.broktech.com.ec"
TEXTO = "✅ Prueba desde prueba_webhook.py — el webhook funciona."
CAPTION = "📎 Índice de URLs y módulos del sistema"
ARCHIVO = "docs/pdf/00_indice_urls_modulos.pdf"

TIMEOUT_TEXTO = 15
TIMEOUT_ARCHIVO = 30


def url_envio(id_chat: int) -> str:
    return f"{BASE_URL}/whatsapp/api/v1/conversaciones/{id_chat}/enviar/"


def _imprimir_respuesta(r: requests.Response) -> None:
    print(f"← {r.status_code}")
    try:
        print(r.json())
    except Exception:
        print(r.text)


def ejemplo_texto():
    url = url_envio(ID_CHAT)
    print("\n── Ejemplo 1: SOLO TEXTO (application/json) ──────────────────────")
    print(f"→ POST {url}")
    print(f"   body: {{'texto': {TEXTO!r}}}")
    r = requests.post(url, json={"texto": TEXTO}, timeout=TIMEOUT_TEXTO)
    _imprimir_respuesta(r)
    r.raise_for_status()


def ejemplo_archivo(ruta_archivo: str = ARCHIVO):
    if not os.path.isfile(ruta_archivo):
        print(f"❌ Archivo no encontrado: {ruta_archivo}")
        sys.exit(1)
    url = url_envio(ID_CHAT)
    nombre = os.path.basename(ruta_archivo)
    print("\n── Ejemplo 2: TEXTO + ARCHIVO (multipart/form-data) ──────────────")
    print(f"→ POST {url}")
    print(f"   texto:   {TEXTO!r}")
    print(f"   caption: {CAPTION!r}")
    print(f"   archivo: {ruta_archivo} ({os.path.getsize(ruta_archivo)} bytes)")
    with open(ruta_archivo, "rb") as f:
        r = requests.post(
            url,
            data={"texto": TEXTO, "caption": CAPTION},
            files={"archivo": (nombre, f, "application/pdf")},
            timeout=TIMEOUT_ARCHIVO,
        )
    _imprimir_respuesta(r)
    r.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description="Probar webhook de envío a conversación.")
    parser.add_argument("--solo-texto", action="store_true", help="Correr solo el ejemplo de texto.")
    parser.add_argument("--solo-archivo", action="store_true", help="Correr solo el ejemplo de archivo.")
    parser.add_argument("--archivo", help="Override de la ruta del archivo a enviar.")
    parser.add_argument("--info", action="store_true", help="Mostrar config y URL armada y salir.")
    args = parser.parse_args()

    if args.info:
        print(f"BASE_URL : {BASE_URL}")
        print(f"ID_CHAT  : {ID_CHAT}")
        print(f"URL      : {url_envio(ID_CHAT)}")
        print(f"ARCHIVO  : {ARCHIVO}")
        return

    archivo = args.archivo or ARCHIVO

    if args.solo_texto:
        ejemplo_texto()
    elif args.solo_archivo:
        ejemplo_archivo(archivo)
    else:
        ejemplo_texto()
        ejemplo_archivo(archivo)


if __name__ == "__main__":
    main()
