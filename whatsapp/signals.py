"""Signals de la app whatsapp.

- Autocrear ConfigBaileys cuando una sesion queda con proveedor='baileys'.
  Garantiza que codigo que accede sesion.config_baileys nunca levanta
  DoesNotExist.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import SesionWhatsApp, ConfigBaileys


@receiver(post_save, sender=SesionWhatsApp)
def _autocrear_config_baileys(sender, instance, created, **kwargs):
    if instance.proveedor != 'baileys':
        return
    if ConfigBaileys.objects.filter(sesion=instance).exists():
        return
    ConfigBaileys.objects.create(sesion=instance)
