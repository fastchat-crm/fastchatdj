"""Detección de growth links en mensajes entrantes.

`procesar_mensaje.py` llama `procesar_growth_link` con cada texto entrante.
Si el texto trae el marcador `(ref: <codigo>)` de un enlace activo y es la
primera vez que ese contacto lo usa, ejecuta las acciones configuradas.
"""
import logging
import re

from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r'\(\s*ref:\s*([a-z0-9\-_]+)\s*\)', re.IGNORECASE)


def procesar_growth_link(contacto, texto):
    """Devuelve el texto de respuesta automática si el enlace corta el pipeline,
    '' si hubo match sin respuesta fija (el pipeline sigue), o None si no aplica."""
    match = _REF_RE.search(texto or '')
    if not match:
        return None
    codigo = match.group(1).lower()
    from .models import EnlaceCrecimiento, UsoEnlaceCrecimiento
    enlace = EnlaceCrecimiento.objects.filter(
        codigo=codigo, status=True, activo=True,
    ).select_related('etiqueta', 'secuencia').first()
    if enlace is None:
        return None

    _, creado = UsoEnlaceCrecimiento.objects.get_or_create(
        enlace=enlace, contacto=contacto,
    )
    if not creado:
        return None

    EnlaceCrecimiento.objects.filter(pk=enlace.pk).update(
        usos=F('usos') + 1, ultimo_uso=timezone.now(),
    )
    logger.info('Growth link %s usado por contacto %s', enlace.codigo, contacto.id)

    if enlace.etiqueta_id:
        try:
            contacto.etiquetas.add(enlace.etiqueta_id)
        except Exception:
            logger.exception('No se pudo aplicar la etiqueta del enlace %s', enlace.codigo)

    if enlace.secuencia_id:
        try:
            from .funciones_secuencias import inscribir_contacto
            inscribir_contacto(enlace.secuencia, contacto)
        except Exception:
            logger.exception('No se pudo inscribir en la secuencia del enlace %s', enlace.codigo)

    return (enlace.mensaje_respuesta or '').strip()
