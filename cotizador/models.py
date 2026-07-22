"""
Modelo de datos parametrizable del cotizador médico (Vida Buena / MGA).

Todo lo tarifario y de coberturas vive en BD y se administra desde el panel —
nada fijo en código. El motor tarifario (motor_tarifario.py) consulta estas
tablas. La carga inicial se hace con el comando `import_excel_vidabuena` desde
`PLANES INDIVIDUALES VIDA SANA 2026.xlsx`.

Multi-tenant: cada `Plan` pertenece a un `PerfilNegocioIA` (empresa/aseguradora),
para poder escalar a otras aseguradoras sobre el mismo motor.
"""
from django.db import models

from core.custom_models import ModeloBase
from crm.models import PerfilNegocioIA


GENERO_CHOICES = (
    ('M', 'Masculino'),
    ('F', 'Femenino'),
)

VARIANTE_DENTAL_CHOICES = (
    ('basico', 'Dental Básico'),
    ('plus', 'Dental Plus'),
)

MODALIDAD_CHOICES = (
    ('mixta', 'Mixta'),
    ('cerrada', 'Cerrada'),
)

TIPO_COBERTURA_CHOICES = (
    ('anual', 'Anual'),
    ('por_incapacidad', 'Por incapacidad'),
)


class VigenciaTarifaria(ModeloBase):
    """Versionamiento de tarifas/condiciones. Solo una activa por empresa."""
    empresa = models.ForeignKey(
        PerfilNegocioIA, on_delete=models.CASCADE, related_name='vigencias_cotizador'
    )
    nombre = models.CharField(max_length=120, help_text='Ej: Tarifario 2026')
    fecha_inicio = models.DateField(blank=True, null=True)
    fecha_fin = models.DateField(blank=True, null=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Vigencia tarifaria'
        verbose_name_plural = 'Vigencias tarifarias'
        ordering = ['-fecha_inicio', '-id']

    def __str__(self):
        return f'{self.nombre} ({"activa" if self.activa else "inactiva"})'


class RangoEtario(ModeloBase):
    """Rangos de edad del tarifario: (0-5), (5-10), ... (70-100)."""
    empresa = models.ForeignKey(
        PerfilNegocioIA, on_delete=models.CASCADE, related_name='rangos_etarios_cotizador'
    )
    edad_min = models.PositiveIntegerField()
    edad_max = models.PositiveIntegerField()
    etiqueta = models.CharField(max_length=20, help_text='Ej: (20 - 25)')

    class Meta:
        verbose_name = 'Rango etario'
        verbose_name_plural = 'Rangos etarios'
        ordering = ['edad_min']

    def __str__(self):
        return self.etiqueta

    def contiene(self, edad: int) -> bool:
        """El rango (a - b) cubre edades a <= edad < b (límite superior exclusivo),
        salvo el último tramo que es inclusivo."""
        return self.edad_min <= edad <= self.edad_max


class Plan(ModeloBase):
    """Plan médico comercial (Protección 10.000, Único 10.000, etc.)."""
    empresa = models.ForeignKey(
        PerfilNegocioIA, on_delete=models.CASCADE, related_name='planes_cotizador'
    )
    nombre_comercial = models.CharField(max_length=120)
    codigo = models.CharField(max_length=40, blank=True, null=True, help_text='Ej: MAGNO_30000')
    suma_asegurada = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    modalidad = models.CharField(max_length=10, choices=MODALIDAD_CHOICES, blank=True, null=True)
    tipo_cobertura = models.CharField(max_length=20, choices=TIPO_COBERTURA_CHOICES, blank=True, null=True)
    nivel_referencia = models.CharField(max_length=10, blank=True, null=True, help_text='N-1 .. N-4')
    deducible_anual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cobertura_territorial = models.CharField(max_length=120, blank=True, null=True)
    periodo_presentacion_dias = models.PositiveIntegerField(blank=True, null=True)
    diferenciadores_comerciales = models.TextField(blank=True, null=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Plan médico'
        verbose_name_plural = 'Planes médicos'
        ordering = ['orden', 'nombre_comercial']

    def __str__(self):
        return self.nombre_comercial


class Tarifa(ModeloBase):
    """Prima mensual por (plan, rango etario, género, variante dental, vigencia).

    Es la tabla núcleo del motor tarifario.
    """
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='tarifas')
    vigencia = models.ForeignKey(VigenciaTarifaria, on_delete=models.CASCADE, related_name='tarifas')
    rango_etario = models.ForeignKey(RangoEtario, on_delete=models.CASCADE, related_name='tarifas')
    genero = models.CharField(max_length=1, choices=GENERO_CHOICES)
    variante_dental = models.CharField(max_length=10, choices=VARIANTE_DENTAL_CHOICES)
    prima_mensual = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'Tarifa'
        verbose_name_plural = 'Tarifas'
        ordering = ['plan', 'rango_etario', 'genero', 'variante_dental']
        indexes = [
            models.Index(fields=['plan', 'rango_etario', 'genero', 'variante_dental', 'vigencia']),
        ]

    def __str__(self):
        return f'{self.plan} · {self.rango_etario} · {self.get_genero_display()} · {self.get_variante_dental_display()} = {self.prima_mensual}'


class Cobertura(ModeloBase):
    """Una fila del cuadro de coberturas para un plan (ambulatoria, hospitalaria,
    maternidad, catastróficas, dental, etc.)."""
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='coberturas')
    categoria = models.CharField(max_length=80, help_text='Ej: Ambulatoria, Hospitalaria, Maternidad')
    concepto = models.CharField(max_length=255)
    valor = models.CharField(max_length=255, blank=True, null=True, help_text='Monto, % o texto')
    condicion = models.TextField(blank=True, null=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Cobertura'
        verbose_name_plural = 'Coberturas'
        ordering = ['plan', 'orden', 'id']

    def __str__(self):
        return f'{self.plan} · {self.categoria}: {self.concepto}'


class Carencia(ModeloBase):
    """Período de carencia por tipo de cobertura."""
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='carencias')
    tipo = models.CharField(max_length=120, help_text='Ambulatoria, maternidad, preexistencias, emergencia…')
    dias = models.PositiveIntegerField()

    class Meta:
        verbose_name = 'Carencia'
        verbose_name_plural = 'Carencias'
        ordering = ['plan', 'tipo']

    def __str__(self):
        return f'{self.plan} · {self.tipo}: {self.dias} días'


