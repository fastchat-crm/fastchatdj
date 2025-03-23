from django.db import models
from core.custom_models import ModeloBase
from autenticacion.models import Usuario

class VisitaEntorno(ModeloBase):
    user = models.ForeignKey(Usuario, on_delete=models.PROTECT, null=True, blank=True, verbose_name='Usuario')
    dispositivo = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Dispositivo')
    ip = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Ip')
    fecha_visita = models.DateField(auto_now_add=True)
    hora_visita = models.TimeField(auto_now=True)