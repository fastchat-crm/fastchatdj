from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.custom_models import ModeloBase


CURRENCY_CHOICES = (
    ('ARS', 'Argentine Peso (ARS)'),
    ('USD', 'US Dollar (USD)'),
    ('EUR', 'Euro (EUR)'),
    ('PEN', 'Peruvian Sol (PEN)'),
    ('CLP', 'Chilean Peso (CLP)'),
    ('COP', 'Colombian Peso (COP)'),
    ('MXN', 'Mexican Peso (MXN)'),
    ('BRL', 'Brazilian Real (BRL)'),
    ('UYU', 'Uruguayan Peso (UYU)'),
    ('PYG', 'Paraguayan Guarani (PYG)'),
    ('BOB', 'Bolivian Boliviano (BOB)'),
    ('VES', 'Venezuelan Bolivar (VES)'),
)

WEEKDAY_CHOICES = (
    (0, 'Monday'),
    (1, 'Tuesday'),
    (2, 'Wednesday'),
    (3, 'Thursday'),
    (4, 'Friday'),
    (5, 'Saturday'),
    (6, 'Sunday'),
)

EXCEPTION_TYPE_CHOICES = (
    ('block_day', 'Block whole day'),
    ('block_range', 'Block hour range'),
    ('add_range', 'Add extra hour range'),
)

APPOINTMENT_STATUS_CHOICES = (
    ('pending', 'Pending'),
    ('confirmed', 'Confirmed'),
    ('cancelled', 'Cancelled'),
    ('rescheduled', 'Rescheduled'),
    ('fulfilled', 'Fulfilled'),
    ('no_show', 'No-show'),
)

APPOINTMENT_ORIGIN_CHOICES = (
    ('chatbot', 'Chatbot'),
    ('manual', 'Manual'),
    ('api', 'API'),
)

ACTIVE_STATUSES = ('pending', 'confirmed')


class GrupoAgenda(ModeloBase):
    nombre = models.CharField('Name', max_length=120)
    descripcion = models.TextField('Description', blank=True, default='')
    moneda = models.CharField('Currency', max_length=8, choices=CURRENCY_CHOICES, default='USD')
    recordatorio_horas_antes = models.PositiveIntegerField(
        'Reminder hours before', default=24,
        help_text='How many hours before the appointment the reminder is sent.'
    )
    zona_horaria = models.CharField(
        'Timezone', max_length=64, default='America/Guayaquil',
        help_text='TZ database name (e.g. America/Guayaquil, UTC).'
    )

    class Meta:
        verbose_name = 'Agenda group'
        verbose_name_plural = 'Agenda groups'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Recurso(ModeloBase):
    grupo_agenda = models.ForeignKey(
        GrupoAgenda, on_delete=models.CASCADE, related_name='recursos',
        verbose_name='Agenda group',
    )
    nombre = models.CharField('Name', max_length=120)
    descripcion = models.TextField('Description', blank=True, default='')
    color = models.CharField('Color', max_length=20, default='#0d6efd')
    orden = models.PositiveIntegerField('Order', default=0, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='recursos_agenda',
        verbose_name='Linked user',
        help_text='Optional user assigned to this resource (e.g. agent).'
    )

    class Meta:
        verbose_name = 'Resource'
        verbose_name_plural = 'Resources'
        ordering = ['grupo_agenda', 'orden', 'nombre']

    def __str__(self):
        return f'{self.nombre} ({self.grupo_agenda.nombre})'