class Exclusion(ModeloBase):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='exclusiones')
    descripcion = models.TextField()

    class Meta:
        verbose_name = 'Exclusión'
        verbose_name_plural = 'Exclusiones'

    def __str__(self):
        return f'{self.plan} · exclusión'


class BeneficioAdicional(ModeloBase):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='beneficios')
    descripcion = models.TextField()

    class Meta:
        verbose_name = 'Beneficio adicional'
        verbose_name_plural = 'Beneficios adicionales'

    def __str__(self):
        return f'{self.plan} · beneficio'


class ProcedimientoDental(ModeloBase):
    """Procedimiento de la red dental (básica o plus) con su copago."""
    empresa = models.ForeignKey(
        PerfilNegocioIA, on_delete=models.CASCADE, related_name='procedimientos_dentales_cotizador'
    )
    variante = models.CharField(max_length=10, choices=VARIANTE_DENTAL_CHOICES)
    servicio = models.CharField(max_length=120, blank=True, null=True, help_text='Categoría: prevención, restauraciones…')
    procedimiento = models.CharField(max_length=255)
    copago = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text='Null = sin copago')

    class Meta:
        verbose_name = 'Procedimiento dental'
        verbose_name_plural = 'Procedimientos dentales'
        ordering = ['variante', 'servicio', 'procedimiento']

    def __str__(self):
        return f'[{self.get_variante_display()}] {self.procedimiento}'
