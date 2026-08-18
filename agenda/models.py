from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.custom_models import ModeloBase


CURRENCY_CHOICES = (
    ('ARS', 'Peso Argentino (ARS)'),
    ('USD', 'Dólar Estadounidense (USD)'),
    ('EUR', 'Euro (EUR)'),
    ('PEN', 'Sol Peruano (PEN)'),
    ('CLP', 'Peso Chileno (CLP)'),
    ('COP', 'Peso Colombiano (COP)'),
    ('MXN', 'Peso Mexicano (MXN)'),
    ('BRL', 'Real Brasileño (BRL)'),
    ('UYU', 'Peso Uruguayo (UYU)'),
    ('PYG', 'Guaraní Paraguayo (PYG)'),
    ('BOB', 'Boliviano (BOB)'),
    ('VES', 'Bolívar Venezolano (VES)'),
)

WEEKDAY_CHOICES = (
    (0, 'Lunes'),
    (1, 'Martes'),
    (2, 'Miércoles'),
    (3, 'Jueves'),
    (4, 'Viernes'),
    (5, 'Sábado'),
    (6, 'Domingo'),
)

EXCEPTION_TYPE_CHOICES = (
    ('block_day', 'Bloquear día completo'),
    ('block_range', 'Bloquear rango horario'),
    ('add_range', 'Agregar rango extra'),
)

APPOINTMENT_STATUS_CHOICES = (
    ('pending', 'Pendiente'),
    ('confirmed', 'Confirmado'),
    ('cancelled', 'Cancelado'),
    ('rescheduled', 'Reagendado'),
    ('fulfilled', 'Cumplido'),
    ('no_show', 'No asistió'),
)

APPOINTMENT_ORIGIN_CHOICES = (
    ('chatbot', 'Chatbot'),
    ('manual', 'Manual'),
    ('api', 'API'),
)

ACTIVE_STATUSES = ('pending', 'confirmed')


class GrupoAgenda(ModeloBase):
    nombre = models.CharField('Nombre', max_length=120)
    descripcion = models.TextField('Descripción', blank=True, default='')
    moneda = models.CharField('Moneda', max_length=8, choices=CURRENCY_CHOICES, default='USD')
    recordatorio_horas_antes = models.PositiveIntegerField(
        'Horas de anticipación del recordatorio', default=24,
        help_text='Cuántas horas antes del turno se envía el recordatorio.'
    )
    zona_horaria = models.CharField(
        'Zona horaria', max_length=64, default='America/Guayaquil',
        help_text='Nombre TZ database (ej. America/Guayaquil, UTC).'
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='grupos_agenda_responsable',
        verbose_name='Responsable',
        help_text='Usuario que recibe correo y notificación interna al crearse un turno en este grupo.',
    )

    class Meta:
        verbose_name = 'Grupo de agenda'
        verbose_name_plural = 'Grupos de agenda'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Recurso(ModeloBase):
    grupo_agenda = models.ForeignKey(
        GrupoAgenda, on_delete=models.CASCADE, related_name='recursos',
        verbose_name='Grupo de agenda',
    )
    nombre = models.CharField('Nombre', max_length=120)
    descripcion = models.TextField('Descripción', blank=True, default='')
    color = models.CharField('Color', max_length=20, default='#0d6efd')
    orden = models.PositiveIntegerField('Orden', default=0, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='recursos_agenda',
        verbose_name='Usuario vinculado',
        help_text='Usuario opcional asignado a este recurso (ej. asesor).'
    )

    class Meta:
        verbose_name = 'Recurso'
        verbose_name_plural = 'Recursos'
        ordering = ['grupo_agenda', 'orden', 'nombre']

    def __str__(self):
        return f'{self.nombre} ({self.grupo_agenda.nombre})'


class HorarioLaboral(ModeloBase):
    recurso = models.ForeignKey(
        Recurso, on_delete=models.CASCADE, related_name='horarios',
        verbose_name='Recurso',
    )
    dia_semana = models.PositiveSmallIntegerField('Día de la semana', choices=WEEKDAY_CHOICES)
    hora_inicio = models.TimeField('Hora de inicio')
    hora_fin = models.TimeField('Hora de fin')
    duracion_slot_min = models.PositiveIntegerField(
        'Duración del slot (minutos)', default=30,
        validators=[MinValueValidator(5)],
        help_text='Duración por defecto del slot al generar disponibilidad.'
    )

    class Meta:
        verbose_name = 'Horario laboral'
        verbose_name_plural = 'Horarios laborales'
        ordering = ['recurso', 'dia_semana', 'hora_inicio']

    def __str__(self):
        return f'{self.recurso.nombre} - {self.get_dia_semana_display()} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M}'


