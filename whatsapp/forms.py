from django import forms
from core.custom_models import ModelFormBase
from .models import SesionWhatsApp

class SesionWhatsAppForm(ModelFormBase):
    class Meta:
        model = SesionWhatsApp
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        super(SesionWhatsAppForm, self).__init__(*args, **kwargs)

    def clean_numero(self):
        numero = self.cleaned_data['numero']
        id = self.instance.id if self.instance else 0
        if SesionWhatsApp.objects.filter(status=True, numero__iexact=numero).exclude(id=id).exists():
            raise forms.ValidationError("Ya existe una sesión con este número.")
        return numero
