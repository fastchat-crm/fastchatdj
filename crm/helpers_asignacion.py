"""Helpers para asignación automática de agentes humanos a conversaciones.

Se invoca desde:
- `crm/motor_flujo_chatbot.py` cuando un nodo `handoff` se activa
  (el flujo dice "contactar con un asesor").
- Cualquier action manual que asigne / reasigne (UI), si querés unificar la
  notificación (push + email + interna).

Fuente única de verdad de "qué asesor atiende" = el NÚMERO/SESIÓN.
Los asesores se configuran en la sesión vía `PerfilSesionWhatsApp` (roles
'supervisor' y 'asesor' — ambos reciben asignación). La disponibilidad
(`whatsapp.DisponibilidadAgente`) es un filtro ortogonal, no un pool aparte.
Los departamentos definen solo el flujo del bot, NO quién atiende.

Política de auto-asignación:
1. Si la conversación ya tiene `asignado_a` → no se cambia.
2. Pool de candidatos = asesores de la sesión (`PerfilSesionWhatsApp`).
3. Se filtra por disponibilidad (`disponible=True`, carga < `max_conversaciones`).
   Un asesor SIN registro de `DisponibilidadAgente` se considera disponible.
4. Se elige al que MENOS asignaciones recibió en las últimas 24 horas
   (`HistorialAsignacion`). Empate → quien lleva más tiempo sin recibir
   asignación; luego menor carga abierta.
5. Si no hay candidatos → no asigna (devuelve `None`).

Fallback de migración: si la sesión no tiene asesores en `PerfilSesionWhatsApp`,
se cae al pool legacy de `DisponibilidadAgente` por sesión.

Cuando hay asignación, se dispara:
- Notificación interna (`seguridad.Notificacion`) — su `save()` también
  dispara push web vía `_disparar_webpush`.
- Correo a la dirección del agente (si tiene una configurada).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


HORAS_VENTANA_REPARTO = 24

MOTIVOS_LABEL = {
    'handoff': 'Transferido por el flujo del chatbot',
    'manual': 'Asignación manual',
    'round_robin': 'Round-robin automático',
    'fin_flujo': 'Flujo completado — seguimiento de inscripción',
    'masivo': 'Asignación automática masiva',
    'inicio': 'Asignada al iniciar la conversación',
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


def _agentes_de_sesion(sesion):
    """Asesores configurados en la sesión/número vía `PerfilSesionWhatsApp`.
    Incluye ambos roles ('supervisor' y 'asesor') — todos reciben asignación."""
    if not sesion:
        return []
    try:
        from whatsapp.models import PerfilSesionWhatsApp
    except Exception:
        return []
    rels = (
        PerfilSesionWhatsApp.objects
        .filter(sesion=sesion, status=True, usuario__is_active=True)
        .select_related('usuario')
    )
    agentes, vistos = [], set()
    for r in rels:
        if r.usuario_id and r.usuario_id not in vistos:
            vistos.add(r.usuario_id)
            agentes.append(r.usuario)
    return agentes


def _agentes_legacy_disponibilidad(conversacion):
    """Pool legacy por `DisponibilidadAgente` de la sesión. Solo se usa como
    último recurso de migración: cuando ningún departamento de la sesión tiene
    asesores configurados, evita que el round-robin existente deje de asignar."""
    sesion = getattr(getattr(conversacion, 'contacto', None), 'sesion', None)
    if not sesion:
        return []
    try:
        from whatsapp.models import DisponibilidadAgente
    except Exception:
        return []
    agentes, vistos = [], set()
    qs = (
        DisponibilidadAgente.objects
        .filter(disponible=True, status=True, usuario__is_active=True)
        .select_related('usuario').prefetch_related('sesiones')
    )
    for disp in qs:
        ses_ids = list(disp.sesiones.values_list('id', flat=True))
        if ses_ids and sesion.id not in ses_ids:
            continue
        if disp.usuario_id and disp.usuario_id not in vistos:
            vistos.add(disp.usuario_id)
            agentes.append(disp.usuario)
    return agentes


def agentes_candidatos(conversacion):
    """Pool de asesores elegibles para una conversación (sin ordenar ni filtrar
    por carga): los configurados en la sesión/número. Si la sesión no tiene
    ninguno, cae al pool legacy de disponibilidad."""
    sesion = getattr(getattr(conversacion, 'contacto', None), 'sesion', None)
    agentes = _agentes_de_sesion(sesion)
    if not agentes:
        agentes = _agentes_legacy_disponibilidad(conversacion)
    return agentes


def _carga_abierta(usuario):
    """Cantidad de conversaciones abiertas asignadas al usuario."""
    try:
        from whatsapp.models import ConversacionWhatsApp
        return ConversacionWhatsApp.objects.filter(
            asignado_a=usuario, conversacion_finalizada=False, status=True,
        ).count()
    except Exception:
        # No silenciar: si esto falla, todos los asesores parecerían con carga 0
        # y el balanceo se rompe sin ninguna señal. Dejamos rastro.
        logger.exception('No pude calcular la carga abierta de usuario=%s',
                         getattr(usuario, 'id', None))
        return 0


def _asignaciones_ultimas_24h(agentes):
    """Asignaciones recibidas por cada asesor dentro de la ventana de reparto
    (`HORAS_VENTANA_REPARTO`), contadas desde `HistorialAsignacion`. Es el
    criterio principal de selección: gana el que menos recibió."""
    try:
        from django.db.models import Count
        from whatsapp.models import HistorialAsignacion
        desde = timezone.now() - timedelta(hours=HORAS_VENTANA_REPARTO)
        filas = (
            HistorialAsignacion.objects
            .filter(asignado_a__in=agentes, fecha__gte=desde)
            .values('asignado_a')
            .annotate(total=Count('id'))
        )
        return {f['asignado_a']: f['total'] for f in filas}
    except Exception:
        logger.exception('No pude contar asignaciones de las últimas %sh',
                         HORAS_VENTANA_REPARTO)
        return {}


def candidatos_ordenados(conversacion):
    """FUENTE ÚNICA de selección de asesor. Devuelve [(usuario, carga)] ya
    filtrado por disponibilidad y ordenado por menos asignaciones recibidas en
    las últimas 24 horas (empate → quien lleva más tiempo sin recibir
    asignación; luego menor carga abierta).

    La usan por igual el handoff del flujo, el fin de flujo con notificación,
    el round-robin y el dropdown manual.
    """
    agentes = agentes_candidatos(conversacion)
    if not agentes:
        return []
    try:
        from whatsapp.models import DisponibilidadAgente
        disp_map = {
            d.usuario_id: d
            for d in DisponibilidadAgente.objects.filter(usuario__in=agentes, status=True)
        }
    except Exception:
        disp_map = {}

    asig_24h = _asignaciones_ultimas_24h(agentes)

    minimo = timezone.datetime.min
    try:
        minimo = minimo.replace(tzinfo=timezone.get_current_timezone())
    except Exception:
        pass

    elegibles = []
    for u in agentes:
        carga = _carga_abierta(u)
        disp = disp_map.get(u.id)
        if disp is not None:
            if not disp.disponible:
                continue
            if disp.max_conversaciones and carga >= disp.max_conversaciones:
                continue
            ultima = disp.ultimo_asignado_en or minimo
        else:
            ultima = minimo
        elegibles.append((u, carga, asig_24h.get(u.id, 0), ultima))

    elegibles.sort(key=lambda it: (it[2], it[3], it[1]))
    return [(u, carga) for (u, carga, _asig, _ult) in elegibles]


def asesores_disponibles_sesion(conversacion):
    """Asesores de la sesión/número que están DISPONIBLES. Para las
    notificaciones del flujo: mismo pool que la asignación, pero SIN filtrar por
    carga máxima — se avisa a todo el equipo que esté online. Un asesor sin
    registro de `DisponibilidadAgente` se considera disponible."""
    agentes = agentes_candidatos(conversacion)
    if not agentes:
        return []
    try:
        from whatsapp.models import DisponibilidadAgente
        offline = set(
            DisponibilidadAgente.objects.filter(
                usuario__in=agentes, status=True, disponible=False,
            ).values_list('usuario_id', flat=True)
        )
    except Exception:
        offline = set()
    return [u for u in agentes if u.id not in offline]


def _marcar_ultima_asignacion(usuario):
    """Actualiza `DisponibilidadAgente.ultimo_asignado_en` del asesor elegido
    (si tiene registro) para que la rotación por antigüedad sea justa entre
    handoff y round-robin."""
    try:
        from whatsapp.models import DisponibilidadAgente
        DisponibilidadAgente.objects.filter(usuario=usuario).update(
            ultimo_asignado_en=timezone.now()
        )
    except Exception:
        pass


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


def _log_notif(conversacion, agente, canal, motivo, destino, exito, detalle=''):
    """Persiste la traza de un aviso de asignación (best-effort, nunca rompe)."""
    try:
        from crm.models import LogNotificacionAsignacion
        LogNotificacionAsignacion.objects.create(
            conversacion=conversacion,
            agente=agente,
            canal=canal,
            motivo=(motivo or '')[:30],
            destino=(destino or '')[:200],
            exito=bool(exito),
            detalle=(detalle or '')[:1000],
        )
    except Exception:
        logger.exception('No se pudo registrar LogNotificacionAsignacion conv=%s canal=%s',
                         getattr(conversacion, 'id', None), canal)


def _normalizar_e164_ec(crudo):
    """Dígitos E.164. Formato local de Ecuador (09XXXXXXXX o 9XXXXXXXX)
    se convierte a 5939XXXXXXXX."""
    numero = ''.join(filter(str.isdigit, str(crudo or '')))
    if not numero:
        return ''
    if len(numero) == 10 and numero.startswith('0'):
        numero = '593' + numero[1:]
    elif len(numero) == 9 and numero.startswith('9'):
        numero = '593' + numero
    return numero


def _numero_whatsapp_agente(agente):
    return _normalizar_e164_ec(
        getattr(agente, 'telefono', '') or getattr(agente, 'celular', '')
    )


def _avisar_agente_por_whatsapp(conversacion, agente, titulo, link_chat, motivo_label, motivo=''):
    """Envía al TELÉFONO del agente un WhatsApp con el aviso de asignación y el
    link directo a la conversación, usando la propia sesión de la conversación.

    Best-effort: en sesiones Meta el envío puede fallar fuera de la ventana de
    24h (requiere plantilla) — queda logueado sin romper la asignación. Cada
    intento se persiste en `LogNotificacionAsignacion`.
    """
    telefono = _numero_whatsapp_agente(agente)
    sesion = getattr(getattr(conversacion, 'contacto', None), 'sesion', None)
    if not telefono or not sesion or not getattr(sesion, 'activo', False):
        _log_notif(conversacion, agente, 'whatsapp', motivo, telefono, False,
                   'Sin teléfono del agente o sesión inactiva.')
        return False
    try:
        from whatsapp.services import get_whatsapp_service
        destino = telefono
        if getattr(sesion, 'es_baileys', False):
            destino = f'{telefono}@s.whatsapp.net'
        contacto = getattr(conversacion, 'contacto', None)
        nombre_cliente = (
            (getattr(contacto, 'contacto_nombre', '') or '').strip()
            or (getattr(contacto, 'contacto_numero', '') or '').strip()
            or 'Cliente'
        )
        numero_cliente = _normalizar_e164_ec(
            getattr(contacto, 'contacto_numero', '') or getattr(contacto, 'from_number', '')
        )
        linea_wa_cliente = (
            f'📱 WhatsApp del cliente: https://wa.me/{numero_cliente}\n'
            if numero_cliente else ''
        )
        texto = (
            f'🔔 {titulo}.\n'
            f'{motivo_label}.\n'
            f'👤 Cliente: {nombre_cliente}\n'
            f'{linea_wa_cliente}'
            f'💬 Responder desde el panel: {link_chat}'
        )
        service = get_whatsapp_service(sesion)
        respuesta = service.send_text_message(sesion.session_id, destino, texto)
        exito = bool(respuesta.get('success'))
        _log_notif(conversacion, agente, 'whatsapp', motivo, telefono, exito,
                   '' if exito else str(respuesta.get('error') or 'Fallo de envío'))
        return exito
    except Exception as ex:
        logger.exception('No se pudo avisar por WhatsApp al agente %s conv %s',
                         getattr(agente, 'id', None), conversacion.id)
        _log_notif(conversacion, agente, 'whatsapp', motivo, telefono, False, str(ex))
        return False


def notificar_agente_asignado(conversacion, agente, motivo='handoff', asignador=None):
    """Crea la Notificacion interna (→ dispara push), envía correo al agente y
    le manda un WhatsApp a su teléfono con el link de la conversación.

    No falla si el correo, el push o el WhatsApp fallan — todo es best-effort.
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
        _log_notif(conversacion, agente, 'interna', motivo, agente.username, True)
    except Exception as ex:
        logger.exception('No se pudo crear Notificacion para agente %s conv %s',
                         getattr(agente, 'id', None), conversacion.id)
        _log_notif(conversacion, agente, 'interna', motivo, agente.username, False, str(ex))

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
            _log_notif(conversacion, agente, 'correo', motivo, email, True)
        except Exception as ex:
            logger.exception('Fallo enviando email de asignación a %s conv %s',
                             email, conversacion.id)
            _log_notif(conversacion, agente, 'correo', motivo, email, False, str(ex))
    else:
        _log_notif(conversacion, agente, 'correo', motivo, '', False,
                   'El agente no tiene correo configurado.')

    _avisar_agente_por_whatsapp(conversacion, agente, titulo, link_chat, motivo_label, motivo=motivo)
    return True


