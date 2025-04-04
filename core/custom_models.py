from datetime import datetime

from django import forms
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Value
from django.forms.widgets import DateTimeBaseInput
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django_select2.forms import ModelSelect2Widget, Select2Widget, Select2MultipleWidget, ModelSelect2MultipleWidget
from for_django_projects.form_utils.forms import BetterForm, BetterModelForm

from core.constantes import SIMBOLO_MONEDA
from core.funciones_adicionales import customgetattr
from fastchatdj.settings import AUTH_USER_MODEL


class CustomValueDb(Value):
    def __init__(self, value):
        from django.db.models import IntegerField, CharField, FloatField, DecimalField, BooleanField
        output_field = None
        type_value = type(value).__name__.lower()
        if "int" in type_value:
            output_field = IntegerField()
        if "str" in type_value:
            output_field = CharField()
        if "float" in type_value:
            output_field = FloatField()
        if "decimal" in type_value:
            output_field = DecimalField()
        if "bool" in type_value:
            output_field = BooleanField()
        super().__init__(value, output_field=output_field)


class NormalModel(models.Model):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for x in self._meta.fields:
            f = x.name
            if isinstance(self._meta.get_field(f), models.BooleanField):
                is_true = customgetattr(self, f)
                if is_true == None:
                    t = 'fas fa-clock text-info'
                else:
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
            if isinstance(self._meta.get_field(f), models.FileField):
                file = getattr(self, f)
                if file:
                    archivo_icon = '<i class="far fa-file"></i>'
                    extension = str(file.name.split('.')[-1]).lower()
                    if extension in ('svg', 'jpg', 'jpeg', 'png', 'tiff', "jfif", 'gif', 'bmp'):
                        archivo_icon = '<i class="far fa-file-image"></i>'
                    elif extension in ('doc', 'docx'):
                        archivo_icon = '<i class="far fa-file-word"></i>'
                    elif extension in ('xls', 'xlsx'):
                        archivo_icon = '<i class="far fa-file-excel"></i>'
                    elif extension in ('csv', ):
                        archivo_icon = '<i class="fas fa-file-csv"></i>'
                    elif extension in ('pptx', 'pptm', 'ppt'):
                        archivo_icon = '<i class="far fa-file-powerpoint"></i>'
                    elif extension in ('pdf',):
                        archivo_icon = '<i class="far fa-file-pdf"></i>'
                    elif extension in ('c', 'cpp', 'cxx', 'class','cmd', 'bat', 'html', 'css', 'js', 'sh'):
                        archivo_icon = '<i class="far fa-file-code"></i>'

                    setattr(self, '%s_a_tag' % f, mark_safe(
                        '<a target="_blank" href="{}">{} descargar</a>'.format(file.url, archivo_icon)
                    ))
                    setattr(self, '%s_icon' % f, mark_safe(archivo_icon))
                    setattr(self, '%s_is_image' % f, extension in ('svg', 'jpg', 'jpeg', 'png', 'tiff', "jfif", 'gif', 'bmp'))

    def get_registros_auditoria(self):
        from django.contrib.contenttypes.models import ContentType
        from seguridad.models import AudiUsuarioTabla
        return AudiUsuarioTabla.objects.filter(
            content_type__id=ContentType.objects.get_for_model(self).id,
            object_id=self.id
        )

    class Meta:
        abstract = True


class ModeloBase(NormalModel):
    usuario_creacion = models.ForeignKey(AUTH_USER_MODEL, on_delete=models.CASCADE, blank=True, null=True, related_name='+')
    fecha_registro = models.DateTimeField(verbose_name="Fecha de Registro", auto_now_add=True, editable=False)
    usuario_modificacion = models.ForeignKey(AUTH_USER_MODEL, on_delete=models.CASCADE, blank=True, null=True, related_name='+')
    fecha_modificacion = models.DateTimeField(verbose_name="Fecha de Registro", blank=True, null=True, editable=False)
    status = models.BooleanField(default=True, editable=False)

    def fecha_hora_registro(self):
        return self.fecha_registro

    def save(self, *args, **kwargs):
        usuario = None
        if len(args):
            if args[0]:
                try:
                    if args[0].user.is_authenticated:
                        usuario = args[0].user.id
                except Exception as ex:
                    pass

        if self.pk:
            self.fecha_modificacion = datetime.now()
            if usuario:
                self.usuario_modificacion_id = usuario
        else:
            if usuario:
                self.usuario_creacion_id = usuario

        # super(ModeloBase, self).save(*args, **kwargs)
        models.Model.save(self)

    class Meta:
        abstract = True


