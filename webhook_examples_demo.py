"""
webhook_examples_demo.py
========================
Payloads de ejemplo + invocaciones con `requests` para cada endpoint webhook
de WhatsApp de fastchat. Standalone — no necesita Django.

Uso:
    pip install requests
    python webhook_examples_demo.py            # corre todos
    python webhook_examples_demo.py qr_code    # corre solo uno

Configurar BASE_URL, NODE_SECRET_KEY, META_VERIFY_TOKEN, SESSION_ID, PHONE_NUMBER_ID
antes de ejecutar contra un entorno real.

Endpoints cubiertos:
    POST /whatsapp/webhook_handler/            (Baileys — todos los event_type)
    POST /whatsapp/webhook_handler/batch/      (Baileys batch)
    GET  /whatsapp/meta_webhook/               (Meta handshake)
    POST /whatsapp/meta_webhook/               (Meta evento)
    POST /whatsapp/instagram_webhook/          (Instagram DM)
    POST /whatsapp/messenger_webhook/          (Messenger)
    POST /whatsapp/conversaciones/             (saliente: action=send)
"""
import hashlib
import hmac
import json
import sys
import time

import requests


BASE_URL = "http://localhost:8000"
NODE_SECRET_KEY = "CHANGE_ME_node_secret"
META_VERIFY_TOKEN = "CHANGE_ME_meta_verify"
META_APP_SECRET = "CHANGE_ME_app_secret"
SESSION_ID = "uuid-de-tu-sesion-baileys"
PHONE_NUMBER_ID = "123456789012345"
WABA_ID = "987654321098765"
CONTACTO_NUMERO = "5491133333333"
SESION_NUMERO = "5491122222222"


def _post_baileys(event_type, data, batch=False):
    url = f"{BASE_URL}/whatsapp/webhook_handler/{'batch/' if batch else ''}"
    payload = {"type": event_type, "data": {"sessionId": SESSION_ID, **data}}
    headers = {"Content-Type": "application/json", "X-API-Key": NODE_SECRET_KEY}
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    print(f"[{event_type}] {r.status_code} {r.text[:200]}")
    return r


def _post_meta(payload, app_secret=META_APP_SECRET):
    url = f"{BASE_URL}/whatsapp/meta_webhook/"
    body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-Hub-Signature-256": sig}
    r = requests.post(url, data=body, headers=headers, timeout=15)
    print(f"[META POST] {r.status_code} {r.text[:200]}")
    return r


def qr_code():
    return _post_baileys("qr_code", {"qrCode": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."})


def ready():
    return _post_baileys("ready", {
        "user": {"id": f"{SESION_NUMERO}:1@s.whatsapp.net", "pushName": "Mi Negocio"},
        "userImage": "https://pps.whatsapp.net/v/t61/foo.jpg",
    })


def authenticated():
    return _post_baileys("authenticated", {})


def contacts_list():
    return _post_baileys("contacts_list", {
        "contacts_list": [
            {"id": f"{CONTACTO_NUMERO}@s.whatsapp.net", "notify": "Cliente Uno"},
            {"id": "5491144444444@s.whatsapp.net", "notify": "Cliente Dos"},
        ],
    })


def auth_failure():
    return _post_baileys("auth_failure", {
        "error": "Connection Closed",
        "reason": "440",
    })


def disconnected():
    return _post_baileys("disconnected", {
        "reason": "logged_out",
        "error": "Stream Errored (conflict)",
    })


def rate_limited():
    return _post_baileys("rate_limited", {
        "count": 50,
        "max": 50,
        "windowMs": 60000,
        "windowStart": int(time.time() * 1000),
        "retryAfterMs": 60000,
    })


def message_text():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "pushName": "Cliente Uno",
        "userImage": None,
        "message": {"conversation": "Hola, quiero saber precios"},
    })


def message_extended_text():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "pushName": "Cliente Uno",
        "message": {"extendedTextMessage": {"text": "Mensaje con link https://x.com"}},
    })


def message_image():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "pushName": "Cliente Uno",
        "mediaType": "imageMessage",
        "mediaData": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        "fileName": "foto.png",
        "caption": "mira esto",
        "message": {"imageMessage": {"caption": "mira esto", "mimetype": "image/png"}},
    })


def message_audio():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "pushName": "Cliente Uno",
        "mediaType": "audioMessage",
        "mediaData": "T2dnUwACAAAAAAAAAAB...",
        "fileName": "audio.ogg",
        "message": {"audioMessage": {"mimetype": "audio/ogg; codecs=opus", "ptt": True}},
    })


