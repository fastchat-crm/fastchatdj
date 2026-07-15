"""Meta Conversions API (CAPI) sender.

Dispara eventos Lead / Purchase / CompleteRegistration al Pixel/Dataset de Meta
para que Ads Manager pueda optimizar y atribuir campañas (en especial CTWA).

Cada llamada se registra en `EventoCAPI` para auditoría y reintento.

Referencia:
    https://developers.facebook.com/docs/marketing-api/conversions-api

El evento trae `ctwa_clid` (click-to-WhatsApp click ID) cuando está disponible
en la conversación origen — ese es el link que cierra el loop desde el ad hasta
la conversión offline.
"""
from __future__ import annotations

import hashlib
import logging
import time
from decimal import Decimal
from typing import Optional

import requests
from django.utils import timezone

from whatsapp.models import ConversacionWhatsApp, EventoCAPI, PixelMeta

from .urls import GRAPH_API_VERSION

logger = logging.getLogger(__name__)

GRAPH_API_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'


def _sha256(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(str(value).strip().lower().encode('utf-8')).hexdigest()


def _build_user_data(conv: ConversacionWhatsApp) -> dict:
    """Construye el bloque user_data que Meta exige. Al menos un identificador
    hasheado debe estar presente."""
    contacto = conv.contacto
    numero = (contacto.contacto_numero or '').strip()
    nombre = (contacto.contacto_nombre or '').strip()
    partes = nombre.split(' ', 1)
    first = partes[0] if partes else ''
    last = partes[1] if len(partes) > 1 else ''

    ud = {}
    if numero:
        ud['ph'] = [_sha256(numero)]
    if first:
        ud['fn'] = [_sha256(first)]
    if last:
        ud['ln'] = [_sha256(last)]
    if conv.ctwa_clid:
        ud['ctwa_clid'] = conv.ctwa_clid
    if contacto.external_id:
        ud['external_id'] = [_sha256(contacto.external_id)]
    return ud


def _resolver_pixel(conv: ConversacionWhatsApp) -> Optional[PixelMeta]:
    """Prioridad: pixel configurado en la sesión → primer pixel activo global."""
    sesion = conv.sesion
    if sesion and sesion.pixel_meta_id:
        pm = sesion.pixel_meta
        if pm and pm.activo:
            return pm
    return PixelMeta.objects.filter(activo=True, status=True).first()


def enviar_evento(conv: ConversacionWhatsApp, event_name: str,
                  value: float = 0, currency: str = 'USD',
                  custom_data_extra: Optional[dict] = None) -> dict:
    """Envía un evento a Meta CAPI para la conversación dada.

    Args:
        conv: ConversacionWhatsApp con (idealmente) ctwa_clid seteado.
        event_name: 'Lead', 'Purchase', 'CompleteRegistration', etc.
        value, currency: para eventos monetarios.
        custom_data_extra: extras mergeados a custom_data del payload.

    Returns dict con keys: success, status, error, evento_capi_id.
    """
    pixel = _resolver_pixel(conv)
    if not pixel:
        return {'success': False, 'error': 'no_pixel_configurado'}

    event_time_dt = timezone.now()
    event_time_unix = int(event_time_dt.timestamp())
    event_id = f"conv_{conv.id}_{event_name}_{event_time_unix}"

    user_data = _build_user_data(conv)
    if not user_data:
        return {'success': False, 'error': 'sin_identificador_usuario'}

    custom_data = {
        'currency': currency,
        'value':    float(value) if value else 0.0,
    }
    if conv.ctwa_clid:
        # Meta usa ctwa_clid también como content identifier para CTWA
        custom_data['ctwa_clid'] = conv.ctwa_clid
    if conv.ad_id:
        custom_data['ad_id'] = conv.ad_id
    if conv.campaign_id:
        custom_data['campaign_id'] = conv.campaign_id
    if custom_data_extra:
        custom_data.update(custom_data_extra)

    data_evento = {
        'event_name':        event_name,
        'event_time':        event_time_unix,
        'event_id':          event_id,
        'action_source':     'business_messaging',
        'messaging_channel': 'whatsapp' if (conv.origen_canal or '') in ('whatsapp', '') else conv.origen_canal,
        'user_data':         user_data,
        'custom_data':       custom_data,
    }
    if conv.referral_source_url:
        data_evento['event_source_url'] = conv.referral_source_url

    payload = {'data': [data_evento]}
    if pixel.test_event_code:
        payload['test_event_code'] = pixel.test_event_code

    url = f"{GRAPH_API_BASE}/{pixel.pixel_id}/events"
    params = {'access_token': pixel.access_token}

    evento_log = EventoCAPI.objects.create(
        pixel=pixel,
        conversacion=conv,
        event_name=event_name,
        event_id=event_id,
        event_time=event_time_dt,
        valor=Decimal(str(value or 0)),
        moneda=currency,
        ctwa_clid=conv.ctwa_clid or '',
        payload_json=payload,
    )

    t0 = time.monotonic()
    try:
        r = requests.post(url, params=params, json=payload, timeout=15)
        evento_log.response_status = r.status_code
        evento_log.response_body = (r.text or '')[:4000]
        evento_log.exitoso = 200 <= r.status_code < 300
        if not evento_log.exitoso:
            evento_log.error = f"HTTP {r.status_code}"
        evento_log.save(update_fields=[
            'response_status', 'response_body', 'exitoso', 'error',
        ])
        latencia_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "CAPI %s conv=%s pixel=%s status=%s lat=%sms",
            event_name, conv.id, pixel.pixel_id, r.status_code, latencia_ms,
        )
        return {
            'success':        evento_log.exitoso,
            'status':         r.status_code,
            'evento_capi_id': evento_log.id,
            'error':          evento_log.error or None,
        }
    except Exception as e:
        evento_log.error = str(e)[:2000]
        evento_log.exitoso = False
        evento_log.save(update_fields=['error', 'exitoso'])
        logger.exception("CAPI excepción conv=%s event=%s", conv.id, event_name)
        return {'success': False, 'error': str(e), 'evento_capi_id': evento_log.id}


def reportar_lead_si_corresponde(conv: ConversacionWhatsApp) -> Optional[dict]:
    """Helper: envía evento Lead si la conversación tiene atribución y aún no se reportó."""
    if conv.capi_lead_enviado:
        return None
    if not (conv.ctwa_clid or conv.ad_id or conv.campaign_id):
        return None  # sin atribución no tiene sentido
    res = enviar_evento(conv, 'Lead')
    if res.get('success'):
        conv.capi_lead_enviado = True
        conv.save(update_fields=['capi_lead_enviado'])
    return res


def reportar_purchase(conv: ConversacionWhatsApp, value: float, currency: str = 'USD') -> Optional[dict]:
    """Envía Purchase si aún no se reportó."""
    if conv.capi_purchase_enviado:
        return None
    res = enviar_evento(conv, 'Purchase', value=value, currency=currency)
    if res.get('success'):
        conv.capi_purchase_enviado = True
        conv.save(update_fields=['capi_purchase_enviado'])
    return res
