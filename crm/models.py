from django.db import models
from core.custom_models import ModeloBase
from autenticacion.models import Usuario
from whatsapp.models import ConversacionWhatsApp

# Representa las industrias generales a las que puede pertenecer un negocio
class Industria(ModeloBase):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'Industria'
        verbose_name_plural = 'Industrias'


# Permite especificar con más detalle a qué se dedica una empresa dentro de una industria
class ActividadEconomica(ModeloBase):
    nombre = models.CharField(max_length=100)
    industria = models.ForeignKey(Industria, on_delete=models.CASCADE, related_name='actividades')
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Actividad Económica'
        verbose_name_plural = 'Actividades Económicas'

    def __str__(self):
        return f"{self.nombre} ({self.industria.nombre})"


# Etapas de venta configurables por industria (embudo personalizado)
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


# Perfil de IA para el usuario autenticado (asesor/cliente)
class PerfilNegocioIA(ModeloBase):
    usuario = models.OneToOneField(Usuario, on_delete=models.CASCADE, related_name='perfil_ia')
    industria = models.ForeignKey(Industria, on_delete=models.SET_NULL, null=True, blank=True)
    actividad = models.ForeignKey(ActividadEconomica, on_delete=models.SET_NULL, null=True, blank=True)
    nombre_empresa = models.CharField(max_length=200, blank=True, null=True)
    descripcion_empresa = models.TextField(blank=True, null=True)
    sitio_web = models.URLField(blank=True, null=True)
    localidad = models.CharField(max_length=100, blank=True, null=True)
    publico_objetivo = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Perfil de Negocio IA"
        verbose_name_plural = "Perfiles de Negocio IA"

    def __str__(self):
        return f"{self.usuario.get_full_name()} - {self.industria.nombre if self.industria else 'Sin industria'}"

    # MÉTODOS ÚTILES

    def tiene_datos_basicos(self):
        return all([self.nombre_empresa, self.descripcion_empresa, self.industria, self.actividad])

    def resumen_contexto_ia(self):
        productos = self.productos.all()
        servicios = self.servicios.all()
        lista_productos = ", ".join([f"{p.nombre} (${p.precio})" for p in productos]) or "N/A"
        lista_servicios = ", ".join([f"{s.nombre}" for s in servicios]) or "N/A"

        return f"""Empresa: {self.nombre_empresa or 'No definido'}
            Industria: {self.industria.nombre if self.industria else 'No definida'}
            Actividad económica: {self.actividad.nombre if self.actividad else 'No definida'}
            Ubicación: {self.localidad or 'No definida'}
            Descripción: {self.descripcion_empresa or 'No definida'}
            Público objetivo: {self.publico_objetivo or 'No definido'}
            Productos ofrecidos: {lista_productos}
            Servicios ofrecidos: {lista_servicios}
            """.strip()

    def total_productos(self):
        return self.productos.count()

    def total_servicios(self):
        return self.servicios.count()


# Productos personalizados del perfil IA
class ProductoIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, related_name='productos')
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Producto IA"
        verbose_name_plural = "Productos IA"

    def __str__(self):
        return f"{self.nombre} - ${self.precio}"


# Servicios personalizados del perfil IA
class ServicioIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, related_name='servicios')
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    precio_referencial = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "Servicio IA"
        verbose_name_plural = "Servicios IA"

    def __str__(self):
        return f"{self.nombre} - ${self.precio_referencial or 0}"


# Preguntas y respuestas predefinidas para que la IA sepa cómo responder ante ciertos temas o comportamientos definidos por el usuario
class RespuestaEntrenadaIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, related_name='respuestas_ia')
    pregunta_clave = models.CharField(max_length=255, help_text="Palabra o frase que activa esta respuesta")
    respuesta_configurada = models.TextField(help_text="Respuesta sugerida por el usuario")
    tono = models.CharField(max_length=100, choices=[
        ('formal', 'Formal'),
        ('informal', 'Informal'),
        ('empatico', 'Empático'),
        ('directo', 'Directo'),
        ('humilde', 'Humilde'),
        ('seguro', 'Seguro'),
    ], default='formal', help_text="Tono sugerido para esta respuesta")

    class Meta:
        verbose_name = 'Respuesta Entrenada IA'
        verbose_name_plural = 'Respuestas Entrenadas IA'

    def __str__(self):
        return f"{self.pregunta_clave} → {self.tono}"
