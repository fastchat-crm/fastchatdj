"""Heartbeat Node -> Django.

Permite detectar cuando el servicio Node esta vivo pero deja de comunicarse con
Django (problema mas insidioso que un crash, porque WhatsApp sigue recibiendo
mensajes que se pierden silenciosamente).

Node debe POSTear cada 30-60s con el estado de cada sesion. Si Django no recibe
ping en >180s, la sesion se considera "muda" y el helper node_esta_vivo()
retorna False para que el resto del sistema pueda decidir que hacer.

URL: POST /whatsapp/heartbeat/
Auth: header X-API-Key: <NODE_SECRET_KEY>

Payload:
    {
      "ts": 1729...,                       # timestamp epoch seg, opcional
      "sessions": [
        {"sessionId": "uuid-1", "estado": "conectado", "queueDepth": 0},
        {"sessionId": "uuid-2", "estado": "conectado", "queueDepth": 5}
      ]
    }

    O un solo ping global sin sesiones (solo confirma que el proceso Node vive):
    { "ts": 1729..., "host": "node-prod-1" }

Respuesta: {"ok": true, "registered": <n>}
"""
import json
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

HEARTBEAT_TTL_SEG = 180  # 3x el intervalo esperado (60s)
HEARTBEAT_GLOBAL_KEY = 'node_heartbeat_global'


def _key_sesion(session_id: str) -> str:
    return f'node_heartbeat_session_{session_id}'


def node_esta_vivo(session_id: str = None) -> bool:
    """True si recibimos un heartbeat reciente. Si se pasa session_id, chequea
    esa sesion; si no, chequea el ping global del proceso Node."""
    try:
        if session_id:
            return bool(cache.get(_key_sesion(session_id)))
        return bool(cache.get(HEARTBEAT_GLOBAL_KEY))
    except Exception:
        return True  # ante fallo del cache, no bloqueamos


def estado_heartbeat_sesion(session_id: str) -> dict | None:
    """Devuelve el ultimo payload registrado para la sesion, o None."""
    try:
        return cache.get(_key_sesion(session_id))
    except Exception:
        return None


@csrf_exempt
@require_POST
def heartbeat_receiver(request):
    api_key = request.headers.get('X-API-Key') or request.META.get('HTTP_X_API_KEY')
    if not api_key or api_key != settings.NODE_SECRET_KEY:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({'error': 'expected_object'}, status=400)

    now = int(time.time())
    ts = payload.get('ts') or now

    cache.set(
        HEARTBEAT_GLOBAL_KEY,
        {'ts': ts, 'received_at': now, 'host': payload.get('host')},
        timeout=HEARTBEAT_TTL_SEG,
    )

    sessions = payload.get('sessions') or []
    if not isinstance(sessions, list):
        return JsonResponse({'error': 'sessions_must_be_array'}, status=400)

    registradas = 0
    for s in sessions:
        if not isinstance(s, dict):
            continue
        sid = s.get('sessionId')
        if not sid:
            continue
        try:
            cache.set(
                _key_sesion(sid),
                {
                    'ts': ts,
                    'received_at': now,
                    'estado': s.get('estado'),
                    'queue_depth': s.get('queueDepth'),
                    'last_event_ts': s.get('lastEventTs'),
                },
                timeout=HEARTBEAT_TTL_SEG,
            )
            registradas += 1
        except Exception:
            logger.exception('Error guardando heartbeat sesion %s', sid)

    return JsonResponse({'ok': True, 'registered': registradas})
