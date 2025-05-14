from email.policy import default
from functools import cached_property

from dateutil.relativedelta import relativedelta
from django.db import models
from django.utils import timezone

from core.custom_models import ModeloBase
from autenticacion.models import Usuario
from core.funciones import default_expira_10_min, get_encrypt
from core.funciones_adicionales import remover_espacios_de_mas
from whatsapp.models_querysetmanagers import ContactoManager, ConversacionWhatsAppManager

ESTADOS_SESION = (
    ('pendiente', 'Pendiente'),
    ('conectado', 'Conectado'),
    ('desconectado', 'Desconectado'),
    ('error', 'Error'),
)


class SesionWhatsApp(ModeloBase):
    nombre = models.CharField(max_length=150, blank=True, null=True, verbose_name='Nombre')
    numero = models.CharField(max_length=50, verbose_name='Número WhatsApp', default='')
    whatsapp_id = models.CharField(max_length=250, verbose_name='WhatsApp ID', default='', blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS_SESION, default='pendiente')
    qr_code = models.TextField(blank=True, null=True, verbose_name='Código QR actual (Base64)')
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, null=True, blank=True, verbose_name='Asesor asignado')
    ultima_conexion = models.DateTimeField(blank=True, null=True, verbose_name='Última conexión')
    observacion = models.TextField(blank=True, null=True, verbose_name='Observaciones')
    error_mensaje = models.TextField(blank=True, null=True, verbose_name='Último error')
    fecha_expira_inactivo = models.DateTimeField(default=default_expira_10_min, verbose_name='Fecha de expiración por inactividad')
    session_id = models.CharField(max_length=255, unique=True, verbose_name='ID de sesión')
    foto = models.TextField(blank=True, null=True, verbose_name='Foto')
    contacts_list = models.TextField(default='[]', verbose_name='Lista de Contactos')
    contacts_length = models.PositiveIntegerField(default=0, verbose_name='Cantidad de contactos')
    # Campos para la gestión de mensajes
    mensaje_bienvenida = models.TextField(blank=True, null=True, verbose_name='Mensaje de bienvenida')
    mensaje_despedida = models.TextField(blank=True, null=True, verbose_name='Mensaje de despedida')
    min_sesion = models.IntegerField(default=0, verbose_name='Minutos de sesión')

    def is_connected(self):
        return self.estado == 'conectado'

    class Meta:
        verbose_name = 'Sesión WhatsApp'
        verbose_name_plural = 'Sesiones WhatsApp'

    def __str__(self):
        return f"{self.numero} - {self.estado}"

    def save(self, *args, **kwargs):
        if self.estado == 'conectado':
            self.ultima_conexion = timezone.now()
        else:
            self.ultima_conexion = None
        if self.estado == 'pendiente':
            self.qr_code = None if not self.qr_code else self.qr_code
            self.session_id = None if not self.session_id else self.session_id
            self.foto = None if not self.foto else self.foto
            self.contacts_list = '[]' if not self.contacts_list else self.contacts_list
        # Validar que min_sesion no supere 180 minutos (3 horas)
        if self.min_sesion > 180:
            raise ValueError("El tiempo de sesión no puede superar las 3 horas (180 minutos).")
        if not self.min_sesion:
            self.min_sesion = 60
        if not self.nombre:
            self.nombre = self.numero.strip()
        # Limpiar espacios en blanco de los mensajes
        self.mensaje_bienvenida = remover_espacios_de_mas(self.mensaje_bienvenida)
        self.mensaje_despedida = remover_espacios_de_mas(self.mensaje_despedida)
        super().save(*args, **kwargs)


class WhatsAppWebhook(models.Model):
    WEBHOOK_TYPES = [
        ('qr_code', 'Código QR'),
        ('ready', 'Sesión Lista'),
        ('authenticated', 'Autenticado'),
        ('auth_failure', 'Fallo de Autenticación'),
        ('disconnected', 'Desconectado'),
        ('message', 'Mensaje Recibido'),
        ('message_sent', 'Mensaje Enviado'),
    ]

    session = models.ForeignKey(SesionWhatsApp, on_delete=models.CASCADE, related_name='webhooks')
    url = models.URLField()
    type = models.CharField(max_length=50, choices=WEBHOOK_TYPES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'url', 'type')

    def __str__(self):
        return f"{self.get_type_display()} - {self.url}"


class Contacto(ModeloBase):
    objects = ContactoManager()
    sesion = models.ForeignKey(SesionWhatsApp, on_delete=models.CASCADE)
    from_number = models.CharField(max_length=255, blank=True, null=True, default='', editable=False)
    contacto_numero = models.CharField(max_length=50, verbose_name='Número del contacto', editable=False)
    contacto_nombre = models.CharField(max_length=255, blank=True, null=True)
    contacto_foto = models.TextField(blank=True, null=True)
    numero_telefono = models.CharField(max_length=50, verbose_name='Número de teléfono', default='')
    estado = models.CharField(max_length=20, choices=(('activo', 'Activo'), ('cerrado', 'Cerrado')), default='activo')
    ultimo_mensaje = models.TextField(blank=True, null=True)
    fecha_ultimo_mensaje = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.contacto_numero} ({self.sesion.numero})"

    class Meta:
        verbose_name = 'Contacto WhatsApp'
        verbose_name_plural = 'Contactos WhatsApp'
        ordering = ['contacto_nombre']
        constraints = [
            models.UniqueConstraint(
                fields=['sesion', 'from_number'], name='whatsapp_contacto_sesion_from_number_unique'
            )
        ]

    def save(self, *args, **kwargs):
        if not self.numero_telefono:
            self.numero_telefono = self.contacto_numero
        else:
            self.contacto_numero = "".join([x for x in self.numero_telefono if x.isdigit()])
            self.from_number = f"{self.contacto_numero}@s.whatsapp.net"
        super().save(*args, **kwargs)


