"""Despachador de webhooks salientes con backoff exponencial.

Uso:
    from whatsapp.webhooks_salientes import disparar_evento
    disparar_evento('conversacion.nueva', {'conversacion_id': 12, ...})

Cada `WebhookSaliente` activo y suscrito al evento recibe un POST. El body se
firma con HMAC-SHA256 (header `X-FC-Signature`) si el webhook define `secret`.
Cada intento queda en `EntregaWebhookSaliente`.

Backoff: ante fallo se incrementa `fallos_consecutivos` y se posterga
`proximo_intento` = ahora + BASE * 2^(fallos-1) (tope MAX_BACKOFF). Mientras
`proximo_intento` sea futuro, el webhook se saltea. Tras MAX_FALLOS fallos
seguidos el webhook se desactiva (`activo=False`) para no colgar el sistema.
Un envío exitoso resetea el contador y limpia el backoff.
"""
import hashlib
import hmac
import json
import logging
import time

import requests
from django.utils import timezone

logger = logging.getLogger('whatsapp')

TIMEOUT_SEG = 8
BASE_BACKOFF_SEG = 60
MAX_BACKOFF_SEG = 6 * 60 * 60
MAX_FALLOS = 8


def _firmar(secret: str, body: bytes) -> str:
    return 'sha256=' + hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()


def disparar_evento(evento: str, payload: dict) -> int:
    """Despacha `evento` a los webhooks suscritos. Devuelve cuántos se entregaron OK."""
    from .models import WebhookSaliente, EntregaWebhookSaliente

    ahora = timezone.now()
    webhooks = WebhookSaliente.objects.filter(status=True, activo=True)
    entregados = 0

    for wh in webhooks:
        if evento not in (wh.eventos or []):
            continue
        if wh.proximo_intento and wh.proximo_intento > ahora:
            continue

        body = json.dumps(
            {'evento': evento, 'data': payload, 'ts': ahora.isoformat()},
            ensure_ascii=False, default=str,
        ).encode('utf-8')

        headers = {'Content-Type': 'application/json'}
        if isinstance(wh.headers_extra, dict):
            headers.update({str(k): str(v) for k, v in wh.headers_extra.items()})
        if wh.secret:
            headers['X-FC-Signature'] = _firmar(wh.secret, body)

        status_code = None
        respuesta_txt = ''
        exitoso = False
        t0 = time.time()
        try:
            resp = requests.post(wh.url, data=body, headers=headers, timeout=TIMEOUT_SEG)
            status_code = resp.status_code
            respuesta_txt = (resp.text or '')[:1000]
            exitoso = 200 <= resp.status_code < 300
        except requests.RequestException as ex:
            respuesta_txt = str(ex)[:1000]
        latencia_ms = int((time.time() - t0) * 1000)

        try:
            EntregaWebhookSaliente.objects.create(
                webhook=wh, evento=evento, payload=payload,
                status_code=status_code, respuesta=respuesta_txt,
                exitoso=exitoso, latencia_ms=latencia_ms,
            )
        except Exception:
            logger.exception('No se pudo registrar EntregaWebhookSaliente')

        _actualizar_backoff(wh, exitoso, respuesta_txt)
        if exitoso:
            entregados += 1

    return entregados


def _actualizar_backoff(wh, exitoso: bool, error_txt: str) -> None:
    if exitoso:
        wh.fallos_consecutivos = 0
        wh.ultimo_error = ''
        wh.proximo_intento = None
        wh.ultima_entrega = timezone.now()
        wh.save(update_fields=['fallos_consecutivos', 'ultimo_error',
                               'proximo_intento', 'ultima_entrega'])
        return

    wh.fallos_consecutivos = (wh.fallos_consecutivos or 0) + 1
    wh.ultimo_error = error_txt or 'error desconocido'
    espera = min(BASE_BACKOFF_SEG * (2 ** (wh.fallos_consecutivos - 1)), MAX_BACKOFF_SEG)
    wh.proximo_intento = timezone.now() + timezone.timedelta(seconds=espera)

    campos = ['fallos_consecutivos', 'ultimo_error', 'proximo_intento']
    if wh.fallos_consecutivos >= MAX_FALLOS:
        wh.activo = False
        campos.append('activo')
        logger.warning('Webhook saliente %s desactivado tras %s fallos', wh.id, wh.fallos_consecutivos)
    wh.save(update_fields=campos)
