"""Emisores de eventos vía señales de Django.

Tres de los eventos se disparan desde varios lugares del código:

    etiqueta_agregada  → 5 sitios distintos hacen `contacto.etiquetas.add(...)`
    cita_creada        → 3 sitios construyen un `Turno`
    registro_creado    → el CRUD genérico de objetos personalizados

Engancharlos uno por uno sería frágil: cualquier sitio nuevo quedaría sin emitir
y nadie lo notaría hasta que una automatización no corriera. Con señales, la
cobertura es automática.

Los eventos que sí tienen un único punto de origen con contexto rico
—`contacto_creado`, `conversacion_finalizada`, `cita_cumplida`,
`oportunidad_ganada`— se disparan explícitamente desde su sitio, porque ahí se
sabe *por qué* pasó (quién cerró, desde qué etapa) y una señal no lo vería.
"""
import logging

from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(m2m_changed, dispatch_uid='automatizacion_etiqueta_contacto')
def etiqueta_agregada(sender, instance, action, pk_set, reverse, **kwargs):
    """Cubre los cinco sitios que etiquetan un contacto."""
    if action != 'post_add' or reverse or not pk_set:
        return

    from whatsapp.models import Contacto
    if not isinstance(instance, Contacto):
        return

    try:
        from whatsapp.models import EtiquetaContacto
        from .models import EVENTO_ETIQUETA_AGREGADA
        from .motor import disparar

        etiquetas = EtiquetaContacto.objects.filter(pk__in=pk_set)
        for etiqueta in etiquetas:
            disparar(EVENTO_ETIQUETA_AGREGADA, {
                'contacto_id': instance.id,
                'contacto_nombre': instance.contacto_nombre or '',
                'numero': instance.contacto_numero or '',
                'canal': instance.canal or '',
                'etiqueta': etiqueta.nombre,
                'etiqueta_id': etiqueta.id,
            })
    except Exception:
        logger.exception('No se pudo emitir etiqueta_agregada para el contacto %s', instance.pk)


@receiver(post_save, dispatch_uid='automatizacion_conversacion_iniciada')
def conversacion_iniciada(sender, instance, created, **kwargs):
    if not created:
        return

    from whatsapp.models import ConversacionWhatsApp
    if not isinstance(instance, ConversacionWhatsApp):
        return

    try:
        from .models import EVENTO_CONVERSACION_INICIADA
        from .motor import disparar
        contacto = instance.contacto
        disparar(EVENTO_CONVERSACION_INICIADA, {
            'conversacion_id': instance.id,
            'contacto_id': instance.contacto_id,
            'contacto_nombre': getattr(contacto, 'contacto_nombre', '') or '',
            'numero': getattr(contacto, 'contacto_numero', '') or '',
            'canal': getattr(contacto, 'canal', '') or '',
            'sesion_id': getattr(getattr(contacto, 'sesion', None), 'id', None),
        })
    except Exception:
        logger.exception('No se pudo emitir conversacion_iniciada para la conversación %s', instance.pk)


@receiver(post_save, dispatch_uid='automatizacion_cita_creada')
def cita_creada(sender, instance, created, **kwargs):
    """Cubre los tres sitios que crean un Turno (manual, reagendado, chatbot)."""
    if not created:
        return

    try:
        from agenda.models import Turno
    except Exception:
        return
    if not isinstance(instance, Turno):
        return

    try:
        from .models import EVENTO_CITA_CREADA
        from .motor import disparar
        disparar(EVENTO_CITA_CREADA, {
            'turno_id': instance.id,
            'contacto_id': getattr(instance, 'contacto_id', None),
            'servicio': str(getattr(instance, 'servicio', '') or ''),
            'recurso': str(getattr(instance, 'recurso', '') or ''),
            'inicio': instance.inicio.isoformat() if getattr(instance, 'inicio', None) else '',
            'origen': getattr(instance, 'origen', '') or '',
            'reagendado': bool(getattr(instance, 'turno_anterior_id', None)),
        })
    except Exception:
        logger.exception('No se pudo emitir cita_creada para el turno %s', instance.pk)


@receiver(post_save, dispatch_uid='automatizacion_registro_creado')
def registro_creado(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        from objetos.models import RegistroPersonalizado
    except Exception:
        return
    if not isinstance(instance, RegistroPersonalizado):
        return

    try:
        from .models import EVENTO_REGISTRO_CREADO
        from .motor import disparar
        # Los valores del registro viajan planos dentro del contexto, así que
        # una condición puede leerlos como `datos.precio`.
        disparar(EVENTO_REGISTRO_CREADO, {
            'registro_id': instance.id,
            'objeto': instance.objeto.nombre_singular,
            'objeto_slug': instance.objeto.slug,
            'titulo': instance.etiqueta_visible(),
            'datos': instance.datos or {},
        })
    except Exception:
        logger.exception('No se pudo emitir registro_creado para el registro %s', instance.pk)
