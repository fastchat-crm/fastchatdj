from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from core.constantes import TIMEZONE_CHOICES, TIMEZONE_CHOICES_LIST
from core.custom_models import ModeloBase


class Pais(ModeloBase):
    codigo = models.CharField(max_length=200, verbose_name='Código', blank=True, null=True)
    nombre = models.CharField(max_length=200, verbose_name='Nombre')
    nombre_st = models.CharField(max_length=200, verbose_name='Nombre sin tilde', blank=True, null=True)
    codigotelefono = models.CharField(max_length=200, blank=True, null=True, verbose_name='Prefijo Teléfono')
    codigoidioma = models.CharField(max_length=200, blank=True, null=True, verbose_name='Código de idioma')
    timezone = models.CharField(choices=TIMEZONE_CHOICES, max_length=200, blank=True, null=True,  verbose_name='Timezone')
    # publicar = models.BooleanField(default=False, verbose_name='Habilitado para registro de usuario')
    # valor_mensual = models.FloatField(default=0, verbose_name='Valor Mensual')
    # valor_anual = models.FloatField(default=0, verbose_name='Valor Anual')
    # currency_code = models.CharField(max_length=500, blank=True, null=True, verbose_name='Codigo Moneda')

    def __str__(self):
        return "{}".format(self.nombre)

    class Meta:
        verbose_name = 'País'
        verbose_name_plural = 'Países'
        ordering = ('nombre',)
        constraints = [
            models.UniqueConstraint(fields=['nombre',], name='pais_nombre_unico', condition=Q(status=True)),
            models.CheckConstraint(check=Q(timezone__in=TIMEZONE_CHOICES_LIST),
                                   name='timezone__in__TIMEZONE_CHOICES'),
        ]

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        if self.nombre:
            self.nombre = self.nombre.upper()
            self.nombre_st = slugify(self.nombre).replace('-', ' ')
        super(Pais, self).save(force_insert, force_update, using)


REGION_CHOICES = (
    (0, 'SIN DEFINIR'),
    (1, 'COSTA'),
    (2, 'SIERRA'),
    (3, 'ORIENTE '),
    (4, 'INSULAR'),
)


class Provincia(ModeloBase):
    codigo = models.CharField(max_length=200, verbose_name='Código', blank=True, null=True)
    pais = models.ForeignKey(Pais, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=200)
    nombre_st = models.CharField(max_length=200, verbose_name='Nombre sin tilde', blank=True, null=True)
    region = models.IntegerField(choices=REGION_CHOICES, default=0, verbose_name='Región')

    def __str__(self):
        return "{}".format(self.nombre)

    @staticmethod
    def pais_choices_searchs():
        return ['nombre__icontains']

    class Meta:
        verbose_name = 'Provincia'
        verbose_name_plural = 'Provincias'
        ordering = ('nombre',)
        constraints = [
            models.UniqueConstraint(fields=['nombre', 'pais_id'], name='provincia_nombre_unico_por_pais', condition=Q(status=True)),
        ]

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        self.nombre = self.nombre.upper()
        self.nombre_st = slugify(self.nombre).replace('-', ' ')
        super(Provincia, self).save(force_insert, force_update, using)


class Ciudad(ModeloBase):
    codigo = models.CharField(max_length=200, verbose_name='Código', blank=True, null=True)
    provincia = models.ForeignKey(Provincia, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=200, verbose_name='Ciudad')
    nombre_st = models.CharField(max_length=200, verbose_name='Nombre sin tilde', blank=True, null=True)
    altura_en_metros = models.FloatField("Altura en metros", default=0)
    lat = models.CharField(max_length=200, default='', blank=True, null=True, verbose_name='Latitud')
    long = models.CharField(max_length=200, default='', blank=True, null=True, verbose_name='Longitud')

    def __str__(self):
        return "{}".format(self.nombre)
        # return "{}, {}, {}".format(self.nombre, self.provincia.nombre, self.provincia.pais.nombre)

    class Meta:
        verbose_name = 'Ciudad'
        verbose_name_plural = 'Ciudades'
        ordering = ('nombre',)

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        self.nombre = self.nombre.upper()
        self.nombre_st = slugify(self.nombre).replace('-', ' ')
        super(Ciudad, self).save(force_insert, force_update, using)

    @staticmethod
    def pais_choices_searchs():
        return ['nombre__icontains']

    @staticmethod
    def provincia_choices_searchs():
        return ['nombre__icontains']

    @staticmethod
    def provincia_dependent_fields():
        return {'pais': 'pais'}


class Parroquia(ModeloBase):
    codigo = models.CharField(max_length=200, verbose_name='Código', blank=True, null=True)
    nombre = models.CharField(max_length=200, verbose_name='Parroquia')
    nombre_st = models.CharField(max_length=200, verbose_name='Nombre sin tilde', blank=True, null=True)
    ciudad = models.ForeignKey(Ciudad, on_delete=models.PROTECT, null=True, blank=True)

    def __str__(self):
        return "{}, {}".format(self.nombre, self.ciudad.nombre)

    class Meta:
        verbose_name = 'Parroquia'
        verbose_name_plural = 'Parroquias'
        ordering = ('nombre',)

    @staticmethod
    def pais_choices_searchs():
        return ['nombre__icontains']

    @staticmethod
    def provincia_choices_searchs():
        return ['nombre__icontains']

    @staticmethod
    def provincia_dependent_fields():
        return {'pais': 'pais'}

    @staticmethod
    def ciudad_choices_searchs():
        return ['nombre__icontains']

    @staticmethod
    def ciudad_dependent_fields():
        return {'provincia__pais': 'pais', 'provincia': 'provincia'}

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        self.nombre = self.nombre.upper()
        self.nombre_st = slugify(self.nombre).replace('-', ' ')
        super(Parroquia, self).save(force_insert, force_update, using)