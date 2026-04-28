"""Side-effects genéricos disparados por nodos del flujo del chatbot.

Por ahora solo `notificar_asesores_depto` — se invoca desde el motor cuando
un nodo HTTP tiene `config.envia_correo = true` y respondió 2xx.

El flujo NO modifica destinatarios ni asunto; siempre va a TODOS los
asesores activos del departamento (`PerfilDepartamentoChatBot.status=True`).
Si en el futuro querés segmentar, agregás un `config.correo_destinatarios`
que reciba una lista o filtro.
"""
from __future__ import annotations

import logging

from django.conf import settings

from core.email_config import send_html_mail
from core.funciones import encrypt_sesion_id
from crm.models import (
    DepartamentoChatBot,
    EstadoFlujoChatbot,
    PerfilDepartamentoChatBot,
)


logger = logging.getLogger(__name__)


def _resolver_departamento(conv):
    """Mismo orden que `cotizar_proxy._resolver_departamento`:
    1. EstadoFlujoChatbot.departamento (depto activo del flujo).
    2. SesionWhatsApp.departamento_default.
    3. Fallback: depto con `codigo='aria'` (legacy del seed).
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
        .exclude(usuario__email__isnull=True)
        .exclude(usuario__email='')
    )


def _link_conversacion(conv) -> str:
    """URL absoluta `/whatsapp/conversaciones/?conv=<token>` con dominio de
    settings. Si la conv ya cerró, view_conversaciones redirige sola a la
    página de finalizadas."""
    base = getattr(settings, 'URL_GENERAL', '').rstrip('/')
    token = encrypt_sesion_id(conv.id)
    return f'{base}/whatsapp/conversaciones/?conv={token}'


def notificar_asesores_depto(conv, nodo=None, request_body=None, response_body=None,
                             asunto=None):
    """Envía correo HTML a TODOS los asesores activos del depto del flujo.

    Llamado desde el motor cuando un nodo HTTP exitoso tiene
    `config.envia_correo=true`. Idempotente: si no hay asesores con email,
    solo loguea — el flujo del cliente no se rompe.
    """
    depto = _resolver_departamento(conv)
    emails = _emails_asesores(depto)
    if not emails:
        logger.warning(
            'Nodo flujo conv#%s: sin asesores con email en depto %s',
            conv.id, depto.nombre if depto else '(none)',
        )
        return False

    nodo_nombre = (nodo.nombre if nodo else '') or 'Nodo del flujo'
    contacto_nombre = (conv.contacto.contacto_nombre or '').strip() or conv.contacto.from_number
    datos = {
        'conv_id': conv.id,
        'contacto_nombre': contacto_nombre,
        'contacto_numero': conv.contacto.from_number,
        'depto_nombre': depto.nombre if depto else '',
        'nodo_nombre': nodo_nombre,
        'request_body': request_body or {},
        'response_body': response_body or {},
        'link_chat': _link_conversacion(conv),
        # Atajos legacy compatibles con `email/asesor_cotizacion.html`
        # (que arma su propio HTML usando claves específicas).
        'cliente': (request_body or {}).get('cliente') or {},
        'vehiculo': (request_body or {}).get('vehiculo') or {},
        'aseguradoras': (request_body or {}).get('aseguradoras') or {},
        'respuesta_webhook': response_body or {},
    }
    asunto_final = asunto or f'🔔 Acción del flujo "{nodo_nombre}" — Conv #{conv.id}'
    try:
        send_html_mail(asunto_final, 'email/asesor_cotizacion.html', datos, emails, [])
        logger.info('Correo enviado a %s asesores (conv#%s, nodo %s)',
                    len(emails), conv.id, nodo.id if nodo else '?')
        return True
    except Exception:
        logger.exception('Fallo enviando correo de flujo conv#%s', conv.id)
        return False
