import json

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
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Actividad Económica'
        verbose_name_plural = 'Actividades Económicas'

    def __str__(self):
        return f"{self.nombre}"


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

    def get_productos(self):
        return self.productos.filter(status=True)

    def get_servicios(self):
        return self.servicios.filter(status=True)

    def get_respuestas(self):
        return self.respuestas_ia.filter(status=True)

    def get_agentes(self):
        return self.agentesia_set.filter(status=True).order_by('nombre')

    def get_apis(self):
        return self.apikeyia_set.filter(status=True)

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


class AgentesIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, blank=True, null=True, verbose_name='Perfil Negocio IA')
    apikey = models.ForeignKey('ApiKeyIA', on_delete=models.CASCADE, blank=True, null=True, verbose_name='Api Key IA')
    nombre = models.CharField(max_length=255, verbose_name="Nombre de agente")
    descripcion = models.TextField(verbose_name="Descripcion del agente")

    class Meta:
        verbose_name = 'Respuesta Entrenada IA'
        verbose_name_plural = 'Respuestas Entrenadas IA'

    def obtener_detalles_agente(self):
        """
        Función para obtener los detalles existentes de un agente
        """
        detalles = self.detalleagentesai_set.filter(status=True)
        detalles_json = []

        for detalle in detalles:
            detalle_data = {
                'id': detalle.id,
                'tipo': detalle.tipo,
                'enlace': detalle.enlace or '',
                'tipo_dato_enlace': detalle.tipo_dato_enlace,
                'archivo_url': detalle.archivo.url if detalle.archivo else '',
                'descripcion': detalle.descripcion if detalle.descripcion else ''
            }
            detalles_json.append(detalle_data)

        return json.dumps(detalles_json)

    def __str__(self):
        return f"{self.nombre}"


TIPO_DETALLE_AGENTE_AI = (
    (1, 'ENLACE'),
    (2, 'ARCHIVO'),
)

TIPO_DATO_ENLACE = (
    (1, 'TEXT'),
    (2, 'HTML'),
    (3, 'JSON'),
    (4, 'EXCEL'),
    (5, 'CSV'),
)

class DetalleAgentesAI(ModeloBase):
    agente = models.ForeignKey(AgentesIA, on_delete=models.CASCADE, blank=True, null=True, verbose_name='Agente')
    tipo = models.PositiveSmallIntegerField(choices=TIPO_DETALLE_AGENTE_AI, default=1, verbose_name='Tipo de detalle')
    enlace = models.URLField(blank=True, null=True, verbose_name='Enlace')
    tipo_dato_enlace = models.PositiveSmallIntegerField(choices=TIPO_DATO_ENLACE, default=1, verbose_name='Tipo de dato retorna')
    archivo = models.FileField(upload_to='detalles_agentes/', blank=True, null=True, verbose_name='Archivo adjunto')
    descripcion = models.TextField(blank=True, null=True, verbose_name='Descripción del detalle')

    class Meta:
        verbose_name = 'Respuesta Entrenada IA'
        verbose_name_plural = 'Respuestas Entrenadas IA'

PROVEEDOR_CHOICES = (
    (2, 'GEMINI'),
    (3, 'OPEN IA'),
)

class ApiKeyIA(ModeloBase):
    perfil = models.ForeignKey(PerfilNegocioIA, on_delete=models.CASCADE, blank=True, null=True, verbose_name='Perfil Negocio IA')
    descripcion = models.CharField(max_length=255, verbose_name="Api Key")
    proveedor = models.IntegerField(choices=PROVEEDOR_CHOICES, default=1, verbose_name='Proveedor')

    class Meta:
        verbose_name = 'Api Keys IA'
        verbose_name_plural = 'Apis Keys IA'

    def __str__(self):
        return f"{self.descripcion}"


class DepartamentoChatBot(ModeloBase):
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    color = models.CharField(max_length=100, verbose_name="Color", default='')
    mensaje_saludo = models.TextField(verbose_name="Mensaje de saludo", default='')

    class Meta:
        verbose_name = 'Departamento ChatBot'
        verbose_name_plural = 'Departamentos ChatBot'

    def __str__(self):
        return self.nombre

    def obtener_arbol_opciones(self):
        def construir_arbol(opciones):
            resultado = []
            for opcion in opciones:
                resultado.append({
                    'id': opcion.id,
                    'nombre': opcion.nombre,
                    'respuesta': opcion.respuesta,
                    'orden': opcion.orden,
                    'hijos': construir_arbol(opcion.subopciones.filter(status=True).order_by('orden'))
                })
            return resultado

        opciones_raiz = self.opciondepartamentochatbot_set.filter(opcion_padre__isnull=True, status=True).order_by('orden')
        return construir_arbol(opciones_raiz)

    def obtener_perfiles(self):
        return self.perfildepartamentochatbot_set.filter(status=True).order_by('usuario__first_name')


class OpcionDepartamentoChatBot(ModeloBase):
    departamento = models.ForeignKey(DepartamentoChatBot, on_delete=models.CASCADE, verbose_name="Departamento")
    orden = models.PositiveSmallIntegerField(default=0, verbose_name="Orden")
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    respuesta = models.TextField(verbose_name="Respuesta", default='')
    opcion_padre = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subopciones', verbose_name="Opción padre")

    class Meta:
        verbose_name = 'Opción Departamento ChatBot'
        verbose_name_plural = 'Opciones Departamentos ChatBot'

    def __str__(self):
        return f"{self.departamento.nombre} - {self.nombre}"


class PerfilDepartamentoChatBot(ModeloBase):
    departamento = models.ForeignKey(DepartamentoChatBot, on_delete=models.SET_NULL, null=True, blank=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)

    class Meta:
        verbose_name = 'Perfil Negocio ChatBot'
        verbose_name_plural = 'Perfiles Negocios ChatBot'

    def __str__(self):
        return f"{self.usuario.get_full_name()} - {self.departamento.nombre if self.departamento else 'Sin departamento'}"
