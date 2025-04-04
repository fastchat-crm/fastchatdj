import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from area_geografica.models import Pais, Ciudad, Provincia
from autenticacion.models import Usuario, PerfilPersona
from core.custom_models import ModelFormBase, FormBase
from core.validadores import es_cedula, es_ruc, es_pasaporte


class UserForm(ModelFormBase):
    pais = forms.ModelChoiceField(queryset=Pais.objects.filter(status=True).order_by('nombre'), required=False, label="País")
    provincia = forms.ModelChoiceField(queryset=Provincia.objects.filter(status=True), required=False, label="Provincia")

    class Meta:
        model = Usuario
        fields = ('foto', 'last_name', 'first_name',  'tipo_documento', 'documento',
                  'groups', 'email', 'telefono', 'sexo', 'fecha_nacimiento', 'pais', 'provincia', 'ciudad','is_superuser', 'is_staff')
        # widgets = {
            # "password": forms.PasswordInput(),
        # }
        labels = {"groups": "Roles asignados para este usuario","is_superuser": "¿Establecer como superusuario?", 'is_staff': "¿Establecer como Staff?"}

    def __init__(self, *args, **kwargs):
        kwargs['requeridos'] = ('first_name', 'last_name', 'tipo_documento', 'email', 'documento',)
        super(UserForm, self).__init__(*args, **kwargs)
        self.fields['ciudad'].queryset = Ciudad.objects.filter(status=True)
        self.fields["is_superuser"].required = False
        self.fields["is_staff"].required = False

        # if self.editando:
        #     if self.instance.get_perfil_adm():
        #         if self.instance.get_perfil_adm().departamentos.count() > 0:
        #             self.initial['departamentos'] = self.instance.get_perfil_adm().departamentos.all()
        #         if self.instance.get_perfil_adm().cargos.count() > 0:
        #             self.initial['cargos'] = self.instance.get_perfil_adm().cargos.all()
        for k, v in self.fields.items():
            if k in ('documento', 'telefono',):
                self.fields[k].widget.attrs['pattern'] = "\d*"
                self.fields[k].widget.attrs['title'] = "Sólo números"
                self.fields[k].widget.attrs['onKeyPress'] = "return soloNumeros(event)"
        if self.editando:
            usuario = Usuario.objects.get(id=self.instance.id)
            self.fields["foto"].widget.attrs['data-default-file'] = self.instance.foto.url if self.instance.foto else ""
            if usuario.ciudad:
                self.initial["pais"] = usuario.ciudad.provincia.pais
                self.initial["provincia"] = usuario.ciudad.provincia
                self.initial["ciudad"] = usuario.ciudad
            # del self.fields['password']

    # def clean_ciudad(self):
    #     return self.cleaned_data["ciudad"].pk

    def clean_first_name(self):
        first_name = self.cleaned_data['first_name']
        return re.sub("\s+", " ", first_name.strip())

    def clean_last_name(self):
        last_name = self.cleaned_data['last_name']
        return re.sub("\s+", " ", last_name.strip())

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        id = self.instance.id if self.instance else 0
        if not self.editando:
            if Usuario.objects.filter(email__iexact=email).exclude(id=id).exists():
                raise ValidationError("Ya existe un usuario con este correo electrónico")
        return email

    def clean_username(self):
        username = self.cleaned_data['username']
        return username.lower()

    def clean_ciudad(self):
        return self.cleaned_data["ciudad"]

    def clean_documento(self):
        tipo_documento = self.cleaned_data['tipo_documento']
        documento = self.cleaned_data['documento'].strip()
        id = self.instance.id if self.instance else 0
        if tipo_documento == Usuario.CEDULA and not es_cedula(documento):
            raise ValidationError("Cédula no válida")
        elif tipo_documento == Usuario.RUC and not es_ruc(documento):
            raise ValidationError("RUC no válido")
        elif tipo_documento == Usuario.PASAPORTE and not es_pasaporte(documento):
            raise ValidationError("Pasaporte no válido")
        if not self.editando:
            if Usuario.objects.filter(documento__iexact=documento, tipo_documento=tipo_documento, status=True, is_active=True).exclude(id=id).exists():
                raise ValidationError("Documento ya está registrado")
        return documento

    def save(self, **kwargs):
        user = super(UserForm, self).save()
        # if not self.editando:
        #     user.set_password(self.cleaned_data["password"])
        #     user.save()
        user.is_staff = True
        user.save()
        return user


