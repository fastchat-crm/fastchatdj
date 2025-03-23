import re
from datetime import datetime, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db.models import Q

from area_geografica.models import Pais, Ciudad, Provincia
from autenticacion.models import Usuario, PerfilPersona
from core.custom_models import ModelFormBase



class RegistroPersonaForm(ModelFormBase):
    # edad = forms.IntegerField(
    #     label="Edad",
    #     validators=[MinValueValidator(18)]
    # )

    class Meta:
        model = Usuario
        fields = ('email', 'tipo_documento', 'documento', 'first_name', 'last_name', 'fecha_nacimiento', 'ciudad', 'telefono')
        labels = {
            "ciudad": "Ubicación"
        }

    def __init__(self, *args, **kwargs):
        kwargs['requeridos'] = ('email', 'tipo_documento', 'documento', 'first_name', 'last_name', 'fecha_nacimiento', 'ciudad', 'telefono')
        kwargs['no_select2'] = ('ciudad',)
        if len(args) == 0:
            kwargs['querysets'] = {
                "ciudad": Ciudad.objects.none()
            }
        super(RegistroPersonaForm, self).__init__(*args, **kwargs)
        if self.editando:
            usuario = Usuario.objects.get(id=self.instance.id)
            if usuario.ciudad:
                self.prefijoCelular = usuario.ciudad.provincia.pais.codigotelefono or ""
            # if usuario.fecha_nacimiento:
            #     self.initial['edad'] = (datetime.now().date() - usuario.fecha_nacimiento).days // 365

    def clean_first_name(self):
        first_name = self.cleaned_data['first_name']
        return re.sub("\s+", " ", first_name.strip())

    def clean_last_name(self):
        last_name = self.cleaned_data['last_name']
        return re.sub("\s+", " ", last_name.strip())

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        id = self.instance.id if self.instance else 0
        if Usuario.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exclude(id=id).exists():
            raise ValidationError("Ya existe un usuario con este correo electrónico")
        return email

    def save(self, **kwargs):
        user = super(RegistroPersonaForm, self).save()
        if not self.editando:
            user.set_password(self.cleaned_data["documento"])
            user.save()
        if not user.username:
            user.username = self.cleaned_data['documento']
        # edad = self.cleaned_data['edad']
        # user.fecha_nacimiento = datetime.now() - (timedelta(days=edad) * 365)
        user.cambio_clave = False
        user.save()
        PerfilPersona.objects.get_or_create(usuario_id=user.id)
        return user

