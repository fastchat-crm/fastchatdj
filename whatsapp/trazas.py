"""Helper para registrar trazas del pipeline IA sin romper el flujo del webhook.
Todas las funciones capturan excepciones silenciosamente: si el logging falla,
no debe afectar la entrega del mensaje al usuario.
"""
import json
import logging

logger = logging.getLogger(__name__)


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
