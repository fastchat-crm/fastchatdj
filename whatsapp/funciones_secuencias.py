"""Helpers de secuencias drip — inscripción, salida al responder y disparo por etiqueta.

Los usan la vista (`view_secuencias.py`), el signal m2m de etiquetas
(`signals.py`) y el pipeline entrante (`procesar_mensaje.py`). El despacho de
pasos vive en `cron_jobs/ejecutar_secuencias.py`.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


def inscribir_contacto(secuencia, contacto):
    """Inscribe un contacto en la secuencia. Devuelve (inscripcion|None, mensaje).

    No duplica: si ya tiene una inscripción activa en esa secuencia, no crea otra.
    Respeta opt_out y números inválidos (las secuencias son mensajería saliente
    tipo campaña, no transaccional).
    """
    from .models import InscripcionSecuencia
    if not secuencia.activa:
        return None, 'La secuencia está inactiva.'
    if contacto.opt_out:
        return None, 'El contacto está dado de baja (opt-out).'
    if contacto.whatsapp_invalido:
        return None, 'El número del contacto es inválido.'
    primer_paso = secuencia.pasos_activos().first()
    if primer_paso is None:
        return None, 'La secuencia no tiene pasos.'
    ya = InscripcionSecuencia.objects.filter(
        secuencia=secuencia, contacto=contacto, estado='activa', status=True,
    ).exists()
    if ya:
        return None, 'El contacto ya está inscrito en esta secuencia.'
    inscripcion = InscripcionSecuencia.objects.create(
        secuencia=secuencia,
        contacto=contacto,
        estado='activa',
        paso_actual=0,
        proximo_envio=timezone.now() + timedelta(hours=primer_paso.espera_horas),
    )
    logger.info('Contacto %s inscrito en secuencia %s', contacto.id, secuencia.id)
    return inscripcion, 'Contacto inscrito.'


def inscribir_por_etiqueta(contacto, etiqueta_ids):
    """Dispara la inscripción automática al asignarse etiquetas a un contacto.

    Llamado desde el signal m2m_changed de Contacto.etiquetas — cubre todos los
    caminos de asignación (form de contacto, inbox, import masivo, API bulk).
    """
    from .models import SecuenciaWhatsApp
    secuencias = SecuenciaWhatsApp.objects.filter(
        status=True, activa=True, etiqueta_disparadora_id__in=list(etiqueta_ids),
    )
    for secuencia in secuencias:
        try:
            inscribir_contacto(secuencia, contacto)
        except Exception:
            logger.exception(
                'Inscripción automática falló (secuencia %s, contacto %s)',
                secuencia.id, contacto.id,
            )


def cancelar_por_respuesta(contacto):
    """El contacto escribió: cancela sus inscripciones activas en secuencias
    con `salir_al_responder=True`. Un solo UPDATE, seguro de llamar por mensaje."""
    from .models import InscripcionSecuencia
    return InscripcionSecuencia.objects.filter(
        contacto=contacto, estado='activa', status=True,
        secuencia__salir_al_responder=True,
    ).update(estado='cancelada_respuesta', finalizada_en=timezone.now())


def cancelar_manual(inscripcion):
    if inscripcion.estado != 'activa':
        return False
    inscripcion.estado = 'cancelada_manual'
    inscripcion.finalizada_en = timezone.now()
    inscripcion.save()
    return True
