from django import forms
from core.custom_models import ModelFormBase
from .models import SesionWhatsApp

class SesionWhatsAppForm(ModelFormBase):
    class Meta:
        model = SesionWhatsApp
        fields = ('nombre', 'mensaje_bienvenida', 'mensaje_despedida', 'min_sesion')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(SesionWhatsAppForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if k in ('mensaje_bienvenida', 'mensaje_despedida',):
                self.fields[k].widget.attrs['rows'] = '3'
                self.fields[k].widget.attrs['class'] = "summernote"
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'