from django import forms

from autenticacion.models import Usuario
from core.custom_forms import FormModeloBase
from core.custom_models import ModelFormBase
from crm.models import PerfilNegocioIA, ActividadEconomica, Industria, ProductoIA, ServicioIA, RespuestaEntrenadaIA, \
    DepartamentoChatBot, AgentesIA, ApiKeyIA


class PerfilNegocioIAForm(ModelFormBase):
    class Meta:
        model = PerfilNegocioIA
        fields = (
            'industria', 'actividad', 'nombre_empresa', 'sitio_web', 'localidad',
            'publico_objetivo', 'descripcion_empresa',
        )

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        self.fields['industria'].queryset = Industria.objects.filter(status=True)
        self.fields['industria'].widget.attrs['data-urladd'] = "/crm/entrenamiento/?action=add_new_industria"
        self.fields['actividad'].queryset = ActividadEconomica.objects.filter(status=True)
        self.fields['actividad'].widget.attrs['data-urladd'] = "/crm/entrenamiento/?action=add_new_actividad"
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].required = True
            if k in ('descripcion_empresa', 'publico_objetivo'):
                self.fields[k].widget.attrs['rows'] = 3
            if k in ('industria', 'actividad'):
                self.fields[k].widget.attrs['class'] = 'form-control select2'
            if k in ('industria', 'actividad', 'nombre_empresa', 'sitio_web', 'localidad'):
                self.fields[k].widget.attrs['col'] = '6'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class IndustriaForm(ModelFormBase):
    class Meta:
        model = Industria
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(IndustriaForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ActividadEconomicaForm(ModelFormBase):
    class Meta:
        model = ActividadEconomica
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ActividadEconomicaForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ProductoIAForm(ModelFormBase):
    class Meta:
        model = ProductoIA
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status', 'perfil')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ProductoIAForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ServicioIAForm(ModelFormBase):
    class Meta:
        model = ServicioIA
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status', 'perfil')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ServicioIAForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class RespuestaEntrenadaIAForm(ModelFormBase):
    class Meta:
        model = RespuestaEntrenadaIA
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status', 'perfil')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(RespuestaEntrenadaIAForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'



class DepartamentoChatBotForm(ModelFormBase):
    class Meta:
        model = DepartamentoChatBot
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(DepartamentoChatBotForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if k in ('nombre',):
                self.fields[k].widget.attrs['col'] = '8'
            elif k in ('color',):
                self.fields[k].widget.attrs['col'] = '4'
                self.fields[k].widget = forms.TextInput(attrs={
                    'type': 'color',
                    'class': 'form-control',
                    'col': '4'
                })

            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class AddPerfilDepartamentoChatBotForm(FormModeloBase):
    usuarios = forms.ModelMultipleChoiceField(label='Personas', queryset=Usuario.objects.filter(status=True))


class AgentesIAForm(ModelFormBase):
    class Meta:
        model = AgentesIA
        fields = ('nombre', 'descripcion','apikey', 'prompt_template', 'anotar_listas')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        self.fields['apikey'].queryset = ApiKeyIA.objects.filter(status=True)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('descripcion',):
                self.fields[k].widget.attrs['col'] = '12'
            if k in ('apikey',):
                self.fields[k].widget.attrs['class'] = 'select2'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ApiKeyIAForm(ModelFormBase):
    class Meta:
        model = ApiKeyIA
        fields = ('alias', 'proveedor', 'descripcion', 'usuario', 'contrasena', 'estado')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '6'
            if k in ('estado'):
                self.fields[k].widget.attrs['class'] = "js-switch"
                self.fields[k].widget.attrs['data-render'] = "switchery"
                self.fields[k].widget.attrs['data-theme'] = "default"
                self.fields[k].widget.attrs['col'] = '3'
            if k in ('descripcion',):
                self.fields[k].widget.attrs['col'] = '12'
            if k in ('proveedor',):
                self.fields[k].widget.attrs['class'] = "form-control jselect"
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'