def message_video():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "pushName": "Cliente Uno",
        "mediaType": "videoMessage",
        "mediaData": "AAAAIGZ0eXBpc29tAAACAGlzb...",
        "fileName": "video.mp4",
        "caption": "demo",
        "message": {"videoMessage": {"caption": "demo", "mimetype": "video/mp4"}},
    })


def message_document():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "pushName": "Cliente Uno",
        "mediaType": "documentMessage",
        "mediaData": "JVBERi0xLjQKJ...",
        "fileName": "factura.pdf",
        "message": {"documentMessage": {"fileName": "factura.pdf", "mimetype": "application/pdf"}},
    })


def message_sticker():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "pushName": "Cliente Uno",
        "mediaType": "stickerMessage",
        "mediaData": "UklGRiQAAA...",
        "fileName": "sticker_001",
        "message": {"stickerMessage": {"mimetype": "image/webp"}},
    })


def message_edited():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "message": {
            "protocolMessage": {
                "type": "MESSAGE_EDIT",
                "key": {"id": "WAID_ORIGINAL_123"},
                "editedMessage": {"conversation": "texto corregido"},
            }
        },
    })


def message_deleted():
    return _post_baileys("message", {
        "id": f"WAID_{int(time.time())}",
        "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "fromMe": False,
        "timestamp": int(time.time()),
        "message": {
            "protocolMessage": {
                "type": "REVOKE",
                "key": {"id": "WAID_ORIGINAL_123"},
            }
        },
    })


def message_sent_outgoing():
    return _post_baileys("message_sent", {
        "messageId": f"WAID_OUT_{int(time.time())}",
        "to": f"{CONTACTO_NUMERO}@s.whatsapp.net",
        "conversacion_id": 0,
        "message": {"conversation": "Respuesta del agente"},
    })


def profile_update():
    return _post_baileys("profile_update", {
        "presence": {"id": f"{CONTACTO_NUMERO}@s.whatsapp.net", "lastKnownPresence": "available"},
    })


def baileys_batch():
    url = f"{BASE_URL}/whatsapp/webhook_handler/batch/"
    payload = {
        "events": [
            {"type": "message", "data": {
                "sessionId": SESSION_ID,
                "id": f"BATCH_{i}_{int(time.time())}",
                "from": f"{CONTACTO_NUMERO}@s.whatsapp.net",
                "fromMe": False,
                "timestamp": int(time.time()),
                "message": {"conversation": f"Mensaje batch {i}"},
            }}
            for i in range(3)
        ]
    }
    r = requests.post(url, json=payload,
                      headers={"X-API-Key": NODE_SECRET_KEY},
                      timeout=15)
    print(f"[batch] {r.status_code} {r.text[:200]}")
    return r


def meta_handshake():
    url = f"{BASE_URL}/whatsapp/meta_webhook/"
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": META_VERIFY_TOKEN,
        "hub.challenge": "1234567890",
    }
    r = requests.get(url, params=params, timeout=15)
    print(f"[meta GET] {r.status_code} body={r.text[:200]}")
    return r


def meta_message_text():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": SESION_NUMERO,
                                 "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": "Cliente Meta"},
                                  "wa_id": CONTACTO_NUMERO}],
                    "messages": [{
                        "from": CONTACTO_NUMERO,
                        "id": f"wamid.HBgL{int(time.time())}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": "Hola desde Meta Cloud"},
                    }],
                },
            }],
        }],
    }
    return _post_meta(payload)


def meta_message_image():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": SESION_NUMERO,
                                 "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": "Cliente Meta"},
                                  "wa_id": CONTACTO_NUMERO}],
                    "messages": [{
                        "from": CONTACTO_NUMERO,
                        "id": f"wamid.HBgL{int(time.time())}",
                        "timestamp": str(int(time.time())),
                        "type": "image",
                        "image": {
                            "id": "META_MEDIA_ID_xyz",
                            "mime_type": "image/jpeg",
                            "sha256": "abc",
                            "caption": "foto factura",
                        },
                    }],
                },
            }],
        }],
    }
    return _post_meta(payload)


def meta_message_status():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": SESION_NUMERO,
                                 "phone_number_id": PHONE_NUMBER_ID},
                    "statuses": [{
                        "id": "wamid.HBgL_outbound_123",
                        "status": "delivered",
                        "timestamp": str(int(time.time())),
                        "recipient_id": CONTACTO_NUMERO,
                    }],
                },
            }],
        }],
    }
    return _post_meta(payload)