def _avisar_cliente_asignacion(conversacion, agente):
    """Mensaje al CLIENTE con el nombre del asesor asignado (mismo copy que la
    asignación manual), persistido y difundido al panel."""
    try:
        sesion = conversacion.contacto.sesion
        nombre = agente.get_full_name() or agente.username
        texto = (getattr(sesion, 'mensaje_handoff', None)
                 or f'Hola, te atenderá {nombre}. En breve te contactamos.')
        from whatsapp.services import get_whatsapp_service
        respuesta = get_whatsapp_service(sesion).send_text_message(
            sesion.session_id,
            conversacion.contacto.from_number,
            texto,
            conversacion_id=conversacion.id,
            simularEscritura=True,
        )
        if respuesta.get('success'):
            from whatsapp.funcionesWhatsappConversacion import persistir_y_difundir_automatico
            persistir_y_difundir_automatico(conversacion, texto)
            return True
    except Exception:
        logger.exception('No pude avisar al cliente la asignación conv=%s', conversacion.id)
    return False


def auto_asignar_agente(conversacion, motivo='handoff', asignador=None, avisar_cliente=True,
                        pausar_ia=True, avisar_si_ya_asignado=False):
    """Asigna un agente humano a la conversación si no tiene uno.

    Args:
        avisar_cliente: si True (default), el cliente recibe "te atenderá X"
            (o el `mensaje_handoff` de la sesión), persistido en el historial.
        pausar_ia: si True (default), la asignación apaga `ai_activo`. El bot
            solo debe pausarse cuando el cliente pide un asesor en el flujo, así
            que las asignaciones administrativas (reparto masivo) pasan False y
            dejan al chatbot siguiendo la conversación.
        avisar_si_ya_asignado: para el handoff sobre una conversación que YA
            tiene asesor (sesiones con `asignar_asesor_al_iniciar`): no se
            reasigna a nadie, pero se pausa la IA, se avisa al asesor que ya la
            tiene y se manda el handoff al cliente, igual que un handoff normal.

    Returns:
        Usuario asignado (o ya existente) o None si no se pudo elegir.
    """
    if getattr(conversacion, 'asignado_a_id', None):
        actual = conversacion.asignado_a
        if avisar_si_ya_asignado and actual:
            try:
                if pausar_ia and conversacion.ai_activo:
                    conversacion.ai_activo = False
                    conversacion.save(update_fields=['ai_activo'])
            except Exception:
                logger.exception('No se pudo pausar la IA conv=%s', conversacion.id)
            notificar_agente_asignado(conversacion, actual, motivo=motivo, asignador=asignador)
            if avisar_cliente:
                _avisar_cliente_asignacion(conversacion, actual)
        return actual

    candidatos = candidatos_ordenados(conversacion)
    if not candidatos:
        logger.info('Auto-asignación sin candidatos disponibles conv=%s', conversacion.id)
        return None
    candidato, carga = candidatos[0]

    # Bloqueo de fila: dos handoffs concurrentes de la misma conversación
    # (timeout + fin_flujo, o reintento del webhook) leían asignado_a=None a la
    # vez y ambos asignaban. Re-leemos bajo select_for_update y abortamos si otro
    # proceso ya asignó mientras calculábamos los candidatos.
    from django.db import transaction
    from whatsapp.models import ConversacionWhatsApp
    try:
        with transaction.atomic():
            conv_lock = (
                ConversacionWhatsApp.objects.select_for_update()
                .get(pk=conversacion.pk)
            )
            if conv_lock.asignado_a_id:
                conversacion.asignado_a = conv_lock.asignado_a
                return conv_lock.asignado_a
            conv_lock.asignado_a = candidato
            conv_lock.fecha_asignacion = timezone.now()
            if not conv_lock.primer_agente_id:
                conv_lock.primer_agente = candidato
            campos = ['asignado_a', 'fecha_asignacion', 'primer_agente']
            if pausar_ia:
                conv_lock.ai_activo = False
                campos.append('ai_activo')
            conv_lock.save(update_fields=campos)
        # Reflejar en la instancia recibida por el caller
        conversacion.asignado_a = candidato
        conversacion.fecha_asignacion = conv_lock.fecha_asignacion
        conversacion.primer_agente = conv_lock.primer_agente
        if pausar_ia:
            conversacion.ai_activo = False
    except Exception:
        logger.exception('No se pudo guardar la asignación auto conv=%s agente=%s',
                         conversacion.id, getattr(candidato, 'id', None))
        return None

    _marcar_ultima_asignacion(candidato)

    try:
        from whatsapp.models import HistorialAsignacion
        HistorialAsignacion.objects.create(
            conversacion=conversacion,
            asignado_a=candidato,
            asignado_por=asignador,
            nota=f'Asignación automática ({motivo}). Carga previa: {carga}.',
        )
    except Exception:
        logger.exception('No se pudo crear HistorialAsignacion conv=%s', conversacion.id)

    notificar_agente_asignado(conversacion, candidato, motivo=motivo, asignador=asignador)
    if avisar_cliente:
        _avisar_cliente_asignacion(conversacion, candidato)
    return candidato
