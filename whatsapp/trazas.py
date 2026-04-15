"""Helper para registrar trazas del pipeline IA sin romper el flujo del webhook.
Todas las funciones capturan excepciones silenciosamente: si el logging falla,
no debe afectar la entrega del mensaje al usuario.
"""
import json
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)


def notificar_superusers_error(titulo: str, cuerpo: str, url: str,
                               cache_key: str, cooldown_segundos: int = 900) -> bool:
    # Retorna True si notificó. Throttle por cache_key para no repetir la misma alerta cada mensaje.
    try:
        if cache_key and cache.get(cache_key):
            return False
        from django.contrib.auth import get_user_model
        from core.funciones import notificacion
        User = get_user_model()
        superusers = User.objects.filter(is_superuser=True, is_active=True)
        for su in superusers:
            try:
                notificacion(
                    titulo=titulo, cuerpo=cuerpo, destinatario=su,
                    url=url, prioridad=1, tipo=4,
                )
            except Exception:
                logger.exception("No se pudo notificar al superuser %s", getattr(su, 'id', '?'))
        if cache_key:
            cache.set(cache_key, 1, timeout=cooldown_segundos)
        return True
    except Exception:
        logger.exception("Error notificando a superusers")
        return False


def fallback_permitido(conversacion_id, cooldown_segundos: int = 300) -> bool:
    # True si el mensaje fallback al cliente todavía no se envió en la ventana. Evita spam.
    if not conversacion_id:
        return True
    key = f'ia_fallback_conv_{conversacion_id}'
    try:
        if cache.get(key):
            return False
        cache.set(key, 1, timeout=cooldown_segundos)
        return True
    except Exception:
        return True


def registrar(
    etapa,
    sesion=None,
    conversacion=None,
    mensaje=None,
    numero=None,
    nivel='info',
    detalle=None,
    latencia_ms=None,
):
    """Inserta una fila en TrazaMensajeIA. Silencia cualquier error para no
    interrumpir el flujo principal.

    Args:
        etapa: uno de ETAPAS_TRAZA (ver whatsapp/models.py).
        sesion: SesionWhatsApp | None
        conversacion: ConversacionWhatsApp | None
        mensaje: MensajeWhatsApp | None (mensaje entrante del cliente)
        numero: str — número del contacto (fallback si no hay relaciones)
        nivel: 'info' | 'success' | 'warning' | 'error'
        detalle: str | dict | None — se serializa a JSON si es dict
        latencia_ms: int | None
    """
    try:
        from whatsapp.models import TrazaMensajeIA
        if isinstance(detalle, (dict, list)):
            try:
                detalle = json.dumps(detalle, ensure_ascii=False, default=str)[:8000]
            except Exception:
                detalle = str(detalle)[:8000]
        elif detalle is not None:
            detalle = str(detalle)[:8000]
        TrazaMensajeIA.objects.create(
            etapa=etapa,
            sesion=sesion,
            conversacion=conversacion,
            mensaje=mensaje,
            numero=(numero or (conversacion and getattr(conversacion.contacto, 'from_number', None)) or None),
            nivel=nivel,
            detalle=detalle,
            latencia_ms=latencia_ms,
        )
    except Exception:
        logger.exception("Error registrando traza (etapa=%s)", etapa)
