from django.apps import AppConfig
from django.db.models.signals import post_save


class SeguridadConfig(AppConfig):
    name = 'seguridad'
    verbose_name = "Seguridad"

    def ready(self):
        from django.contrib.auth.models import Group
        from seguridad.signals import create_authgroup
        post_save.connect(create_authgroup, sender=Group)