class MySelect2Widget(ModelSelect2Widget):
    search_fields = []

    def __init__(self, searchs=None, *args, **kwargs):
        self.search_fields = searchs
        super().__init__(*args, **kwargs)

class MySelect2MultipleWidget(ModelSelect2MultipleWidget):
    search_fields = []

    def __init__(self, searchs=None, *args, **kwargs):
        self.search_fields = searchs
        super().__init__(*args, **kwargs)

class FormError(Exception):
    def __init__(self, form, prefix="", sufix=""):
        super().__init__("Error en el formulario")
        if isinstance(form, list) or isinstance(form, tuple):
            self.errors = []
            for x in form:
                for k, v in x.errors.items():
                    self.errors.append({prefix+k+sufix: v[0]})
        else:
            self.errors = [{prefix+k+sufix: v[0]} for k, v in form.errors.items()]
        self.dict_error = {
            'error': True,
            "form": self.errors,
            "message": "Datos incorrectos, revise la información registrada."
        }


class ExecFunctionError(Exception):
    def __init__(self, function, message, **kwargs):
        super().__init__(message)
        function(**kwargs)


class CustomDateInput(DateTimeBaseInput):
    def format_value(self, value):
        return str(value or '')


class FormParent:

    class Media:
        css = {
            'all': ('/static/assets/plugins/switchery/switchery.min.css', )
        }
        js = (
            '/static/assets/plugins/switchery/switchery.min.js',
            '/static/js/renderSwicheryControl.js',
            # '/static/assets/plugins/select2/js/select2.full.min.js',
            # '/static/assets/plugins/select2/js/i18n/es.js',
            # '/static/assets/plugins/dropify/js/dropify.min.js',
            # '/static/js/form-controls-init.js',
            # '/static/js/forms.js?v=11',
            # '/static/panel/js/inline_forms.js?v=2',
        )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        self.ver = kwargs.pop('ver', False)
        customStep = kwargs.pop('customStep', None)
        cantCharsSelect2 = kwargs.pop('cantCharsSelect2', {})
        addDataNameInput = kwargs.pop('addDataNameInput', False)
        select2_req = kwargs.pop('select2_req', [])#listado d campos que deban tener select2 ajax
        no_requeridos = kwargs.pop('no_requeridos', [])#listado d campos que no quieran q sean requeridos en el form
        requeridos = kwargs.pop('requeridos', [])#listado d campos que x defecto son requeridos pero quiere q no lo sean en el form
        campos = kwargs.pop('campos', [])#listado d campos con su widget customizado
        querysets = kwargs.pop('querysets', {})#listado d campos con un queryset filtrado
        no_switchery = kwargs.pop('no_switchery', [])#listado d campos BooleanField que no quieran q se dibujen con switchery en el form
        no_select2 = kwargs.pop('no_select2', [])#listado d campos que no quieran q se renderice con la librería select2
        inlines = kwargs.pop('inlines', [])
        # Solo extrae el booleano de edición aquí, sin tocar `self.instance` aún
        self.editando = bool('instance' in kwargs and kwargs.get("instance") and kwargs.get("instance").id)

        # Llama al constructor padre PRIMERO
        super(FormParent, self).__init__(*args, **kwargs)

        # AHORA puedes usar self.instance de forma segura
        if self.editando:
            self.instancia = self.instance  # Aquí ya existe `self.instance`
        super(FormParent, self).__init__(*args, **kwargs)

        if inlines:
            self.inlines = inlines
            if self.editando and len(args) == 0:
                instancia = self.instance
                if hasattr(self, 'inlines'):
                    for i in range(len(self.inlines)):
                        Formset = self.inlines[i]["formset"]
                        self.inlines[i]["formset"] = Formset(instance=instancia)
        for w in campos:
            self.fields[w['field']] = w['widget']
        if type(no_requeridos).__name__.lower() in ("list", "tuple"):
            for nr in no_requeridos:
                self.fields[nr].required = False
        for r in requeridos:
            self.fields[r].required = True
        for k, v in querysets.items():
            self.fields[k].queryset = v
        if hasattr(self, "Meta"):
            Modelo = self.Meta.model
            nombre_app, nombre_model = Modelo._meta.app_label, Modelo._meta.model_name
        for k, v in self.fields.items():
            field = self.fields[k]
            if isinstance(field.widget, forms.FileInput) and hasattr(self, '_meta') and hasattr(self._meta.model._meta.get_field(k), "validators"):
                extensions = []
                for x in self._meta.model._meta.get_field(k).validators:
                    if isinstance(x, FileExtensionValidator):
                        extensions.append(",".join([f".{ext}" for ext in x.allowed_extensions]))
                if len(extensions) > 0:
                    self.fields[k].widget.attrs["accept"] = ",".join(extensions)
                    self.fields[k].widget.attrs["data-allowed-file-extensions"] = " ".join(extensions).replace(".", "").replace(",", " ")
                if self.editando and getattr(self.instance, k) and hasattr(getattr(self.instance, k), "url"):
                    self.fields[k].widget.attrs["data-default-file"] = getattr(getattr(self.instance, k), "url")
            if no_requeridos == "__all__":
                self.fields[k].required = False
            if isinstance(field, forms.DateField):
                self.fields[k].widget = CustomDateInput()
                self.fields[k].widget.input_type = "date"
            if isinstance(field, forms.TimeField) or isinstance(field.widget, forms.TimeInput):
                self.fields[k].widget.input_type = "time"
            if (isinstance(field, forms.ModelMultipleChoiceField) or isinstance(field, forms.ModelChoiceField)) and not field.widget.is_hidden:
                # TheMySelect2 = MySelect2MultipleWidget if isinstance(field, forms.ModelMultipleChoiceField) else MySelect2Widget
                # TheSelect2 = Select2MultipleWidget if isinstance(field,
                #                                                    forms.ModelMultipleChoiceField) else Select2Widget
                if hasattr(field, 'queryset') and not k in no_select2:
                    self.fields[k].widget.attrs['class'] = "select2"
                    # if hasattr(field.queryset.model, 'status'):
                    #     self.fields[k].queryset = self.fields[k].queryset.filter(status=True)
                    # cantReg = self.fields[k].queryset.count()
                    # if k in select2_req and hasattr(self, "Meta"):
                    #     choices_searchs = customgetattr(Modelo, '{}_choices_searchs'.format(k))
                    #     dependent_fields = {}
                    #     if hasattr(Modelo, '{}_dependent_fields'.format(k)):
                    #         dependent_fields = customgetattr(Modelo, '{}_dependent_fields'.format(k))
                    #     if not isinstance(dependent_fields, dict):
                    #         raise ValueError("La función {} en {}.{} debe ser un diccionario.".format(
                    #             '{}_dependent_fields'.format(k), nombre_app, nombre_model))
                    #     if (isinstance(choices_searchs, list) or isinstance(choices_searchs, tuple)) and len(
                    #             choices_searchs) > 0:
                    #         self.fields[k].widget = TheMySelect2(searchs=choices_searchs,
                    #                                              dependent_fields=dependent_fields,
                    #                                              queryset=self.fields[k].queryset,
                    #                                              choices=field.choices,
                    #                                              attrs={'data-width': '100%', 'data-minimum-input-length': 1, 'data-language': 'es', 'data-ajax--delay': "500", "data-ajax--cache": "false"},
                    #                                              max_results=20)
                    #     else:
                    #         self.fields[k].widget = TheSelect2(choices=field.choices,
                    #                                            attrs={'data-width': '100%', 'data-language': 'es'})
                    # else:
                    #     if hasattr(self, "Meta"):
                    #         if (cantReg <= 20) or not hasattr(Modelo, '{}_choices_searchs'.format(k)):
                    #             self.fields[k].widget = TheSelect2(choices=field.choices, attrs={'data-width': '100%', 'data-language': 'es'})
                    #         elif cantReg > 20 and hasattr(Modelo, '{}_choices_searchs'.format(k)):
                    #             choices_searchs = customgetattr(Modelo, '{}_choices_searchs'.format(k))
                    #             dependent_fields = {}
                    #             if hasattr(Modelo, '{}_dependent_fields'.format(k)):
                    #                 dependent_fields = customgetattr(Modelo, '{}_dependent_fields'.format(k))
                    #             if not isinstance(dependent_fields, dict):
                    #                 raise ValueError("La función {} en {}.{} debe ser un diccionario.".format('{}_dependent_fields'.format(k), nombre_app, nombre_model))
                    #             if (isinstance(choices_searchs, list) or isinstance(choices_searchs, tuple)) and len(choices_searchs) > 0:
                    #                 self.fields[k].widget = TheMySelect2(searchs=choices_searchs,
                    #                                                         dependent_fields=dependent_fields,
                    #                                                      queryset=self.fields[k].queryset,
                    #                                                      choices=field.choices,
                    #                                                      attrs={'data-width': '100%', 'data-minimum-input-length': 1, 'data-language': 'es', 'data-ajax--delay': "500", "data-ajax--cache": "false"}, max_results=20)
                    #             else:
                    #                 raise ValueError("La función {} en {}.{} debe ser una lista o tupla.".format('{}_choices_searchs'.format(k), nombre_app, nombre_model))
                else:
                    self.fields[k].widget.attrs['class'] = "form-control"
            elif isinstance(field, forms.TypedChoiceField):
                if hasattr(field, 'choices'):
                    if len(field.choices) > 10:
                        self.fields[k].widget.attrs['class'] = "select2"
                        # self.fields[k].widget = Select2Widget(choices=field.choices, attrs={'data-width': '100%', 'data-minimum-input-length': 1})
                    else:
                        self.fields[k].widget.attrs['class'] = "form-control"
            elif isinstance(field, forms.MultipleChoiceField):
                if hasattr(field, 'choices'):
                    self.fields[k].widget.attrs['class'] = "select2"
                    # self.fields[k].widget = Select2MultipleWidget(choices=field.choices, attrs={'data-width': '100%', 'data-language': 'es', 'data-minimum-input-length': 1})
            elif isinstance(field, forms.BooleanField) and not(k in no_switchery):
                self.fields[k].widget.attrs['class'] = "js-switch"
                self.fields[k].widget.attrs['data-render'] = "switchery"
                self.fields[k].widget.attrs['data-theme'] = "default"
            elif not isinstance(field, forms.FileField):
                self.fields[k].widget.attrs['class'] = "form-control"
            if isinstance(field.widget, forms.Textarea):
                self.fields[k].widget.attrs['rows'] = "2"
            if self.fields[k].required and self.fields[k].label:
                self.fields[k].label = mark_safe(self.fields[k].label + '<span style="color:red;margin-left:2px;"><strong>*</strong></span>')
            if self.ver:
                self.fields[k].widget.attrs['readonly'] = "readonly"
            if not 'col' in self.fields[k].widget.attrs:
                self.fields[k].widget.attrs['col'] = "12"
            if addDataNameInput:
                self.fields[k].widget.attrs['data-nameinput'] = k

        for f in self.fieldsets:
            step = f.name
            for ff in f.boundfields:
                k = ff.name
                if self.fields[k].required:
                    self.fields[k].widget.attrs['data-parsley-required'] = "true"
                self.fields[k].widget.attrs['data-parsley-group'] = customStep or step
                self.fields[k].widget.attrs['data-parsley-required-message'] = strip_tags("{} es obligatorio".format(
                    self.fields[k].label))