class PersonaForm(ModelFormBase):
    pais = forms.ModelChoiceField(queryset=Pais.objects.filter(status=True).order_by('nombre'), required=False,
                                       label="País")
    provincia = forms.ModelChoiceField(queryset=Provincia.objects.filter(status=True), required=False, label="Provincia")

    class Meta:
        model = Usuario
        fields = ('last_name', 'first_name',  'tipo_documento', 'documento',
                  'email', 'telefono', 'sexo', 'fecha_nacimiento', 'pais', 'provincia', 'ciudad')
        # widgets = {
            # "password": forms.PasswordInput(),
        # }
        # labels = {"groups": "Roles asignados para este usuario"}

    def __init__(self, *args, **kwargs):
        kwargs['requeridos'] = ('first_name', 'last_name', 'tipo_documento', 'email', 'documento',)
        super(PersonaForm, self).__init__(*args, **kwargs)
        # if self.editando:
        #     if self.instance.get_perfil_adm():
        #         if self.instance.get_perfil_adm().departamentos.count() > 0:
        #             self.initial['departamentos'] = self.instance.get_perfil_adm().departamentos.all()
        #         if self.instance.get_perfil_adm().cargos.count() > 0:
        #             self.initial['cargos'] = self.instance.get_perfil_adm().cargos.all()
        for k, v in self.fields.items():
            if k in ('documento', 'telefono',):
                self.fields[k].widget.attrs['pattern'] = "\d*"
                self.fields[k].widget.attrs['title'] = "Sólo números"
                self.fields[k].widget.attrs['onKeyPress'] = "return soloNumeros(event)"
        if self.editando:
            usuario = Usuario.objects.get(id=self.instance.id)
            # self.fields["foto"].widget.attrs['data-default-file'] = self.instance.foto.url if self.instance.foto else ""
            if usuario.ciudad:
                self.initial["pais"] = usuario.ciudad.provincia.pais
                self.initial["provincia"] = usuario.ciudad.provincia
                self.initial["ciudad"] = usuario.ciudad
            # del self.fields['password']

    # def clean_ciudad(self):
    #     return self.cleaned_data["ciudad"].pk

    def clean_first_name(self):
        first_name = self.cleaned_data['first_name']
        return re.sub("\s+", " ", first_name.strip())

    def clean_last_name(self):
        last_name = self.cleaned_data['last_name']
        return re.sub("\s+", " ", last_name.strip())

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        id = self.instance.id if self.instance else 0
        if not self.editando:
            if Usuario.objects.filter(email__iexact=email).exclude(id=id).exists():
                raise ValidationError("Ya existe un usuario con este correo electrónico")
        return email

    def clean_username(self):
        username = self.cleaned_data['username']
        return username.lower()

    def clean_ciudad(self):
        return self.cleaned_data["ciudad"]

    def clean_documento(self):
        tipo_documento = self.cleaned_data['tipo_documento']
        documento = self.cleaned_data['documento'].strip()
        id = self.instance.id if self.instance else 0
        if tipo_documento == Usuario.CEDULA and not es_cedula(documento):
            raise ValidationError("Cédula no válida")
        elif tipo_documento == Usuario.RUC and not es_ruc(documento):
            raise ValidationError("RUC no válido")
        elif tipo_documento == Usuario.PASAPORTE and not es_pasaporte(documento):
            raise ValidationError("Pasaporte no válido")
        if not self.editando:
            if Usuario.objects.filter(documento__iexact=documento, tipo_documento=tipo_documento, status=True, is_active=True).exclude(id=id).exists():
                raise ValidationError("Documento ya está registrado")
        return documento

    def save(self, **kwargs):
        user = super(PersonaForm, self).save()
        # if not self.editando:
        #     user.set_password(self.cleaned_data["password"])
        #     user.save()
        user.is_staff = True
        user.save()
        return user


class GrupoUserForm(ModelFormBase):
    class Meta:
        model = Usuario
        fields = ('groups',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        self.editando = 'instance' in kwargs
        super(GrupoUserForm, self).__init__(*args, **kwargs)
        self.fields['groups'].queryset = self.fields['groups'].queryset.all().order_by('-id')
        for k, v in self.fields.items():
            if k in ('groups',):
                self.fields[k].required = True
                self.fields[k].widget.attrs['class'] = "select2"
            if ver:
                self.fields[k].widget.attrs['disabled'] = 'disabled'


class EditPersonaForm(ModelFormBase):
    pais = forms.ModelChoiceField(label=u"Pais", required=True, queryset=Pais.objects.filter(status=True).order_by('nombre'))
    provincia = forms.ModelChoiceField(label=u"Provincia", required=True, queryset=Provincia.objects.filter(status=True).order_by('nombre'))

    class Meta:
        model = Usuario
        fields = ('first_name', 'last_name', 'fecha_nacimiento', 'email', 'telefono', 'pais', 'provincia', 'ciudad', 'direccion',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        instancia = kwargs["instance"] if 'instance' in kwargs else None
        super(EditPersonaForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            if k in ('direccion',):
                self.fields[k].widget.attrs['col'] = "12"
            else:
                self.fields[k].widget.attrs['col'] = "6"
            if k in ('pais', 'provincia', 'ciudad',):
                self.fields[k].widget.attrs['class'] = "form-control jselect2"
            else:
                self.fields[k].widget.attrs['class'] = "form-control"


class ManageProfileForm(FormBase):
    user_is_active = forms.BooleanField(label="Usuario Activo?", required=False)
    perfil_administrativo = forms.BooleanField(label="Perfil Administrativo Activo?", required=False)
    perfil_cliente = forms.BooleanField(label="Perfil Cliente Activo?", required=False)

