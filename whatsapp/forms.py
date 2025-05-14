from django import forms
from core.custom_models import ModelFormBase
from .models import SesionWhatsApp

class SesionWhatsAppForm(ModelFormBase):
    class Meta:
        model = SesionWhatsApp
        fields = ('nombre', 'mensaje_bienvenida', 'mensaje_despedida', 'min_sesion')