class ConversacionWhatsApp(ModeloBase):
    objects = ConversacionWhatsAppManager()
    hashed_id = models.TextField(default='')
    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(default=0)
    fecha_hora_expira = models.DateTimeField('Fecha y Hora que expira la conversación')
    bienvenida_enviado = models.BooleanField('Bienvenida Enviado', default=False)
    despedida_enviado = models.BooleanField('Despedida Enviado', default=False)

    class Meta:
        verbose_name = 'Conversación WhatsApp'
        verbose_name_plural = 'Conversaciones WhatsApp'
        ordering = ['-order']

    @cached_property
    def sesion(self):
        return self.contacto.sesion

    @cached_property
    def sesion_id(self):
        return self.contacto.sesion_id

    @cached_property
    def from_number(self):
        return self.contacto.from_number

    @cached_property
    def contacto_numero(self):
        return self.contacto.contacto_numero

    @cached_property
    def contacto_nombre(self):
        return self.contacto.contacto_nombre

    @cached_property
    def contacto_foto(self):
        return self.contacto.contacto_foto

    @cached_property
    def estado(self):
        return self.contacto.estado

    @cached_property
    def ultimo_mensaje(self):
        return self.contacto.ultimo_mensaje

    @cached_property
    def fecha_ultimo_mensaje(self):
        return self.contacto.fecha_ultimo_mensaje

    def __str__(self):
        return f"Conversación con {self.contacto}"

    def save(self, *args, **kwargs):
        if self.contacto.fecha_ultimo_mensaje:
            self.order = int(round(self.contacto.fecha_ultimo_mensaje.timestamp(), 0))
        if not self.fecha_hora_expira:
            self.fecha_hora_expira = timezone.now() + relativedelta(minutes=self.contacto.sesion.min_sesion)
        if not self.hashed_id:
            self.hashed_id = get_encrypt(self.id)[1]
        super().save(*args, **kwargs)


TIPO_MENSAJE_CHOICES = (
    ('texto', 'Texto'),
    ('imagen', 'Imagen'),
    ('audio', 'Audio'),
    ('video', 'Video'),
    ('documento', 'Documento'),
    ('ubicacion', 'Ubicación'),
    ('contacto', 'Contacto'),
    ('sticker', 'Sticker'),
    ('archivo', 'Archivo')
)


class MensajeWhatsApp(ModeloBase):
    conversacion = models.ForeignKey(ConversacionWhatsApp, on_delete=models.CASCADE, related_name='mensajes')
    remitente = models.CharField(max_length=50)  # Número de teléfono del remitente
    mensaje = models.TextField()
    mensaje_original = models.TextField(blank=True, null=True)  # Para guardar el mensaje original en caso de edición
    tipo = models.CharField(max_length=20, choices=TIPO_MENSAJE_CHOICES, default='texto')
    archivo_url = models.URLField(blank=True, null=True)
    fecha = models.DateTimeField()
    leido = models.BooleanField(default=False)
    fecha_leido = models.DateTimeField(blank=True, null=True)

    # Campos para mensajes eliminados
    eliminado = models.BooleanField(default=False)
    fecha_eliminacion = models.DateTimeField(blank=True, null=True)

    # Campos para mensajes editados
    editado = models.BooleanField(default=False)
    fecha_edicion = models.DateTimeField(blank=True, null=True)

    # Para mensajes enviados por el sistema
    es_automatico = models.BooleanField(default=False, verbose_name='¿Enviado automáticamente?')
    ia_generado = models.BooleanField(default=False, verbose_name='¿Generado por IA?')

    # ID externo del mensaje (para poder identificarlo cuando se elimina o edita)
    mensaje_id_externo = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = "Mensaje WhatsApp"
        verbose_name_plural = "Mensajes WhatsApp"
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.remitente}: {self.mensaje[:30]}"


class EstadisticasConversacion(ModeloBase):
    conversacion = models.OneToOneField(ConversacionWhatsApp, on_delete=models.CASCADE, related_name='estadisticas')
    total_mensajes = models.IntegerField(default=0)
    mensajes_cliente = models.IntegerField(default=0)
    mensajes_asesor = models.IntegerField(default=0)
    mensajes_automaticos = models.IntegerField(default=0)
    mensajes_ia = models.IntegerField(default=0)
    tiempo_primera_respuesta = models.DurationField(null=True, blank=True)
    tiempo_respuesta_promedio = models.DurationField(null=True, blank=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Estadísticas de conversación'
        verbose_name_plural = 'Estadísticas de conversaciones'

    def __str__(self):
        return f"Estadísticas: {self.conversacion}"