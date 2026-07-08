"""Opt-out (baja) de mensajería masiva — protege la calidad del número.

Meta penaliza el quality rating cuando los usuarios bloquean o reportan un
número. Detectar BAJA/STOP y respetarlo de inmediato es requisito de la
plataforma (error 131050) y buena práctica en Baileys.

Puntos de uso:
  - whatsapp/procesar_mensaje.py  → detecta la palabra clave en el mensaje entrante
  - cron_jobs/ejecutar_campanas.py → excluye contactos con opt_out / número inválido
  - whatsapp/meta_webhook_view.py → marca baja automática ante error 131050 y
    número inválido ante 131030
"""
import logging
import re

from django.utils import timezone

logger = logging.getLogger(__name__)

# OJO: sin 'salir' ni 'cancelar' a secas — son comandos de navegación del
# chatbot tradicional (motor_flujo_chatbot) y marcarían bajas por error.
_OPT_OUT_RE = re.compile(
    r'^\s*(baja|stop|unsubscribe|cancelar\s+suscripci[oó]n'
    r'|no\s+quiero\s+(m[aá]s\s+)?(mensajes|publicidad|promociones|informaci[oó]n)'
    r'|no\s+me\s+env[ií]en?\s+(m[aá]s\s+)?(mensajes|publicidad|promociones)?'
    r'|dar(me)?\s+de\s+baja|quitar(me)?\s+de\s+la\s+lista)\s*[.!❗]*\s*$',
    re.IGNORECASE | re.UNICODE,
)

_OPT_IN_RE = re.compile(
    r'^\s*(alta|suscribir(me)?|quiero\s+(recibir|volver\s+a\s+recibir)\s+(los\s+)?mensajes)\s*[.!]*\s*$',
    re.IGNORECASE | re.UNICODE,
)

MENSAJE_CONFIRMACION_BAJA = (
    'Listo ✅ Quedaste fuera de nuestros mensajes masivos y promociones. '
    'Igual podés escribirnos cuando quieras. Si cambiás de opinión, escribí ALTA.'
)
MENSAJE_CONFIRMACION_ALTA = (
    '¡Bienvenido de vuelta! ✅ Volverás a recibir nuestras novedades y promociones.'
)


def es_solicitud_baja(texto: str) -> bool:
    return bool(_OPT_OUT_RE.match((texto or '').strip()))


def es_solicitud_alta(texto: str) -> bool:
    return bool(_OPT_IN_RE.match((texto or '').strip()))


def marcar_opt_out(contacto, motivo: str = 'keyword') -> None:
    if contacto.opt_out:
        return
    contacto.opt_out = True
    contacto.fecha_opt_out = timezone.now()
    contacto.motivo_opt_out = motivo[:30]
    contacto.save(update_fields=['opt_out', 'fecha_opt_out', 'motivo_opt_out'])
    logger.info("Contacto %s dado de baja de masivos (motivo=%s)", contacto.id, motivo)


def marcar_opt_in(contacto) -> None:
    if not contacto.opt_out:
        return
    contacto.opt_out = False
    contacto.fecha_opt_out = None
    contacto.motivo_opt_out = ''
    contacto.save(update_fields=['opt_out', 'fecha_opt_out', 'motivo_opt_out'])
    logger.info("Contacto %s reactivado en masivos (opt-in)", contacto.id)


def marcar_numero_invalido(contacto) -> None:
    if contacto.whatsapp_invalido:
        return
    contacto.whatsapp_invalido = True
    contacto.save(update_fields=['whatsapp_invalido'])
    logger.info("Contacto %s marcado como número inválido en WhatsApp", contacto.id)


def procesar_mensaje_entrante(contacto, texto: str, service, session) -> str:
    """Procesa baja/alta desde un mensaje entrante.

    Devuelve 'baja', 'alta' o '' según lo detectado. Cuando detecta algo,
    marca el contacto y envía la confirmación — el caller debe cortar el
    pipeline del bot para ese mensaje.
    """
    if es_solicitud_baja(texto):
        marcar_opt_out(contacto, motivo='keyword')
        try:
            service.send_text_message(
                session.session_id, contacto.from_number or contacto.contacto_numero,
                MENSAJE_CONFIRMACION_BAJA,
            )
        except Exception:
            logger.exception("No se pudo confirmar la baja al contacto %s", contacto.id)
        return 'baja'

    if contacto.opt_out and es_solicitud_alta(texto):
        marcar_opt_in(contacto)
        try:
            service.send_text_message(
                session.session_id, contacto.from_number or contacto.contacto_numero,
                MENSAJE_CONFIRMACION_ALTA,
            )
        except Exception:
            logger.exception("No se pudo confirmar el alta al contacto %s", contacto.id)
        return 'alta'

    return ''
