from core.custom_models import ModelFormBase
from crm.models import PerfilNegocioIA, ActividadEconomica, Industria, ProductoIA, ServicioIA, RespuestaEntrenadaIA


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
        self.fields['industria'].widget.attrs['data-urladd'] = "/crm/industria/?action=addnew"
        self.fields['actividad'].queryset = ActividadEconomica.objects.filter(status=True)
        self.fields['actividad'].widget.attrs['data-urladd'] = "/crm/industria/?action=addnew"
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
            if k in ('industria',):
                self.fields[k].widget.attrs['class'] = 'form-control select2'
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


