"""Signals de la app whatsapp.

- Autocrear ConfigBaileys cuando una sesion queda con proveedor='baileys'.
  Garantiza que codigo que accede sesion.config_baileys nunca levanta
  DoesNotExist.
- Inscripción automática en secuencias drip al asignarse la etiqueta
  disparadora a un contacto (cubre form, inbox, import masivo y API bulk).
"""
import logging

from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from .models import Contacto, SesionWhatsApp, ConfigBaileys

logger = logging.getLogger(__name__)


@receiver(post_save, sender=SesionWhatsApp)
def _autocrear_config_baileys(sender, instance, created, **kwargs):
    if instance.proveedor != 'baileys':
        return
    if ConfigBaileys.objects.filter(sesion=instance).exists():
        return
    ConfigBaileys.objects.create(sesion=instance)


@receiver(m2m_changed, sender=Contacto.etiquetas.through)
def _inscribir_secuencias_por_etiqueta(sender, instance, action, pk_set, **kwargs):
    if action != 'post_add' or not pk_set:
        return
    try:
        from .funciones_secuencias import inscribir_por_etiqueta
        inscribir_por_etiqueta(instance, pk_set)
    except Exception:
        logger.exception('Inscripción por etiqueta falló para contacto %s', instance.pk)