def meta_ctwa_referral():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": SESION_NUMERO,
                                 "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": "Lead Ad"},
                                  "wa_id": CONTACTO_NUMERO}],
                    "messages": [{
                        "from": CONTACTO_NUMERO,
                        "id": f"wamid.HBgL{int(time.time())}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": "Vine del anuncio"},
                        "referral": {
                            "source_url": "https://fb.me/...",
                            "source_type": "ad",
                            "source_id": "AD_ID_123",
                            "headline": "Promo 2x1",
                            "ctwa_clid": "ARZ...",
                        },
                    }],
                },
            }],
        }],
    }
    return _post_meta(payload)


def instagram_webhook():
    url = f"{BASE_URL}/whatsapp/instagram_webhook/"
    payload = {
        "object": "instagram",
        "entry": [{
            "id": "IG_PAGE_ID",
            "time": int(time.time()),
            "messaging": [{
                "sender": {"id": "IG_USER_ID"},
                "recipient": {"id": "IG_PAGE_ID"},
                "timestamp": int(time.time() * 1000),
                "message": {"mid": "IG_MID_123", "text": "Hola por IG DM"},
            }],
        }],
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = requests.post(url, data=body,
                      headers={"Content-Type": "application/json",
                               "X-Hub-Signature-256": sig},
                      timeout=15)
    print(f"[IG] {r.status_code} {r.text[:200]}")
    return r


def messenger_webhook():
    url = f"{BASE_URL}/whatsapp/messenger_webhook/"
    payload = {
        "object": "page",
        "entry": [{
            "id": "FB_PAGE_ID",
            "time": int(time.time()),
            "messaging": [{
                "sender": {"id": "FB_USER_ID"},
                "recipient": {"id": "FB_PAGE_ID"},
                "timestamp": int(time.time() * 1000),
                "message": {"mid": "FB_MID_123", "text": "Hola por Messenger"},
            }],
        }],
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = requests.post(url, data=body,
                      headers={"Content-Type": "application/json",
                               "X-Hub-Signature-256": sig},
                      timeout=15)
    print(f"[Messenger] {r.status_code} {r.text[:200]}")
    return r


def saliente_send_text(session_cookie):
    url = f"{BASE_URL}/whatsapp/conversaciones/"
    data = {
        "action": "send",
        "pk": "1",
        "mensaje": "Hola, soy el agente",
    }
    r = requests.post(url, data=data,
                      cookies={"sessionid": session_cookie},
                      timeout=15)
    print(f"[OUT send] {r.status_code} {r.text[:200]}")
    return r


def saliente_enviar_plantilla_meta(session_cookie):
    url = f"{BASE_URL}/whatsapp/conversaciones-finalizadas/"
    data = {
        "action": "enviar_plantilla_meta",
        "pk": "1",
        "plantilla_id": "10",
        "params_cuerpo_json": json.dumps({"1": "Juan", "2": "10:00"}),
        "params_header_json": json.dumps({}),
    }
    r = requests.post(url, data=data,
                      cookies={"sessionid": session_cookie},
                      timeout=15)
    print(f"[OUT plantilla] {r.status_code} {r.text[:200]}")
    return r


REGISTRY = {
    "qr_code": qr_code,
    "ready": ready,
    "authenticated": authenticated,
    "contacts_list": contacts_list,
    "auth_failure": auth_failure,
    "disconnected": disconnected,
    "rate_limited": rate_limited,
    "message_text": message_text,
    "message_extended_text": message_extended_text,
    "message_image": message_image,
    "message_audio": message_audio,
    "message_video": message_video,
    "message_document": message_document,
    "message_sticker": message_sticker,
    "message_edited": message_edited,
    "message_deleted": message_deleted,
    "message_sent_outgoing": message_sent_outgoing,
    "profile_update": profile_update,
    "baileys_batch": baileys_batch,
    "meta_handshake": meta_handshake,
    "meta_message_text": meta_message_text,
    "meta_message_image": meta_message_image,
    "meta_message_status": meta_message_status,
    "meta_ctwa_referral": meta_ctwa_referral,
    "instagram_webhook": instagram_webhook,
    "messenger_webhook": messenger_webhook,
}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in REGISTRY:
            print(f"Desconocido: {name}\nDisponibles: {', '.join(REGISTRY)}")
            sys.exit(1)
        REGISTRY[name]()
    else:
        for name, fn in REGISTRY.items():
            print(f"\n=== {name} ===")
            try:
                fn()
            except Exception as e:
                print(f"ERROR {name}: {e}")
