"""Endpoint para que el servicio Node.js registre trazas del lado del servicio
WhatsApp en la tabla TrazaMensajeIA. Permite ver en un solo timeline los eventos
de ambos lados (Django + Node) para diagnosticar fallos end-to-end.

URL: POST /whatsapp/trace/
Auth: header X-API-Key: <NODE_SECRET_KEY>
"""
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp
from .trazas import registrar as _traza

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def trace_receiver(request):
    """Recibe una o varias trazas desde Node y las persiste en TrazaMensajeIA.

    Payload aceptado (JSON):
        Una sola traza:
            {
              "sessionId": "uuid-de-sesion",        # obligatorio
              "etapa": "node_envio_intento",         # obligatorio (ver ETAPAS_TRAZA)
              "nivel": "info|success|warning|error", # opcional, default: info
              "numero": "593987654321",              # opcional
              "conversacionId": 123,                 # opcional (ID Django)
              "mensajeIdExterno": "wamid.XXX",       # opcional (busca el Mensaje por id externo)
              "detalle": "texto o objeto JSON",      # opcional
              "latenciaMs": 1234                     # opcional
            }

        O un lote:
            { "trazas": [ {...}, {...}, ... ] }
    """
    # --- Autenticacion ---
    api_key = request.headers.get('X-API-Key') or request.META.get('HTTP_X_API_KEY')
    if not api_key or api_key != settings.NODE_SECRET_KEY:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    trazas = payload.get('trazas') if isinstance(payload, dict) and 'trazas' in payload else [payload]
    if not isinstance(trazas, list):
        return JsonResponse({'error': 'expected_list_or_single'}, status=400)

    registradas, rechazadas = 0, []
    for idx, item in enumerate(trazas):
        try:
            session_id = item.get('sessionId')
            etapa = item.get('etapa')
            if not session_id or not etapa:
                rechazadas.append({'idx': idx, 'error': 'sessionId_or_etapa_missing'})
                continue

            sesion = SesionWhatsApp.objects.filter(session_id=session_id).first()
            conversacion = None
            mensaje = None

            conv_id = item.get('conversacionId')
            if conv_id:
                conversacion = ConversacionWhatsApp.objects.filter(id=conv_id).first()

            msg_id_ext = item.get('mensajeIdExterno')
            if msg_id_ext:
                mensaje = MensajeWhatsApp.objects.filter(mensaje_id_externo=msg_id_ext).first()
                if mensaje and not conversacion:
                    conversacion = mensaje.conversacion

            _traza(
                etapa=etapa,
                sesion=sesion,
                conversacion=conversacion,
                mensaje=mensaje,
                numero=item.get('numero'),
                nivel=item.get('nivel') or 'info',
                detalle=item.get('detalle'),
                latencia_ms=item.get('latenciaMs'),
            )
            registradas += 1
        except Exception as e:
            logger.exception('Error procesando traza desde Node: %s', e)
            rechazadas.append({'idx': idx, 'error': str(e)[:300]})

    return JsonResponse({
        'ok': True,
        'registradas': registradas,
        'rechazadas': rechazadas,
    })
