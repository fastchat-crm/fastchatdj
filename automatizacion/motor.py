"""Motor: evalúa disparadores y ejecuta acciones.

Dos puntos de entrada:

    disparar(evento, contexto)   → lo llama el código de dominio cuando pasa algo
    procesar_pendientes()        → lo llama el cron cada minuto

`disparar` NO ejecuta nada de forma síncrona: crea la ejecución y vuelve. Así un
webhook lento o un envío caído nunca bloquean el flujo que disparó el evento
(guardar un contacto, cerrar una conversación). El cron hace el trabajo real.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    ACCION_AGREGAR_ETIQUETA,
    ACCION_ASIGNAR_ASESOR,
    ACCION_ENVIAR_EMAIL,
    ACCION_ENVIAR_WHATSAPP,
    ACCION_ESPERAR,
    ACCION_NOTIFICAR,
    ACCION_WEBHOOK,
    ESTADO_COMPLETADA,
    ESTADO_ESPERANDO,
    ESTADO_FALLIDA,
    ESTADO_PENDIENTE,
    Automatizacion,
    EjecucionAutomatizacion,
    LogAutomatizacion,
)

logger = logging.getLogger(__name__)

MAX_INTENTOS = 3


# ---------------------------------------------------------------------------
# Condiciones
# ---------------------------------------------------------------------------

def _valor_contexto(contexto, ruta):
    """Lee `cliente.nombre` de un dict anidado. Devuelve None si no existe."""
    actual = contexto
    for parte in str(ruta or '').split('.'):
        if isinstance(actual, dict):
            actual = actual.get(parte)
        else:
            return None
    return actual


def _cumple(condicion, contexto):
    campo = condicion.get('campo')
    operador = condicion.get('operador') or 'igual'
    esperado = condicion.get('valor')
    actual = _valor_contexto(contexto, campo)

    if operador == 'existe':
        return actual not in (None, '', [], {})
    if operador == 'vacio':
        return actual in (None, '', [], {})

    if operador in ('mayor', 'menor'):
        try:
            a, b = float(actual), float(esperado)
        except (TypeError, ValueError):
            return False
        return a > b if operador == 'mayor' else a < b

    texto_actual = '' if actual is None else str(actual).strip().lower()
    texto_esperado = '' if esperado is None else str(esperado).strip().lower()

    if operador == 'igual':
        return texto_actual == texto_esperado
    if operador == 'distinto':
        return texto_actual != texto_esperado
    if operador == 'contiene':
        return texto_esperado in texto_actual
    if operador == 'no_contiene':
        return texto_esperado not in texto_actual
    return False


def cumple_condiciones(automatizacion, contexto):
    """Todas las condiciones deben cumplirse. Sin condiciones, siempre pasa."""
    condiciones = automatizacion.condiciones or []
    if not condiciones:
        return True
    try:
        return all(_cumple(c, contexto) for c in condiciones)
    except Exception as ex:
        logger.warning('Automatización %s: no se pudieron evaluar las condiciones: %s',
                       automatizacion.id, ex)
        return False


# ---------------------------------------------------------------------------
# Disparo
# ---------------------------------------------------------------------------

def disparar(evento, contexto=None, usuario=None):
    """Crea una ejecución por cada automatización activa que matchee.

    Nunca lanza: un fallo acá no puede romper el flujo de negocio que lo llamó
    (guardar un contacto, cerrar una conversación). Devuelve cuántas se crearon.
    """
    contexto = contexto or {}
    creadas = 0
    try:
        qs = Automatizacion.objects.filter(evento=evento, activo=True, status=True)
        if usuario is not None:
            qs = qs.filter(usuario=usuario)

        for automatizacion in qs:
            if not cumple_condiciones(automatizacion, contexto):
                continue
            if not automatizacion.acciones_activas().exists():
                continue
            EjecucionAutomatizacion.objects.create(
                automatizacion=automatizacion,
                contexto=contexto,
                estado=ESTADO_PENDIENTE,
                ejecutar_en=timezone.now(),
            )
            Automatizacion.objects.filter(pk=automatizacion.pk).update(
                total_ejecuciones=F('total_ejecuciones') + 1,
                ultima_ejecucion=timezone.now(),
            )
            creadas += 1
    except Exception as ex:
        logger.exception('No se pudo disparar el evento %s: %s', evento, ex)
    return creadas


# ---------------------------------------------------------------------------
# Ejecución de acciones
# ---------------------------------------------------------------------------

def _contacto_de(contexto):
    from whatsapp.models import Contacto
    cid = contexto.get('contacto_id')
    if not cid:
        return None
    return Contacto.objects.filter(pk=cid, status=True).first()


def _interpolar(texto, contexto):
    """Reemplaza {{campo}} por su valor del contexto.

    Deliberadamente simple: sin lógica ni filtros. Un placeholder que no existe
    se reemplaza por vacío en vez de romper el envío.
    """
    import re
    def sustituir(m):
        valor = _valor_contexto(contexto, m.group(1).strip())
        return '' if valor is None else str(valor)
    return re.sub(r'\{\{([^}]+)\}\}', sustituir, texto or '')


def _accion_enviar_whatsapp(accion, contexto):
    contacto = _contacto_de(contexto)
    if not contacto:
        return False, 'El evento no trae un contacto al que escribirle.'
    texto = _interpolar((accion.parametros or {}).get('mensaje') or '', contexto)
    if not texto.strip():
        return False, 'El mensaje quedó vacío.'

    from whatsapp.services import get_whatsapp_service
    sesion = contacto.sesion
    servicio = get_whatsapp_service(sesion)
    res = servicio.send_text_message(sesion.session_id, contacto.from_number, texto)
    if isinstance(res, dict) and res.get('error'):
        return False, str(res.get('error'))[:400]
    return True, f'Mensaje enviado a {contacto.from_number}.'


def _accion_enviar_email(accion, contexto):
    p = accion.parametros or {}
    # `Contacto` no tiene campo email, así que el destinatario sale del
    # parámetro — literal o interpolado desde el contexto del evento
    # (ej. "{{cliente.email}}" cuando el evento lo trae).
    destino = _interpolar(p.get('destinatario') or '', contexto).strip()
    if not destino:
        return False, 'No hay destinatario para el correo. Indicá uno en la acción.'

    from core.email_config import send_html_mail
    asunto = _interpolar(p.get('asunto') or 'Notificación', contexto)
    cuerpo = _interpolar(p.get('cuerpo') or '', contexto)
    send_html_mail(asunto, 'email/email_default.html', {'contenido': cuerpo}, [destino], [])
    return True, f'Correo encolado a {destino}.'


def _accion_agregar_etiqueta(accion, contexto):
    contacto = _contacto_de(contexto)
    if not contacto:
        return False, 'El evento no trae un contacto que etiquetar.'
    nombre = _interpolar((accion.parametros or {}).get('etiqueta') or '', contexto).strip()
    if not nombre:
        return False, 'No se indicó qué etiqueta agregar.'

    from whatsapp.models import EtiquetaContacto
    etiqueta = EtiquetaContacto.objects.filter(nombre__iexact=nombre, status=True).first()
    if not etiqueta:
        return False, f'No existe la etiqueta «{nombre}». Creala primero en Etiquetas.'
    contacto.etiquetas.add(etiqueta)
    return True, f'Etiqueta «{etiqueta.nombre}» agregada.'


def _accion_asignar_asesor(accion, contexto):
    conv_id = contexto.get('conversacion_id')
    if not conv_id:
        return False, 'El evento no trae una conversación que asignar.'

    from whatsapp.models import ConversacionWhatsApp
    conv = ConversacionWhatsApp.objects.filter(pk=conv_id, status=True).first()
    if not conv:
        return False, 'No se encontró la conversación.'

    from crm.helpers_asignacion import candidatos_ordenados
    candidatos = candidatos_ordenados(conv)
    if not candidatos:
        return False, 'No hay asesores disponibles.'
    conv.asignado_a = candidatos[0]
    conv.ai_activo = False
    conv.save(update_fields=['asignado_a', 'ai_activo'])
    return True, f'Asignada a {conv.asignado_a}.'


def _accion_webhook(accion, contexto):
    import requests
    p = accion.parametros or {}
    url = (p.get('url') or '').strip()
    if not url.startswith(('http://', 'https://')):
        return False, 'La URL del webhook no es válida.'
    try:
        r = requests.post(url, json=contexto, timeout=15)
        if r.status_code >= 400:
            return False, f'El webhook respondió {r.status_code}.'
        return True, f'Webhook llamado ({r.status_code}).'
    except Exception as ex:
        return False, f'No se pudo llamar al webhook: {ex}'


def _accion_notificar(accion, contexto):
    p = accion.parametros or {}
    mensaje = _interpolar(p.get('mensaje') or '', contexto)
    if not mensaje.strip():
        return False, 'El mensaje de la notificación quedó vacío.'
    try:
        from seguridad.models import Notificacion
        from autenticacion.models import Usuario
        destino = Usuario.objects.filter(pk=p.get('usuario_id'), is_active=True).first()
        if not destino:
            return False, 'No se encontró al usuario a notificar.'
        Notificacion.objects.create(
            destinatario=destino,
            titulo=(p.get('titulo') or 'Automatización')[:300],
            cuerpo=mensaje[:4000],
            url=(p.get('url') or '')[:300] or None,
        )
        return True, f'Notificación enviada a {destino}.'
    except Exception as ex:
        return False, f'No se pudo notificar: {ex}'


EJECUTORES = {
    ACCION_ENVIAR_WHATSAPP: _accion_enviar_whatsapp,
    ACCION_ENVIAR_EMAIL: _accion_enviar_email,
    ACCION_AGREGAR_ETIQUETA: _accion_agregar_etiqueta,
    ACCION_ASIGNAR_ASESOR: _accion_asignar_asesor,
    ACCION_WEBHOOK: _accion_webhook,
    ACCION_NOTIFICAR: _accion_notificar,
}


def _log(ejecucion, accion_tipo, ok, detalle):
    try:
        LogAutomatizacion.objects.create(
            ejecucion=ejecucion, accion=accion_tipo, ok=ok, detalle=str(detalle)[:2000]
        )
    except Exception:
        logger.exception('No se pudo registrar el log de la ejecución %s', ejecucion.id)


def ejecutar(ejecucion):
    """Corre la ejecución desde `indice_accion` hasta terminar o toparse con un
    `esperar`. Devuelve el estado final."""
    acciones = list(ejecucion.automatizacion.acciones_activas())

    while ejecucion.indice_accion < len(acciones):
        accion = acciones[ejecucion.indice_accion]

        if accion.tipo == ACCION_ESPERAR:
            demora = accion.demora()
            # Se avanza el índice ANTES de dormir: al retomar no se vuelve a
            # esperar el mismo paso.
            ejecucion.indice_accion += 1
            ejecucion.estado = ESTADO_ESPERANDO
            ejecucion.ejecutar_en = timezone.now() + demora
            ejecucion.save(update_fields=['indice_accion', 'estado', 'ejecutar_en'])
            _log(ejecucion, ACCION_ESPERAR, True, f'Retoma el {ejecucion.ejecutar_en:%Y-%m-%d %H:%M}.')
            return ESTADO_ESPERANDO

        ejecutor = EJECUTORES.get(accion.tipo)
        if not ejecutor:
            _log(ejecucion, accion.tipo, False, 'Tipo de acción desconocido.')
            ejecucion.indice_accion += 1
            continue

        try:
            ok, detalle = ejecutor(accion, ejecucion.contexto or {})
        except Exception as ex:
            logger.exception('Acción %s falló en la ejecución %s', accion.tipo, ejecucion.id)
            ok, detalle = False, f'Error inesperado: {ex}'

        _log(ejecucion, accion.tipo, ok, detalle)

        if not ok:
            # Una acción fallida no cancela la automatización entera: se
            # reintenta la ejecución completa desde este paso hasta MAX_INTENTOS.
            ejecucion.intentos += 1
            ejecucion.error = str(detalle)[:1000]
            if ejecucion.intentos >= MAX_INTENTOS:
                ejecucion.estado = ESTADO_FALLIDA
                ejecucion.save(update_fields=['intentos', 'error', 'estado'])
                return ESTADO_FALLIDA
            # Backoff lineal: 10, 20, 30 minutos.
            ejecucion.estado = ESTADO_ESPERANDO
            ejecucion.ejecutar_en = timezone.now() + timedelta(minutes=10 * ejecucion.intentos)
            ejecucion.save(update_fields=['intentos', 'error', 'estado', 'ejecutar_en'])
            return ESTADO_ESPERANDO

        ejecucion.indice_accion += 1
        ejecucion.save(update_fields=['indice_accion'])

    ejecucion.estado = ESTADO_COMPLETADA
    ejecucion.save(update_fields=['estado'])
    return ESTADO_COMPLETADA


def procesar_pendientes(limite=100):
    """Levanta las ejecuciones vencidas. Lo llama el cron.

    Se toma cada una con `select_for_update(skip_locked=True)` para que dos
    corridas solapadas del cron no procesen la misma ejecución dos veces.
    """
    ahora = timezone.now()
    procesadas = {'completadas': 0, 'esperando': 0, 'fallidas': 0}

    ids = list(
        EjecucionAutomatizacion.objects
        .filter(estado__in=[ESTADO_PENDIENTE, ESTADO_ESPERANDO],
                ejecutar_en__lte=ahora, status=True)
        .order_by('ejecutar_en')
        .values_list('id', flat=True)[:limite]
    )

    for ejecucion_id in ids:
        try:
            with transaction.atomic():
                ejecucion = (
                    EjecucionAutomatizacion.objects
                    .select_for_update(skip_locked=True)
                    .filter(pk=ejecucion_id,
                            estado__in=[ESTADO_PENDIENTE, ESTADO_ESPERANDO],
                            ejecutar_en__lte=ahora)
                    .first()
                )
                if not ejecucion:
                    continue
                estado = ejecutar(ejecucion)
            if estado == ESTADO_COMPLETADA:
                procesadas['completadas'] += 1
            elif estado == ESTADO_FALLIDA:
                procesadas['fallidas'] += 1
            else:
                procesadas['esperando'] += 1
        except Exception:
            logger.exception('No se pudo procesar la ejecución %s', ejecucion_id)

    return procesadas
