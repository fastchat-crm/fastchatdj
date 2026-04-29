"""Endpoint stub para tools de captura del agente IA.

Cuando una `HerramientaAgente` generada por `migrar_depto_a_tools` se
invoca (ej. capturar_cedula), el LLM hace POST acá con el dato. El
endpoint solo hace echo: confirma que recibió el dato y se lo devuelve
al LLM para que lo use en el contexto de la conversación.

No persiste nada — el contexto vive en la memoria del agente
(`DjangoChatMessageHistory`).
"""
from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@csrf_exempt
@require_POST
def captura_local(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        payload = {}
    return JsonResponse({
        'ok': True,
        'registrado': payload,
        'message': 'Dato capturado. Continuá la conversación con este valor en mente.',
    })
