from django.db import models
from core.custom_models import ModeloBase
from autenticacion.models import Usuario
from core.funciones import default_expira_10_min
from whatsapp.models_querysetmanagers import ConversacionWhatsAppManager

ESTADOS_SESION = (
    ('pendiente', 'Pendiente'),
    ('conectado', 'Conectado'),
    ('desconectado', 'Desconectado'),
    ('error', 'Error'),
)


class SesionWhatsApp(ModeloBase):
    numero = models.CharField(max_length=50, verbose_name='Número WhatsApp', default='')
    whatsapp_id = models.CharField(max_length=250, verbose_name='WhatsApp ID', default='')
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
            self.ultima_conexion = models.DateTimeField(auto_now=True)
        else:
            self.ultima_conexion = None
        if self.estado == 'pendiente':
            self.qr_code = None if not self.qr_code else self.qr_code
            self.whatsapp_id = None if not self.whatsapp_id else self.whatsapp_id
            self.session_id = None if not self.session_id else self.session_id
            self.foto = None if not self.foto else self.foto
            self.contacts_list = '[]' if not self.contacts_list else self.contacts_list
        # Validar que min_sesion no supere 180 minutos (3 horas)
        if self.min_sesion > 180:
            raise ValueError("El tiempo de sesión no puede superar las 3 horas (180 minutos).")        
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


class ConversacionWhatsApp(ModeloBase):
    objects = ConversacionWhatsAppManager()
    sesion = models.ForeignKey(SesionWhatsApp, on_delete=models.CASCADE, related_name='conversaciones')
    from_number = models.CharField(max_length=255, blank=True, null=True, default='')
    contacto_numero = models.CharField(max_length=50, verbose_name='Número del contacto')
    contacto_nombre = models.CharField(max_length=255, blank=True, null=True)
    contacto_foto = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=(('activo', 'Activo'), ('cerrado', 'Cerrado')), default='activo')
    ultimo_mensaje = models.TextField(blank=True, null=True)
    fecha_ultimo_mensaje = models.DateTimeField(blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Conversación WhatsApp'
        verbose_name_plural = 'Conversaciones WhatsApp'
        ordering = ['-order']
        constraints = [
            models.UniqueConstraint(
                fields=['sesion', 'from_number'], name='whatsapp_conversacion_sesion_from_number_unique'
            )
        ]

    def __str__(self):
        return f"Conversación con {self.contacto_numero} ({self.sesion.numero})"

    def save(self, *args, **kwargs):
        if self.fecha_ultimo_mensaje:
            self.order = int(round(self.fecha_ultimo_mensaje.timestamp(), 0))
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


class RespuestaAutomatica(ModeloBase):
    sesion = models.ForeignKey(SesionWhatsApp, on_delete=models.CASCADE, related_name='respuestas_automaticas')
    palabra_clave = models.CharField(max_length=100, help_text="Palabra o frase que activa esta respuesta")
    respuesta = models.TextField()
    activo = models.BooleanField(default=True)
    prioridad = models.IntegerField(default=0, help_text="Mayor número = mayor prioridad")

    class Meta:
        verbose_name = 'Respuesta automática'
        verbose_name_plural = 'Respuestas automáticas'
        ordering = ['-prioridad']

    def __str__(self):
        return f"Auto-respuesta: {self.palabra_clave[:20]}"


class MensajeProgramado(ModeloBase):
    conversacion = models.ForeignKey(ConversacionWhatsApp, on_delete=models.CASCADE,
                                     related_name='mensajes_programados')
    mensaje = models.TextField()
    tipo = models.CharField(max_length=20, choices=(
        ('texto', 'Texto'),
        ('imagen', 'Imagen'),
        ('archivo', 'Archivo')
    ), default='texto')
    archivo_url = models.URLField(blank=True, null=True)
    fecha_programada = models.DateTimeField()
    enviado = models.BooleanField(default=False)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    programado_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)

    class Meta:
        verbose_name = 'Mensaje programado'
        verbose_name_plural = 'Mensajes programados'
        ordering = ['fecha_programada']

    def __str__(self):
        return f"Programado: {self.fecha_programada.strftime('%d/%m/%Y %H:%M')}"


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


class UsoDeLaIA(ModeloBase):
    sesion = models.ForeignKey(SesionWhatsApp, on_delete=models.CASCADE, related_name='uso_ia')
    fecha = models.DateField(auto_now_add=True)
    mensajes_procesados = models.IntegerField(default=0)
    mensajes_respondidos = models.IntegerField(default=0)
    tokens_consumidos = models.IntegerField(default=0)
    costo_estimado = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Uso de IA'
        verbose_name_plural = 'Uso de IA'
        unique_together = ['sesion', 'fecha']

    def __str__(self):
        return f"Uso IA: {self.sesion} - {self.fecha}"


class AsignacionChat(ModeloBase):
    conversacion = models.ForeignKey(ConversacionWhatsApp, on_delete=models.CASCADE, related_name='asignaciones')
    asesor = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    fecha_asignacion = models.DateTimeField(auto_now_add=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)
    asignado_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True,
                                     related_name='asignaciones_realizadas')
    MOTIVO_FIN = (
        ('reasignacion', 'Reasignación'),
        ('finalizacion', 'Finalización de la conversación'),
        ('desconexion', 'Desconexión del asesor'),
        ('otro', 'Otro motivo')
    )
    motivo_fin = models.CharField(max_length=20, choices=MOTIVO_FIN, null=True, blank=True)

    class Meta:
        verbose_name = 'Asignación de chat'
        verbose_name_plural = 'Asignaciones de chat'

    def __str__(self):
        return f"Asignación: {self.conversacion} a {self.asesor}"


class TemplateWhatsApp(ModeloBase):
    """Plantillas oficiales de WhatsApp Business API"""
    nombre = models.CharField(max_length=100)
    namespace = models.CharField(max_length=100, blank=True, null=True)
    idioma = models.CharField(max_length=10, default='es')
    categoria = models.CharField(max_length=50, choices=(
        ('marketing', 'Marketing'),
        ('utilidad', 'Utilidad'),
        ('autenticacion', 'Autenticación')
    ))
    contenido = models.TextField()
    variables = models.TextField(help_text="Variables en formato {{1}}, {{2}}, etc.", blank=True)
    header_type = models.CharField(max_length=20, choices=(
        ('none', 'Ninguno'),
        ('text', 'Texto'),
        ('image', 'Imagen'),
        ('document', 'Documento'),
        ('video', 'Video')
    ), default='none')
    header_text = models.CharField(max_length=255, blank=True, null=True)
    aprobado = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Template WhatsApp'
        verbose_name_plural = 'Templates WhatsApp'

    def __str__(self):
        return f"Template: {self.nombre}"