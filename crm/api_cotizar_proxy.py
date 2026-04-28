"""Proxy interno para el flujo de cotización ARIA.

El motor del flujo del chatbot tradicional invoca un único nodo HTTP que pega
acá. Este endpoint orquesta dos efectos:

1. POST al webhook externo `https://fguerrero.mgaseguros.ec/webhook/cotizar/`
   con el body que arma el flujo (cliente + vehiculo + aseguradoras).
2. Si el webhook acepta (HTTP 202 con `ok: true`), envía un correo a los
   asesores del departamento del flujo — todos los `PerfilDepartamentoChatBot`
   activos del depto cuyo `EstadoFlujoChatbot.departamento` coincide con la
   conversación.

Devuelve siempre `{success: bool, message: str}` para que el motor del flujo
ramifique a `siguiente_ok` (success=True) o `siguiente_error` (success=False).

Sin auth — es un endpoint interno, lo único que valida es que la conversación
exista y no esté finalizada.
"""
from __future__ import annotations

import json
import logging

import requests
from django.conf import settings
from django.http import JsonResponse
from django.template.loader import get_template
from django.urls import reverse  # noqa: F401  (se usa indirectamente para tests)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.email_config import send_html_mail
from core.funciones import encrypt_sesion_id
from crm.models import (
    DepartamentoChatBot,
    EstadoFlujoChatbot,
    PerfilDepartamentoChatBot,
)
from whatsapp.models import ConversacionWhatsApp


logger = logging.getLogger(__name__)


WEBHOOK_ARIA_URL = 'https://fguerrero.mgaseguros.ec/webhook/cotizar/'
WEBHOOK_TIMEOUT_SEG = 30


def _resolver_departamento(conv: ConversacionWhatsApp):
    """Resuelve el depto desde el cual notificar.
    Orden de preferencia:
      1. EstadoFlujoChatbot.departamento (depto activo del flujo).
      2. SesionWhatsApp.departamento_default.
      3. Depto con codigo='aria' (fallback del seed).
    """
    estado = EstadoFlujoChatbot.objects.filter(conversacion=conv).first()
    if estado and estado.departamento:
        return estado.departamento
    sesion = getattr(conv.contacto, 'sesion', None)
    if sesion and sesion.departamento_default:
        return sesion.departamento_default
    return DepartamentoChatBot.objects.filter(codigo='aria', status=True).first()


def _emails_asesores(depto):
    if not depto:
        return []
    return list(
        PerfilDepartamentoChatBot.objects
        .filter(departamento=depto, status=True)
        .select_related('usuario')
        .values_list('usuario__email', flat=True)
        .exclude(usuario__email='')
    )


def _link_conversacion(conv: ConversacionWhatsApp) -> str:
    """Arma URL absoluta a /whatsapp/conversaciones/?conv=<token> con dominio
    de settings. Si la conv está finalizada, view_conversaciones la redirige
    sola a /conversaciones-finalizadas/."""
    base = getattr(settings, 'URL_GENERAL', '').rstrip('/')
    token = encrypt_sesion_id(conv.id)
    return f'{base}/whatsapp/conversaciones/?conv={token}'


def _enviar_correo_asesores(conv, body_webhook, respuesta_webhook):
    depto = _resolver_departamento(conv)
    emails = _emails_asesores(depto)
    if not emails:
        logger.warning(
            'Cotización conv#%s: no hay asesores con email en depto %s',
            conv.id, depto.nombre if depto else '(none)'
        )
        return False
    cliente = body_webhook.get('cliente') or {}
    vehiculo = body_webhook.get('vehiculo') or {}
    datos = {
        'conv_id': conv.id,
        'contacto_nombre': (conv.contacto.contacto_nombre or '').strip()
                           or conv.contacto.from_number,
        'contacto_numero': conv.contacto.from_number,
        'cliente': cliente,
        'vehiculo': vehiculo,
        'aseguradoras': body_webhook.get('aseguradoras') or {},
        'respuesta_webhook': respuesta_webhook,
        'link_chat': _link_conversacion(conv),
        'depto_nombre': depto.nombre if depto else '',
    }
    asunto = f'🚗 Nueva cotización solicitada — Conv #{conv.id}'
    send_html_mail(asunto, 'email/asesor_cotizacion.html', datos, emails, [])
    return True


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

    # Éxito: notificar por correo a los asesores del depto.
    try:
        _enviar_correo_asesores(conv, payload, resp_json)
    except Exception:
        # Si el correo falla, NO rompemos el flujo del cliente — la cotización
        # ya está encolada del lado de ARIA. Solo logueamos.
        logger.exception('Fallo enviando correo de cotización conv#%s', conv.id)

    return JsonResponse({
        'success': True,
        'message': resp_json.get('mensaje') or 'Cotización en proceso.',
        'status': resp_json.get('status') or 'encolado',
    })
