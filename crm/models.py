# crm/models.py
from django.db import models
from core.custom_models import ModeloBase
from autenticacion.models import Usuario
from whatsapp.models import ConversacionWhatsApp  # Importando tu modelo existente


class Industria(ModeloBase):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'Industria'
        verbose_name_plural = 'Industrias'


class EtapaVenta(ModeloBase):
    nombre = models.CharField(max_length=100)
    orden = models.PositiveSmallIntegerField(default=0)
    industria = models.ForeignKey(Industria, on_delete=models.CASCADE, related_name='etapas')
    duracion_estimada = models.PositiveIntegerField(help_text="Duración estimada en días", default=1)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['orden']
        verbose_name = 'Etapa de venta'
        verbose_name_plural = 'Etapas de venta'

    def __str__(self):
        return f"{self.nombre} - {self.industria}"


class Lead(ModeloBase):
    conversacion = models.OneToOneField(ConversacionWhatsApp, on_delete=models.CASCADE, related_name='lead')
    industria = models.ForeignKey(Industria, on_delete=models.PROTECT)
    etapa_actual = models.ForeignKey(EtapaVenta, on_delete=models.SET_NULL, null=True, blank=True)

    # Datos de contacto complementarios
    correo = models.EmailField(blank=True, null=True)
    empresa = models.CharField(max_length=200, blank=True, null=True)
    cargo = models.CharField(max_length=100, blank=True, null=True)

    # Etiquetas para clasificación
    etiquetas = models.ManyToManyField('Etiqueta', blank=True)

    # Datos de negocio
    valor_estimado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    probabilidad_cierre = models.PositiveSmallIntegerField(default=0, help_text="Porcentaje de 0 a 100")
    fecha_primer_contacto = models.DateTimeField(auto_now_add=True)
    fecha_ultima_actividad = models.DateTimeField(auto_now=True)
    fecha_cierre_estimada = models.DateField(null=True, blank=True)

    # Asignación
    asesor_asignado = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='leads')

    # Estado
    ESTADOS = (
        ('nuevo', 'Nuevo'),
        ('en_seguimiento', 'En Seguimiento'),
        ('oportunidad', 'Oportunidad'),
        ('ganado', 'Ganado'),
        ('perdido', 'Perdido'),
        ('inactivo', 'Inactivo'),
    )
    estado = models.CharField(max_length=20, choices=ESTADOS, default='nuevo')

    class Meta:
        verbose_name = 'Lead'
        verbose_name_plural = 'Leads'

    def __str__(self):
        return f"Lead: {self.conversacion.contacto_nombre or self.conversacion.contacto_numero}"


class Seguimiento(ModeloBase):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='seguimientos')
    etapa = models.ForeignKey(EtapaVenta, on_delete=models.SET_NULL, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    notas = models.TextField()
    usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)

    # Campos para seguimiento de llamadas o interacciones
    tipo_interaccion = models.CharField(max_length=50, choices=(
        ('llamada', 'Llamada'),
        ('mensaje', 'Mensaje WhatsApp'),
        ('correo', 'Correo Electrónico'),
        ('reunion', 'Reunión'),
        ('otro', 'Otro'),
    ))
    resultado = models.CharField(max_length=50, choices=(
        ('positivo', 'Positivo'),
        ('neutral', 'Neutral'),
        ('negativo', 'Negativo'),
        ('no_respuesta', 'Sin Respuesta'),
    ))
    duracion = models.PositiveIntegerField(help_text="Duración en minutos", null=True, blank=True)

    class Meta:
        verbose_name = 'Seguimiento'
        verbose_name_plural = 'Seguimientos'

    def __str__(self):
        return f"Seguimiento de {self.lead} - {self.fecha.strftime('%d/%m/%Y')}"


class Etiqueta(ModeloBase):
    nombre = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default="#3498db")  # Formato HEX
    industria = models.ForeignKey(Industria, on_delete=models.CASCADE, related_name='etiquetas')

    class Meta:
        verbose_name = 'Etiqueta'
        verbose_name_plural = 'Etiquetas'

    def __str__(self):
        return self.nombre


class Producto(ModeloBase):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField()
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    industria = models.ForeignKey(Industria, on_delete=models.CASCADE, related_name='productos')
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'

    def __str__(self):
        return self.nombre


class Venta(ModeloBase):
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name='ventas')
    fecha_venta = models.DateTimeField(auto_now_add=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    asesor = models.ForeignKey(Usuario, on_delete=models.PROTECT)

    # Estado de la venta
    ESTADOS = (
        ('pendiente', 'Pendiente de Pago'),
        ('pagado', 'Pagado'),
        ('entregado', 'Entregado'),
        ('cancelado', 'Cancelado'),
    )
    estado = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')

    class Meta:
        verbose_name = 'Venta'
        verbose_name_plural = 'Ventas'

    def __str__(self):
        return f"Venta a {self.lead} - {self.fecha_venta.strftime('%d/%m/%Y')}"


class DetalleVenta(ModeloBase):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    def subtotal(self):
        return self.cantidad * self.precio_unitario

    class Meta:
        verbose_name = 'Detalle de venta'
        verbose_name_plural = 'Detalles de venta'

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre}"


class Plantilla(ModeloBase):
    """Plantillas de respuesta para automatización"""
    nombre = models.CharField(max_length=100)
    contenido = models.TextField()
    industria = models.ForeignKey(Industria, on_delete=models.CASCADE, related_name='plantillas')
    etapa = models.ForeignKey(EtapaVenta, on_delete=models.SET_NULL, null=True, blank=True)
    variables = models.TextField(help_text="Variables disponibles separadas por coma", blank=True)

    class Meta:
        verbose_name = 'Plantilla'
        verbose_name_plural = 'Plantillas'

    def __str__(self):
        return self.nombre


class ConfiguracionIA(ModeloBase):
    """Configuración para respuestas automáticas por IA"""
    industria = models.ForeignKey(Industria, on_delete=models.CASCADE)
    prompt_base = models.TextField(help_text="Prompt base para contextualizar a la IA")
    modelo = models.CharField(max_length=100, default="gpt-3.5-turbo")
    temperatura = models.FloatField(default=0.7)
    max_tokens = models.PositiveIntegerField(default=150)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Configuración de IA'
        verbose_name_plural = 'Configuraciones de IA'

    def __str__(self):
        return f"Config IA para {self.industria}"