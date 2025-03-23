from django import forms
from django.core.exceptions import ValidationError

from area_geografica.models import Pais, Provincia, Parroquia, Ciudad, REGION_CHOICES
from core.custom_models import ModelFormBase


class PaisForm(ModelFormBase):
    class Meta:
        model = Pais
        exclude = ( 'usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        super(PaisForm, self).__init__(*args, **kwargs)
        self.fields["nombre_st"].widget = forms.HiddenInput()

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre']
        id = self.instance.id if self.instance else 0
        if Pais.objects.filter(status=True, nombre__iexact=nombre).exclude(id=id).exists():
            raise ValidationError("Ya existe un país con este nombre")
        return nombre


class ProvinciaForm(ModelFormBase):
    class Meta:
        model = Provincia
        exclude = ( 'usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        super(ProvinciaForm, self).__init__(*args, **kwargs)
        self.fields["nombre_st"].widget = forms.HiddenInput()
        for k, v in self.fields.items():
            if k in ('region',):
                self.fields[k].required = True
                self.fields[k].widget.attrs['class'] = "select2"

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre']
        pais = self.cleaned_data['pais']
        id = self.instance.id if self.instance else 0
        qs = Provincia.objects.filter(status=True, nombre__iexact=nombre, pais_id=pais.pk).exclude(id=id)
        if qs.exists():
            raise ValidationError("Ya existe una provincia con este nombre en el país {}".format(pais.nombre))
        return nombre


class CiudadForm(ModelFormBase):
    pais = forms.ModelChoiceField(queryset=Pais.objects.filter(status=True).order_by('nombre'))

    class Meta:
        model = Ciudad
        fields = ('pais', 'provincia', 'nombre', 'nombre_st')

    def __init__(self, *args, **kwargs):
        super(CiudadForm, self).__init__(*args, **kwargs)
        self.fields["nombre_st"].widget = forms.HiddenInput()
        if self.editando:
            self.initial['pais'] = self.instance.provincia.pais

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre']
        provincia = self.cleaned_data['provincia']
        id = self.instance.id if self.instance else 0
        qs = Ciudad.objects.filter(status=True, nombre__iexact=nombre, provincia_id=provincia.pk).exclude(id=id)
        if qs.exists():
            raise ValidationError("Ya existe una ciudad con este nombre en la provincia {}".format(provincia.nombre))
        return nombre


class ParroquiaForm(ModelFormBase):
    pais = forms.ModelChoiceField(queryset=Pais.objects.filter(status=True).order_by('nombre'))
    provincia = forms.ModelChoiceField(queryset=Provincia.objects.filter(status=True).order_by('nombre'))
    class Meta:
        model = Parroquia
        fields = ('pais', 'provincia', 'ciudad', 'nombre', 'nombre_st')


    def __init__(self, *args, **kwargs):
        super(ParroquiaForm, self).__init__(*args, **kwargs)
        self.fields["nombre_st"].widget = forms.HiddenInput()
        if self.editando:
            self.initial['pais'] = self.instance.ciudad.provincia.pais_id
            self.initial['provincia'] = self.instance.ciudad.provincia_id

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre']
        ciudad = self.cleaned_data['ciudad']
        id = self.instance.id if self.instance else 0
        qs = Ciudad.objects.filter(status=True, nombre__iexact=nombre, ciudad_id=ciudad.pk).exclude(id=id)
        if qs.exists():
            raise ValidationError("Ya existe una parroquia con este nombre en la ciudad {}".format(ciudad.nombre))
        return nombre