class ExcepcionAgenda(ModeloBase):
    recurso = models.ForeignKey(
        Recurso, on_delete=models.CASCADE, related_name='excepciones',
        verbose_name='Recurso',
    )
    fecha = models.DateField('Fecha', db_index=True)
    tipo = models.CharField('Tipo', max_length=20, choices=EXCEPTION_TYPE_CHOICES)
    hora_inicio = models.TimeField('Hora de inicio', null=True, blank=True)
    hora_fin = models.TimeField('Hora de fin', null=True, blank=True)
    motivo = models.CharField('Motivo', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'Excepción de agenda'
        verbose_name_plural = 'Excepciones de agenda'
        ordering = ['recurso', 'fecha']

    def __str__(self):
        return f'{self.recurso.nombre} - {self.fecha} ({self.get_tipo_display()})'


class Servicio(ModeloBase):
    grupo_agenda = models.ForeignKey(
        GrupoAgenda, on_delete=models.CASCADE, related_name='servicios',
        verbose_name='Grupo de agenda',
    )
    nombre = models.CharField('Nombre', max_length=150)
    descripcion = models.TextField('Descripción', blank=True, default='')
    duracion_min = models.PositiveIntegerField(
        'Duración (minutos)', default=30,
        validators=[MinValueValidator(5)],
    )
    precio = models.DecimalField(
        'Precio', max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    recursos = models.ManyToManyField(
        Recurso, blank=True, related_name='servicios',
        verbose_name='Recursos que ofrecen este servicio',
    )
    orden = models.PositiveIntegerField('Orden', default=0, db_index=True)

    class Meta:
        verbose_name = 'Servicio'
        verbose_name_plural = 'Servicios'
        ordering = ['grupo_agenda', 'orden', 'nombre']

    def __str__(self):
        return f'{self.nombre} ({self.grupo_agenda.nombre})'

    @property
    def precio_formateado(self):
        return f'{self.precio} {self.grupo_agenda.moneda}'


class Turno(ModeloBase):
    recurso = models.ForeignKey(
        Recurso, on_delete=models.PROTECT, related_name='turnos',
        verbose_name='Recurso',
    )
    servicio = models.ForeignKey(
        Servicio, on_delete=models.PROTECT, related_name='turnos',
        verbose_name='Servicio',
    )
    contacto = models.ForeignKey(
        'whatsapp.Contacto', on_delete=models.PROTECT, related_name='turnos',
        verbose_name='Contacto',
    )
    inicio = models.DateTimeField('Inicio', db_index=True)
    fin = models.DateTimeField('Fin')
    precio_cobrado = models.DecimalField(
        'Precio cobrado', max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Snapshot del precio del servicio al momento de reservar.'
    )
    estado = models.CharField(
        'Estado', max_length=20, choices=APPOINTMENT_STATUS_CHOICES,
        default='pending', db_index=True,
    )
    origen = models.CharField(
        'Origen', max_length=20, choices=APPOINTMENT_ORIGIN_CHOICES,
        default='manual',
    )
    conversacion = models.ForeignKey(
        'whatsapp.ConversacionWhatsApp', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='turnos',
        verbose_name='Conversación',
    )
    notas = models.TextField('Notas', blank=True, default='')
    recordatorio_enviado = models.BooleanField('Recordatorio enviado', default=False, db_index=True)
    recordatorio_horas_antes = models.PositiveIntegerField(
        'Horas de anticipación del recordatorio', null=True, blank=True,
        help_text='Anula el valor del grupo solo para este turno. Vacío = usa el del grupo.'
    )
    recordatorio_intentos = models.PositiveSmallIntegerField(
        'Intentos de envío del recordatorio', default=0,
        help_text='Cantidad de envíos fallidos; al llegar al tope el cron deja de reintentar.'
    )
    turno_anterior = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reagendamientos',
        verbose_name='Turno anterior',
        help_text='Se asigna cuando este turno reemplaza a uno reagendado.'
    )

    class Meta:
        verbose_name = 'Turno'
        verbose_name_plural = 'Turnos'
        ordering = ['-inicio']
        indexes = [
            models.Index(fields=['recurso', 'inicio']),
            models.Index(fields=['contacto', 'inicio']),
        ]

    def __str__(self):
        return f'{self.contacto} - {self.servicio.nombre} - {self.inicio:%Y-%m-%d %H:%M}'

    def is_active(self):
        return self.estado in ACTIVE_STATUSES

    def overlaps_existing(self):
        qs = Turno.objects.filter(
            recurso=self.recurso,
            estado__in=ACTIVE_STATUSES,
            status=True,
            inicio__lt=self.fin,
            fin__gt=self.inicio,
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        return qs.exists()

    def save(self, *args, **kwargs):
        if not self.fin and self.inicio and self.servicio_id:
            self.fin = self.inicio + timezone.timedelta(minutes=self.servicio.duracion_min)
        super().save(*args, **kwargs)
