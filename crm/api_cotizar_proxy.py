"""Proxy interno para el flujo de cotización ARIA.

El motor del flujo del chatbot tradicional invoca un único nodo HTTP que pega
acá. Este endpoint solo orquesta el webhook externo de ARIA — el envío de
correo al asesor lo dispara el motor genéricamente cuando el nodo tiene
`config.envia_correo = true` (ver `crm/helpers_correo_flujo.py`).

Devuelve `{success: bool, message: str}` para que el motor del flujo
ramifique a `siguiente_ok` (success=True) o `siguiente_error` (success=False).

Sin auth — es un endpoint interno, lo único que valida es que la conversación
exista y no esté finalizada.
"""
from __future__ import annotations

import json
import logging

import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from whatsapp.models import ConversacionWhatsApp


logger = logging.getLogger(__name__)


WEBHOOK_ARIA_URL = 'https://fguerrero.mgaseguros.ec/webhook/cotizar/'
WEBHOOK_TIMEOUT_SEG = 30


@csrf_exempt
@require_POST
def cotizar_proxy(request, conv_id: int):
    """Orquesta el webhook externo + email a asesores. Llamado por el motor
    del flujo del chatbot tradicional (nodo HTTP único).

    Body JSON esperado (lo arma el flujo desde sus variables):
        {
          "cliente": {cedula, email, telefono, edad, civil_status, genero},
          "vehiculo": {placa, tipo_vehiculo, color, provincia, valor_comercial},
          "aseguradoras": {"all": true}
        }
    """
    try:
        conv = ConversacionWhatsApp.objects.select_related('contacto', 'contacto__sesion').get(pk=conv_id)
    except ConversacionWhatsApp.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Conversación no existe.'}, status=404)
    if conv.conversacion_finalizada:
        return JsonResponse({
            'success': False, 'message': 'La conversación ya está finalizada.',
        }, status=409)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False, 'message': 'JSON inválido.',
        }, status=400)

    # Inyectar id_conversacion al body que se manda al webhook ARIA.
    payload_aria = dict(payload)
    payload_aria['id_conversacion'] = conv.id

    try:
        r = requests.post(
            WEBHOOK_ARIA_URL,
            json=payload_aria,
            timeout=WEBHOOK_TIMEOUT_SEG,
            headers={'Content-Type': 'application/json',
                     'Accept': 'application/json'},
        )
    except requests.RequestException as ex:
        logger.exception('Webhook ARIA conv#%s falló: %s', conv.id, ex)
        return JsonResponse({
            'success': False,
            'message': 'No pudimos contactar al servicio de cotización.',
            'detalle': str(ex)[:300],
        }, status=502)

    try:
        resp_json = r.json()
    except ValueError:
        resp_json = {'_raw': r.text[:1000]}

    # 200/202 con `ok: true` → éxito. Cualquier otra cosa → error.
    es_exito = (200 <= r.status_code < 300) and bool(resp_json.get('ok'))
    if not es_exito:
        logger.warning(
            'Webhook ARIA conv#%s rechazó: status=%s body=%s',
            conv.id, r.status_code, resp_json,
        )
        return JsonResponse({
            'success': False,
            'message': resp_json.get('error') or f'El servicio de cotización respondió {r.status_code}.',
            'webhook_status': r.status_code,
            'webhook_body': resp_json,
        }, status=502)

    # Éxito. El correo a los asesores lo dispara el motor del flujo si el
    # nodo tiene `config.envia_correo=true` (ver helpers_correo_flujo.py).
    return JsonResponse({
        'success': True,
        'message': resp_json.get('mensaje') or 'Cotización en proceso.',
        'status': resp_json.get('status') or 'encolado',
    })