class FormBase(FormParent, BetterForm):
    pass


class ModelFormBase(FormParent, BetterModelForm):

    def is_valid(self):
        is_valid = super(ModelFormBase, self).is_valid()
        form = self
        if hasattr(form, 'inlines'):
            for inline in form.inlines:
                Formset = inline["formset"]
                formset = Formset(self.data, self.files, instance=self.instance if self.editando else None)
                is_valid = is_valid and formset.is_valid()
                errors = {}
                for i in range(len(formset.errors)):
                    e = formset.errors[i]
                    for k, v in e.items():
                        errors['{}-{}-{}'.format(formset.prefix, i, k)] = v
                self.errors.update(
                    errors
                )
        return is_valid

    def save(self, commit=True):

        if self.request:
            if self.instance.pk:
                self.instance.usuario_modificacion = self.request.user
            else:
                self.instance.usuario_creacion = self.request.user

        obj = super(ModelFormBase, self).save(commit=commit)
        if commit:
            obj.save()
            self._save_m2m()  # Guardar relaciones many-to-many si las hay

        form = self
        if hasattr(form, 'inlines'):
            for inline in form.inlines:
                Formset = inline["formset"]
                formset = Formset(self.data, self.files, instance=obj)
                if formset.is_valid():
                    formset.save()
        return obj