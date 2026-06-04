"""Side-effects genéricos disparados por nodos del flujo del chatbot.

Por ahora solo `notificar_asesores_depto` — se invoca desde el motor cuando
un nodo HTTP tiene `config.envia_correo = true` y respondió 2xx.

Los destinatarios son los asesores DISPONIBLES de la sesión/número
(`PerfilSesionWhatsApp` + `DisponibilidadAgente.disponible`), resueltos por
`crm.helpers_asignacion.asesores_disponibles_sesion`. El departamento solo
aporta una etiqueta informativa, no decide a quién se notifica.
"""
from __future__ import annotations

import logging

from django.conf import settings

from core.email_config import send_html_mail
from core.funciones import encrypt_sesion_id
from crm.models import (
    DepartamentoChatBot,
    EstadoFlujoChatbot,
)


logger = logging.getLogger(__name__)


def _resolver_departamento(conv):
    """Resuelve el depto al que pertenece la conversación, en orden:
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


def _usuarios_a_notificar(conv):
    """Asesores DISPONIBLES de la sesión/número. Fuente única — nunca se
    notifica a alguien fuera del equipo del número."""
    try:
        from crm.helpers_asignacion import asesores_disponibles_sesion
        return asesores_disponibles_sesion(conv)
    except Exception:
        logger.exception('No se pudo resolver asesores de sesión conv#%s', conv.id)
        return []


def _emails_de(usuarios):
    out = []
    for u in usuarios:
        e = (getattr(u, 'email', '') or '').strip()
        if e:
            out.append(e)
    return out


def _link_conversacion(conv) -> str:
    """URL absoluta `/whatsapp/conversaciones/?conv=<token>` con dominio de
    settings. Si la conv ya cerró, view_conversaciones redirige sola a la
    página de finalizadas."""
    base = getattr(settings, 'URL_GENERAL', '').rstrip('/')
    token = encrypt_sesion_id(conv.id)
    return f'{base}/whatsapp/conversaciones/?conv={token}'


def _crear_notificaciones_internas(usuarios, conv, etiqueta, nodo_nombre,
                                   link_chat, mensaje_custom=''):
    try:
        from seguridad.models import Notificacion
    except ImportError:
        return 0
    contacto_nombre = (conv.contacto.contacto_nombre or '').strip() or conv.contacto.from_number
    msg = (mensaje_custom or '').strip()
    if msg:
        titulo = f'🔔 {msg[:200]} — Conv #{conv.id}'
        cuerpo = (
            f'{msg} '
            f'({etiqueta}. Contacto: {contacto_nombre}.)'
        )
    else:
        titulo = f'🔔 {nodo_nombre} — Conv #{conv.id}'
        cuerpo = (
            f'Nueva acción del flujo ({etiqueta}). '
            f'Contacto: {contacto_nombre}. '
            f'Hacé click para abrir la conversación.'
        )
    creadas = 0
    for usuario in usuarios:
        if not usuario:
            continue
        try:
            Notificacion.objects.create(
                titulo=titulo[:300],
                cuerpo=cuerpo,
                destinatario=usuario,
                url=link_chat,
                tipo=3,        # 3 = success (verde) — cotización solicitada
                prioridad=2,   # media
            )
            creadas += 1
        except Exception:
            logger.exception('No se pudo crear Notificacion para usuario %s',
                             getattr(usuario, 'id', None))
    return creadas


def notificar_asesores_depto(conv, nodo=None, request_body=None, response_body=None,
                             asunto=None, mensaje_custom=''):
    depto = _resolver_departamento(conv)
    sesion = getattr(conv.contacto, 'sesion', None)
    etiqueta = (
        f'Departamento "{depto.nombre}"' if depto
        else (f'Sesión "{getattr(sesion, "nombre", "") or getattr(sesion, "numero", "")}"'
              if sesion else 'Flujo')
    )
    usuarios = _usuarios_a_notificar(conv)
    emails = _emails_de(usuarios)
    nodo_nombre = (nodo.nombre if nodo else '') or 'Nodo del flujo'
    link_chat = _link_conversacion(conv)

    n_internas = _crear_notificaciones_internas(
        usuarios, conv, etiqueta, nodo_nombre, link_chat, mensaje_custom=mensaje_custom,
    )

    if not emails:
        logger.warning(
            'Nodo flujo conv#%s: sin asesores disponibles con email '
            '(notificaciones internas creadas: %s)',
            conv.id, n_internas,
        )
        return n_internas > 0  # devuelve True si al menos hubo notif interna

    contacto_nombre = (conv.contacto.contacto_nombre or '').strip() or conv.contacto.from_number
    msg_custom = (mensaje_custom or '').strip()
    datos = {
        'conv_id': conv.id,
        'contacto_nombre': contacto_nombre,
        'contacto_numero': conv.contacto.from_number,
        'depto_nombre': depto.nombre if depto else '',
        'nodo_nombre': nodo_nombre,
        'mensaje_custom': msg_custom,
        'request_body': request_body or {},
        'response_body': response_body or {},
        'link_chat': link_chat,
        'cliente': (request_body or {}).get('cliente') or {},
        'vehiculo': (request_body or {}).get('vehiculo') or {},
        'aseguradoras': (request_body or {}).get('aseguradoras') or {},
        'respuesta_webhook': response_body or {},
    }
    if asunto:
        asunto_final = asunto
    elif msg_custom:
        asunto_final = f'🔔 {msg_custom[:120]} — Conv #{conv.id}'
    else:
        asunto_final = f'🔔 Acción del flujo "{nodo_nombre}" — Conv #{conv.id}'
    try:
        send_html_mail(asunto_final, 'email/asesor_cotizacion.html', datos, emails, [])
        logger.info('Notificación dual: %s correos + %s notif internas (conv#%s, nodo %s)',
                    len(emails), n_internas, conv.id, nodo.id if nodo else '?')
        return True
    except Exception:
        logger.exception('Fallo enviando correo de flujo conv#%s', conv.id)
        return n_internas > 0
