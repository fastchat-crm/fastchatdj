from django.db import models
from core.custom_models import ModeloBase
from autenticacion.models import Usuario

ESTADOS_SESION = (
    ('pendiente', 'Pendiente'),
    ('conectado', 'Conectado'),
    ('desconectado', 'Desconectado'),
    ('error', 'Error'),
)

class SesionWhatsApp(ModeloBase):
    numero = models.CharField(max_length=20, verbose_name='Número WhatsApp')
    estado = models.CharField(max_length=20, choices=ESTADOS_SESION, default='pendiente')
    qr_code = models.TextField(blank=True, null=True, verbose_name='Código QR actual (Base64)')
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, null=True, blank=True, verbose_name='Asesor asignado')
    ultima_conexion = models.DateTimeField(blank=True, null=True, verbose_name='Última conexión')
    observacion = models.TextField(blank=True, null=True, verbose_name='Observaciones')
    error_mensaje = models.TextField(blank=True, null=True, verbose_name='Último error')

    def is_connected(self):
        return self.estado == 'conectado'

    class Meta:
        verbose_name = 'Sesión WhatsApp'
        verbose_name_plural = 'Sesiones WhatsApp'

    def __str__(self):
        return f"{self.numero} - {self.estado}"


class ConversacionWhatsApp(ModeloBase):
    sesion = models.ForeignKey(SesionWhatsApp, on_delete=models.CASCADE, related_name='conversaciones')
    contacto_numero = models.CharField(max_length=50, verbose_name='Número del contacto')
    contacto_nombre = models.CharField(max_length=255, blank=True, null=True)
    contacto_foto = models.URLField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=(('activo', 'Activo'), ('cerrado', 'Cerrado')), default='activo')
    ultimo_mensaje = models.TextField(blank=True, null=True)
    fecha_ultimo_mensaje = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Conversación con {self.contacto_numero} ({self.sesion.numero})"


class MensajeWhatsApp(ModeloBase):
    conversacion = models.ForeignKey(ConversacionWhatsApp, on_delete=models.CASCADE, related_name='mensajes')
    remitente = models.CharField(max_length=20, verbose_name='Número remitente')
    mensaje = models.TextField(blank=True, null=True)
    tipo = models.CharField(max_length=20, choices=(('texto', 'Texto'), ('imagen', 'Imagen'), ('archivo', 'Archivo')), default='texto')
    archivo_url = models.URLField(blank=True, null=True)
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Mensaje de {self.remitente} - {self.tipo}"
