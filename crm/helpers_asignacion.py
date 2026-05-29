"""Helpers para asignación automática de agentes humanos a conversaciones.

Se invoca desde:
- `crm/motor_flujo_chatbot.py` cuando un nodo `handoff` se activa
  (el flujo dice "contactar con un asesor").
- Cualquier action manual que asigne / reasigne (UI), si querés unificar la
  notificación (push + email + interna).

Política de auto-asignación (orden de prioridad):
1. Si la conversación ya tiene `asignado_a` → no se cambia.
2. Si la sesión tiene `usuario` (responsable de la sesión) → ese usuario.
3. Si el departamento del flujo tiene `PerfilDepartamentoChatBot` activos →
   uno al azar entre los que tienen email **o** suscripción push.
4. Si nada de lo anterior matchea → no asigna (devuelve `None`).

Cuando hay asignación, se dispara:
- Notificación interna (`seguridad.Notificacion`) — su `save()` también
  dispara push web vía `_disparar_webpush`.
- Correo a la dirección del agente (si tiene una configurada).
"""
from __future__ import annotations

import logging
import random

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


MOTIVOS_LABEL = {
    'handoff': 'Transferido por el flujo del chatbot',
    'manual': 'Asignación manual',
    'round_robin': 'Round-robin automático',
}


def _link_conversacion(conv) -> str:
    try:
        from core.funciones import encrypt_sesion_id
        token = encrypt_sesion_id(conv.id)
        base = getattr(settings, 'URL_GENERAL', '').rstrip('/')
        return f'{base}/whatsapp/conversaciones/?conv={token}'
    except Exception:
        return '/whatsapp/conversaciones/'


def _resolver_departamento(conversacion):
    try:
        from crm.models import DepartamentoChatBot, EstadoFlujoChatbot
    except Exception:
        return None
    estado = EstadoFlujoChatbot.objects.filter(conversacion=conversacion).first()
    if estado and estado.departamento_id:
        return estado.departamento
    sesion = getattr(conversacion.contacto, 'sesion', None)
    if sesion and sesion.departamento_default_id:
        return sesion.departamento_default
    return DepartamentoChatBot.objects.filter(es_default=True, status=True).first()


def _agentes_del_departamento(depto):
    if not depto:
        return []
    try:
        from crm.models import PerfilDepartamentoChatBot
    except Exception:
        return []
    rels = (
        PerfilDepartamentoChatBot.objects
        .filter(departamento=depto, status=True, usuario__is_active=True)
        .select_related('usuario')
    )
    return [r.usuario for r in rels if r.usuario_id]


def _ultimo_mensaje_cliente(conv):
    try:
        from whatsapp.models import MensajeWhatsApp
        sesion_num = getattr(conv.contacto.sesion, 'numero', '') or ''
        m = (
            MensajeWhatsApp.objects.filter(conversacion=conv)
            .exclude(remitente=sesion_num)
            .order_by('-fecha')
            .values_list('mensaje', flat=True)
            .first()
        )
        return (m or '').strip()
    except Exception:
        return ''


def notificar_agente_asignado(conversacion, agente, motivo='handoff', asignador=None):
    """Crea la Notificacion interna (→ dispara push) y envía correo al agente.

    No falla si el correo o el push fallan — el side-effect es best-effort.
    """
    if not agente:
        return False
    contacto_nombre = (
        getattr(conversacion.contacto, 'contacto_nombre', None)
        or getattr(conversacion.contacto, 'from_number', None)
        or 'Contacto'
    )
    contacto_numero = getattr(conversacion.contacto, 'from_number', '') or ''
    sesion = getattr(conversacion.contacto, 'sesion', None)
    sesion_nombre = (
        getattr(sesion, 'nombre', None)
        or getattr(sesion, 'numero', None)
        or 'WhatsApp'
    )
    depto = _resolver_departamento(conversacion)
    depto_nombre = getattr(depto, 'nombre', '') if depto else ''
    link_chat = _link_conversacion(conversacion)
    motivo_label = MOTIVOS_LABEL.get(motivo, motivo)

    titulo = f'Se te asignó la conversación con {contacto_nombre}'
    cuerpo = (
        f'{motivo_label}. Conversación #{conversacion.id} de la sesión "{sesion_nombre}". '
    )
    if depto_nombre:
        cuerpo += f'Departamento: {depto_nombre}. '
    cuerpo += 'Abrila desde el sistema para responder.'

    try:
        from seguridad.models import Notificacion
        Notificacion.objects.create(
            titulo=titulo[:300],
            cuerpo=cuerpo,
            destinatario=agente,
            url=link_chat,
            prioridad=2,
            tipo=3,
        )
    except Exception:
        logger.exception('No se pudo crear Notificacion para agente %s conv %s',
                         getattr(agente, 'id', None), conversacion.id)

    email = (getattr(agente, 'email', '') or '').strip()
    if email:
        try:
            from core.email_config import send_html_mail
            datos = {
                'agente_nombre': (agente.get_full_name() or agente.username) if hasattr(agente, 'username') else '',
                'contacto_nombre': contacto_nombre,
                'contacto_numero': contacto_numero,
                'sesion_nombre': sesion_nombre,
                'departamento_nombre': depto_nombre,
                'conv_id': conversacion.id,
                'motivo_label': motivo_label,
                'asignador_nombre': (asignador.get_full_name() if asignador and hasattr(asignador, 'get_full_name') else ''),
                'ultimo_mensaje': _ultimo_mensaje_cliente(conversacion),
                'link_chat': link_chat,
            }
            send_html_mail(
                f'🔔 Conversación asignada — {contacto_nombre} (Conv #{conversacion.id})',
                'email/asignacion_conversacion.html',
                datos,
                [email],
                [],
            )
        except Exception:
            logger.exception('Fallo enviando email de asignación a %s conv %s',
                             email, conversacion.id)
    return True


def auto_asignar_agente(conversacion, motivo='handoff', asignador=None):
    """Asigna un agente humano a la conversación si no tiene uno.

    Returns:
        Usuario asignado (o ya existente) o None si no se pudo elegir.
    """
    if getattr(conversacion, 'asignado_a_id', None):
        return conversacion.asignado_a

    sesion = getattr(conversacion.contacto, 'sesion', None)
    candidato = None

    if sesion and getattr(sesion, 'usuario_id', None):
        candidato = sesion.usuario

    if not candidato:
        depto = _resolver_departamento(conversacion)
        agentes = _agentes_del_departamento(depto)
        if agentes:
            try:
                candidato = random.choice(agentes)
            except Exception:
                candidato = agentes[0] if agentes else None

    if not candidato:
        return None

    try:
        conversacion.asignado_a = candidato
        conversacion.fecha_asignacion = timezone.now()
        if not getattr(conversacion, 'primer_agente_id', None):
            conversacion.primer_agente = candidato
        conversacion.ai_activo = False
        conversacion.save(update_fields=[
            'asignado_a', 'fecha_asignacion', 'primer_agente', 'ai_activo',
        ])
    except Exception:
        logger.exception('No se pudo guardar la asignación auto conv=%s agente=%s',
                         conversacion.id, getattr(candidato, 'id', None))
        return None

    try:
        from whatsapp.models import HistorialAsignacion
        HistorialAsignacion.objects.create(
            conversacion=conversacion,
            asignado_a=candidato,
            asignado_por=asignador,
            nota=f'Asignación automática ({motivo}).',
        )
    except Exception:
        logger.exception('No se pudo crear HistorialAsignacion conv=%s', conversacion.id)

    notificar_agente_asignado(conversacion, candidato, motivo=motivo, asignador=asignador)
    return candidato
