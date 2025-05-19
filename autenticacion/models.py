import sys
from datetime import datetime
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q, Sum, F
from core.custom_models import ModeloBase
from core.funciones_adicionales import remover_espacios_de_mas, round_num_dec
from core.models_utils import FileNameUploadToPath
from core.validadores import solo_numeros, validate_file_size_2mb
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as trad
from hashlib import md5


class Usuario(AbstractUser, ModeloBase):
    TIPO_DOCUMENTO = (
        ("C", "Cédula"),
        ("R", "RUC"),
        ("P", "Pasaporte"),
        ("N", "Ninguno"),
    )
    SEXO = (
        ("MASCULINO", "Masculino"),
        ("FEMENINO", "Femenino"),
        ("NINGUNO", "Sin definir"),
    )
    razonsocial = models.CharField(max_length=100, default='', blank=True, null=True, verbose_name='Razón Social')
    email = models.EmailField(trad('email address'), unique=False)
    foto = models.FileField(upload_to=FileNameUploadToPath('fotousuario/', "foto_perfil", ["username"]), max_length=600, blank=True, null=True, verbose_name="Foto", validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', "jfif", "svg"]), validate_file_size_2mb])
    sexo = models.CharField(verbose_name="Sexo", max_length=50, choices=SEXO, null=True, blank=True)
    fecha_nacimiento = models.DateField("Fecha de nacimiento", null=True, blank=True)
    telefono = models.CharField(max_length=30, null=True, blank=True, verbose_name='Teléfonos', validators=[solo_numeros])
    tipo_documento = models.CharField(verbose_name="Tipo Documento", max_length=50, choices=TIPO_DOCUMENTO, default="NINGUNO")
    documento = models.CharField(max_length=20, null=True, blank=True, verbose_name='Cédula/RUC/Pasaporte', validators=[solo_numeros])
    ciudad = models.ForeignKey('area_geografica.Ciudad', on_delete=models.PROTECT, blank=True, null=True, verbose_name='Ciudad')
    direccion = models.TextField(verbose_name='Dirección')
    telcelular = models.CharField(max_length=30, verbose_name='# Teléfono Móvil', null=True, blank=True)
    telfijo = models.CharField(max_length=30, verbose_name='# Teléfono Fijo', null=True, blank=True)
    cambio_clave = models.BooleanField(default=False, verbose_name='Cambio de Contraseña Obligatorio')
    # CONFIGURACIÓN DE USUARIO
    notificar_por_correo = models.BooleanField(default=True, verbose_name='Recibe notificaciones por correo')
    # empresa = models.ForeignKey('seguridad.Empresa', on_delete=models.PROTECT, blank=True, null=True, verbose_name='Empresa')

    # TIPO_DOCUMENTO
    CEDULA = "C"
    RUC = "R"
    PASAPORTE = "P"

    def full_name(self):
        return "{} {}".format(self.first_name, self.last_name).title()

    def nacimiento_str(self):
        return str(self.fecha_nacimiento)

    def anios_actual(self):
        anio_actual = datetime.now().year
        anio_nacimiento = self.fecha_nacimiento.year if self.fecha_nacimiento else 0
        return anio_actual - anio_nacimiento

    def primernombre(self):
        return self.first_name.split()[0].lower().capitalize()

    def es_cumple(self):
        hoy = datetime.now()
        fn = self.fecha_nacimiento
        if fn:
            return fn and fn.month == hoy.month and fn.day == hoy.day
        return False

    def get_nombre(self):
        return "{} - {}".format(self.username, self.get_full_name().title(), self.documento if self else "")

    def usuario_activo(self):
        if self.is_active:
            return "fas fa-check-circle text-success"
        else:
            return "fas fa-times-circle text-danger"

    def groups_str(self):
        return ", ".join(list(self.groups.all().values_list('name', flat=True)))

    def nombre_corto(self):
        import re
        fn = re.sub("\s+", " ", self.first_name.strip()).split(" ")
        ln = re.sub("\s+", " ", self.last_name.strip()).split(" ")
        return "{} {}".format(fn[0], ln[0]).title()

    def get_foto(self):
        if self.foto:
            return self.foto.url
        else:
            return "/static/foto_defaultd.png"

    def get_foto_gris(self):
        try:
            if self.foto == '':
                inicial = self.first_name[0]
                if inicial and not inicial.isdigit():
                    return f"/static/images/initials/gris/{inicial}.png"
                return "/static/foto_defaultd.png"
            return self.foto.url
        except Exception:
            return "/static/foto_defaultd.png"

    def datos(self):
        return "{} {}".format(self.first_name, self.last_name).title()

    def save(self, *args, **kwargs):
        self.first_name = remover_espacios_de_mas(self.first_name).title()
        self.last_name = remover_espacios_de_mas(self.last_name).title()
        super(Usuario, self).save(*args, **kwargs)

    def es_administrativo(self):
        return self.perfiladministrativo_set.filter(status=True).exists()

    def es_persona(self):
        return self.perfilpersona_set.filter(status=True).exists()

    def get_perfil_adm(self):
        return self.perfiladministrativo_set.filter(status=True).first()

    def get_perfil_per(self):
        return self.perfilpersona_set.filter(status=True).first()

    def get_admin(self):
        admin= self.perfiladministrativo_set.first()
        if not admin:
            admin = PerfilAdministrativo.objects.create(usuario=self)
        return admin

    def get_client(self, activo=True):
        from django.contrib.auth.models import Group
        cliente = self.perfilpersona_set.first()
        if not cliente:
            cliente = PerfilPersona.objects.create(usuario=self)
        group = Group.objects.get(name='Cliente')
        if activo and not self.groups.filter(name='Cliente').exists():
            self.groups.add(group)
        elif self.groups.filter(name='Cliente').exists() :
            self.groups.remove(group)
        return cliente

    def __str__(self):
        return "{} {} {}".format(self.documento, self.last_name, self.first_name).title()

    def telefono_formateado(self):
        if self.ciudad:
            telf = f'+{self.ciudad.provincia.pais.codigotelefono} {self.telefono}'
        else:
            telf = f'{self.telefono}'
        return telf

    class Meta:
        verbose_name = 'Perfil'
        verbose_name_plural = "Perfiles"
        ordering = ('id',)


class PerfilPersona(ModeloBase):
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, blank=True, null=True, verbose_name='Usuario')

    def __str__(self):
        return "{}".format(self.usuario.__str__())

    class Meta:
        verbose_name = 'Perfil Persona'
        verbose_name_plural = 'Perfil Personas'
        constraints = [
            models.UniqueConstraint(fields=['usuario'],
                                    name='autenticacion_PerfilPersona_usuario_unique',
                                    condition=Q(usuario__isnull=False) & Q(status=True)),
        ]

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        super(PerfilPersona, self).save(force_insert, force_update, using)


class PerfilAdministrativo(ModeloBase):
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, verbose_name='Usuario')
    idtelegram = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return "{}".format(self.usuario.__str__())

    class Meta:
        verbose_name = 'Perfil Administrativo'
        verbose_name_plural = 'Perfil Administrativo'

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        super(PerfilAdministrativo, self).save(force_insert, force_update, using)


