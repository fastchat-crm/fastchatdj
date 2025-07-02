from django import forms
from core.custom_models import ModelFormBase
from crm.models import DepartamentoChatBot
from .models import SesionWhatsApp, Contacto, ConversacionWhatsApp


class SesionWhatsAppForm(ModelFormBase):
    class Meta:
        model = SesionWhatsApp
        fields = ('nombre', 'min_sesion', 'language', 'agente_ia', 'departamentos', 'mensaje_bienvenida', 'mensaje_despedida',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(SesionWhatsAppForm, self).__init__(*args, **kwargs)
        self.fields['departamentos'].queryset = DepartamentoChatBot.objects.filter(status=True).order_by('nombre')
        for k, v in self.fields.items():
            if k in ('mensaje_bienvenida', 'mensaje_despedida',):
                self.fields[k].widget.attrs['rows'] = '10'
                self.fields[k].widget.attrs['class'] = "summernote"
            if k in ('min_sesion',):
                self.fields[k].widget.attrs['col'] = '3'
            if k in ('departamentos','language', 'agente_ia'):
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['class'] = "jselect2"
                self.fields[k].required = False
            if k in ('nombre',):
                self.fields[k].widget.attrs['col'] = '9'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ContactoForm(ModelFormBase):
    class Meta:
        model = Contacto
        fields = ('numero_telefono', 'contacto_nombre', 'contacto_foto')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ContactoForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('contacto_foto',):
                self.fields[k].widget.input_type = 'file'
                self.fields[k].widget.attrs['dropify'] = 'dropify'
                self.fields[k].widget.attrs['accept'] = 'image/*'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class CambiarClasificacionForm(ModelFormBase):
    class Meta:
        model = ConversacionWhatsApp
        fields = ('clasificacion',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(CambiarClasificacionForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('clasificacion',):
                self.fields[k].widget.attrs['class'] = 'jselect2'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class CambiarNombreContactoForm(ModelFormBase):
    class Meta:
        model = Contacto
        fields = ('contacto_nombre',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(CambiarNombreContactoForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'
