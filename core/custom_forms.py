import os
import random

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.forms.widgets import DateTimeBaseInput
from django.utils.safestring import mark_safe
from .funciones_adicionales import customgetattr


class NormalModel(models.Model):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for x in self._meta.fields:
            f = x.name
            if isinstance(self._meta.get_field(f), models.BooleanField):
                is_true = customgetattr(self, f)
                t = 'fa-check-circle text-success' if is_true else 'fa-times-circle text-secondary'
                setattr(self, '%s_boolhtml' % f, mark_safe('<i class="fas ' + t + '"></i>'))
                t = "HABILITADO" if is_true else "DESHABILITADO"
                setattr(self, '%s_texthtml' % f, t)
                t = "Sí" if is_true else "No"
                setattr(self, '%s_yesorno' % f, t)
            if isinstance(self._meta.get_field(f), models.DecimalField):
                t = customgetattr(self, f)
                if t != None:
                    setattr(self, '%s_unlocalize' % f, str(t).replace(',', '.'))
                    setattr(self, '%s_money' % f, "{}{}".format(SIMBOLO_MONEDA, str(t).replace(',', '.')))
                    t = int(float(customgetattr(self, f)))
                    setattr(self, '%s_integer' % f, t)

    class Meta:
        abstract = True


class FormError(Exception):
    def __init__(self, form):
        super().__init__("Error en el formulario")
        if isinstance(form, list) or isinstance(form, tuple):
            self.errors = []
            for x in form:
                for k, v in x.errors.items():
                    self.errors.append({k: v[0]})
        else:
            self.errors = [{k: v[0]} for k, v in form.errors.items()]
        self.dict_error = {
            'error': True,
            "form": self.errors,
            "message": "Los datos enviados son inconsistentes"
        }


class CustomDateInput(DateTimeBaseInput):
    def format_value(self, value):
        return str(value or '')


class FormModeloBase(forms.Form):

    class Media:
        css = {
            'all': ('/static/assets/plugins/switchery/switchery.min.css', )
        }
        js = (
            '/static/assets/plugins/switchery/switchery.min.js',
            '/static/js/renderSwicheryControl.js',
            # '/static/js/forms.js?v=11',
            # '/static/panel/js/inline_forms.js?v=2',
        )

    def __init__(self, *args, **kwargs):
        self.ver = kwargs.pop('ver') if 'ver' in kwargs else False
        # self.editando = 'instance' in kwargs
        self.instancia = kwargs.pop('instancia', None)
        no_requeridos = kwargs.pop('no_requeridos') if 'no_requeridos' in kwargs else []
        requeridos = kwargs.pop('requeridos') if 'requeridos' in kwargs else []
        # if self.editando:
        no_switchery = kwargs.pop('no_switchery', [])#listado d campos BooleanField que no quieran q se dibujen con switchery en el form
        #     self.instancia = kwargs['instance']
        super(FormModeloBase, self).__init__(*args, **kwargs)
        for nr in no_requeridos:
            self.fields[nr].required = False
        for r in requeridos:
            self.fields[r].required = True
        for k, v in self.fields.items():
            field = self.fields[k]
            if isinstance(field, forms.TimeField):
                attrs_ = self.fields[k].widget.attrs
                self.fields[k].widget = CustomDateInput(attrs={'type': 'time'})
                self.fields[k].widget.attrs = attrs_
            if isinstance(field, forms.DateField):
                attrs_ = self.fields[k].widget.attrs
                self.fields[k].widget = CustomDateInput(attrs={'type': 'date'})
                self.fields[k].widget.attrs = attrs_
                # self.fields[k].input_formats = ['%d/%m/%Y']
            elif isinstance(field, forms.BooleanField) and not(k in no_switchery):
                self.fields[k].widget.attrs['class'] = "js-switch"
                self.fields[k].widget.attrs['data-render'] = "switchery"
                self.fields[k].widget.attrs['data-theme'] = "default"
            else:
                if 'class' in self.fields[k].widget.attrs:
                    self.fields[k].widget.attrs['class'] += " form-control"
                else:
                    self.fields[k].widget.attrs['class'] = "form-control"
            if not 'col' in self.fields[k].widget.attrs:
                self.fields[k].widget.attrs['col'] = "12"
            if self.fields[k].required and self.fields[k].label:
                self.fields[k].label = mark_safe(self.fields[k].label + '<span style="color:red;margin-left:2px;"><strong>*</strong></span>')
            self.fields[k].widget.attrs['data-nameinput'] = k
            if self.ver:
                self.fields[k].widget.attrs['readonly'] = "readonly"


class CheckboxSelectMultipleCustom(forms.CheckboxSelectMultiple):
    def render(self, *args, **kwargs):
        output = super(CheckboxSelectMultipleCustom, self).render(*args, **kwargs)
        return mark_safe(output.replace(u'<ul>', u'<div class="custom-multiselect" style="width: 600px;overflow: scroll"><ul>').replace(u'</ul>', u'</ul></div>').replace(u'<li>', u'').replace(u'</li>', u'').replace(u'<label', u'<div style="width: 900px"><li').replace(u'</label>', u'</li></div>'))


class ExtFileField(forms.FileField):
    """
    * max_upload_size - a number indicating the maximum file size allowed for upload.
            500Kb - 524288
            1MB - 1048576
            2.5MB - 2621440
            5MB - 5242880
            10MB - 10485760
            20MB - 20971520
            50MB - 5242880
            100MB 104857600
            250MB - 214958080
            500MB - 429916160
    t = ExtFileField(ext_whitelist=(".pdf", ".txt"), max_upload_size=)
    """

    def __init__(self, *args, **kwargs):
        ext_whitelist = kwargs.pop("ext_whitelist")
        self.ext_whitelist = [i.lower() for i in ext_whitelist]
        self.max_upload_size = kwargs.pop("max_upload_size")
        super(ExtFileField, self).__init__(*args, **kwargs)

    def clean(self, *args, **kwargs):
        upload = super(ExtFileField, self).clean(*args, **kwargs)
        if upload:
            size = upload.size
            filename = upload.name
            ext = os.path.splitext(filename)[1]
            ext = ext.lower()
            if size == 0 or ext not in self.ext_whitelist or size > self.max_upload_size:
                raise forms.ValidationError("Tipo de fichero o tamanno no permitido!")


def deshabilitar_campo(form, campo):
    form.fields[campo].widget.attrs['readonly'] = True
    form.fields[campo].widget.attrs['disabled'] = True


def habilitar_campo(form, campo):
    form.fields[campo].widget.attrs['readonly'] = False
    form.fields[campo].widget.attrs['disabled'] = False


def campo_modolectura(form, campo, valor):
    form.fields[campo].widget.attrs['readonly'] = valor


def campo_modobloqueo(form, campo, valor):
    form.fields[campo].widget.attrs['disabled'] = valor