"""Endpoint batch para drenar la outbox del servicio Node.js.

Cuando Node persiste eventos en su outbox (porque Django estuvo caído o lento),
los reenvía agrupados por este endpoint. La idempotencia ya existente en
view_webhook_handler.process_incoming_message (chequeo por mensaje_id_externo)
cubre los duplicados, así que Node puede reintentar sin riesgo.

URL: POST /whatsapp/webhook_handler/batch/
Auth: header X-API-Key: <NODE_SECRET_KEY>

Payload:
    {
      "events": [
        {"eventId": "<id outbox local de Node>", "type": "message", "data": {...}},
        {"eventId": "...",                       "type": "message_sent", "data": {...}},
        ...
      ]
    }

    Tambien acepta un array desnudo: [ {...}, {...} ]

Respuesta:
    {
      "ok": true,
      "results": [
        {"eventId": "...", "ok": true,  "status": 200},
        {"eventId": "...", "ok": false, "status": 500, "error": "..."}
      ]
    }

Node debe borrar de su outbox solo los items con ok=true.
"""
import json
import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .view_webhook_handler import webhook_handler

logger = logging.getLogger(__name__)

MAX_EVENTS_POR_BATCH = 200


@csrf_exempt
@require_POST
def webhook_handler_batch(request):
    api_key = request.headers.get('X-API-Key') or request.META.get('HTTP_X_API_KEY')
    if not api_key or api_key != settings.NODE_SECRET_KEY:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    if isinstance(payload, list):
        events = payload
    elif isinstance(payload, dict):
        events = payload.get('events') or []
    else:
        return JsonResponse({'error': 'expected_object_or_array'}, status=400)

    if not isinstance(events, list):
        return JsonResponse({'error': 'events_must_be_array'}, status=400)

    if len(events) > MAX_EVENTS_POR_BATCH:
        return JsonResponse(
            {'error': 'batch_too_large', 'max': MAX_EVENTS_POR_BATCH, 'received': len(events)},
            status=413,
        )

    results = []
    for idx, event in enumerate(events):
        event_id = event.get('eventId') if isinstance(event, dict) else None
        try:
            sub_req = HttpRequest()
            sub_req.method = 'POST'
            sub_req.META = dict(request.META)
            sub_req._body = json.dumps(event).encode('utf-8')

            response = webhook_handler(sub_req)
            status = getattr(response, 'status_code', 500)
            ok = 200 <= status < 300
            entry = {'idx': idx, 'eventId': event_id, 'ok': ok, 'status': status}
            if not ok:
                try:
                    entry['error'] = json.loads(response.content.decode('utf-8')).get('message') or response.content.decode('utf-8')[:200]
                except Exception:
                    entry['error'] = response.content.decode('utf-8', errors='replace')[:200]
            results.append(entry)
        except Exception as e:
            logger.exception('Batch: error procesando event idx=%s eventId=%s: %s', idx, event_id, e)
            results.append({'idx': idx, 'eventId': event_id, 'ok': False, 'status': 500, 'error': str(e)[:300]})

    procesados_ok = sum(1 for r in results if r['ok'])
    logger.info(
        'Batch webhook recibido: %s evento(s), %s ok / %s fail',
        len(events), procesados_ok, len(results) - procesados_ok,
    )

    return JsonResponse({'ok': True, 'results': results})