class HorarioLaboral(ModeloBase):
    recurso = models.ForeignKey(
        Recurso, on_delete=models.CASCADE, related_name='horarios',
        verbose_name='Resource',
    )
    dia_semana = models.PositiveSmallIntegerField('Weekday', choices=WEEKDAY_CHOICES)
    hora_inicio = models.TimeField('Start time')
    hora_fin = models.TimeField('End time')
    duracion_slot_min = models.PositiveIntegerField(
        'Slot duration (minutes)', default=30,
        validators=[MinValueValidator(5)],
        help_text='Default slot length used when generating availability.'
    )

    class Meta:
        verbose_name = 'Working schedule'
        verbose_name_plural = 'Working schedules'
        ordering = ['recurso', 'dia_semana', 'hora_inicio']

    def __str__(self):
        return f'{self.recurso.nombre} - {self.get_dia_semana_display()} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M}'


class ExcepcionAgenda(ModeloBase):
    recurso = models.ForeignKey(
        Recurso, on_delete=models.CASCADE, related_name='excepciones',
        verbose_name='Resource',
    )
    fecha = models.DateField('Date', db_index=True)
    tipo = models.CharField('Type', max_length=20, choices=EXCEPTION_TYPE_CHOICES)
    hora_inicio = models.TimeField('Start time', null=True, blank=True)
    hora_fin = models.TimeField('End time', null=True, blank=True)
    motivo = models.CharField('Reason', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'Schedule exception'
        verbose_name_plural = 'Schedule exceptions'
        ordering = ['recurso', 'fecha']

    def __str__(self):
        return f'{self.recurso.nombre} - {self.fecha} ({self.get_tipo_display()})'


class Servicio(ModeloBase):
    grupo_agenda = models.ForeignKey(
        GrupoAgenda, on_delete=models.CASCADE, related_name='servicios',
        verbose_name='Agenda group',
    )
    nombre = models.CharField('Name', max_length=150)
    descripcion = models.TextField('Description', blank=True, default='')
    duracion_min = models.PositiveIntegerField(
        'Duration (minutes)', default=30,
        validators=[MinValueValidator(5)],
    )
    precio = models.DecimalField(
        'Price', max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    recursos = models.ManyToManyField(
        Recurso, blank=True, related_name='servicios',
        verbose_name='Resources offering this service',
    )
    orden = models.PositiveIntegerField('Order', default=0, db_index=True)

    class Meta:
        verbose_name = 'Service'
        verbose_name_plural = 'Services'
        ordering = ['grupo_agenda', 'orden', 'nombre']

    def __str__(self):
        return f'{self.nombre} ({self.grupo_agenda.nombre})'

    @property
    def precio_formateado(self):
        return f'{self.precio} {self.grupo_agenda.moneda}'


class Turno(ModeloBase):
    recurso = models.ForeignKey(
        Recurso, on_delete=models.PROTECT, related_name='turnos',
        verbose_name='Resource',
    )
    servicio = models.ForeignKey(
        Servicio, on_delete=models.PROTECT, related_name='turnos',
        verbose_name='Service',
    )
    contacto = models.ForeignKey(
        'whatsapp.Contacto', on_delete=models.PROTECT, related_name='turnos',
        verbose_name='Contact',
    )
    inicio = models.DateTimeField('Start', db_index=True)
    fin = models.DateTimeField('End')
    precio_cobrado = models.DecimalField(
        'Charged price', max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Snapshot of service price at booking time.'
    )
    estado = models.CharField(
        'Status', max_length=20, choices=APPOINTMENT_STATUS_CHOICES,
        default='pending', db_index=True,
    )
    origen = models.CharField(
        'Origin', max_length=20, choices=APPOINTMENT_ORIGIN_CHOICES,
        default='manual',
    )
    conversacion = models.ForeignKey(
        'whatsapp.ConversacionWhatsApp', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='turnos',
        verbose_name='Conversation',
    )
    notas = models.TextField('Notes', blank=True, default='')
    recordatorio_enviado = models.BooleanField('Reminder sent', default=False, db_index=True)
    turno_anterior = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reagendamientos',
        verbose_name='Previous appointment',
        help_text='Set when this appointment replaces a rescheduled one.'
    )

    class Meta:
        verbose_name = 'Appointment'
        verbose_name_plural = 'Appointments'
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
