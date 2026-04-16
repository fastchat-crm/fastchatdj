import json
import os
from email.policy import default
from functools import cached_property

from dateutil.relativedelta import relativedelta
from django.conf.global_settings import LANGUAGES
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone

from agents_ai.agente_resumidor import AgenteResumidor
from core.custom_models import ModeloBase
from autenticacion.models import Usuario
from core.funciones import default_expira_10_min, get_encrypt
from core.funciones_adicionales import remover_espacios_de_mas
from fastchatdj.settings import MEDIA_ROOT
from whatsapp.models_querysetmanagers import ContactoManager, ConversacionWhatsAppManager

ESTADOS_SESION = (
    ('pendiente', 'Pendiente'),
    ('conectado', 'Conectado'),
    ('desconectado', 'Desconectado'),
    ('error', 'Error'),
)

MODOS_BOT = (
    ('ninguno',     'Sin bot (sólo humanos)'),
    ('tradicional', 'Chatbot tradicional (flujo/menús/APIs)'),
    ('ia',          'Agente IA'),
    ('hibrido',     'Híbrido: flujo tradicional, cae a IA si no matchea'),
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
    mensaje_handoff = models.TextField(blank=True, null=True, verbose_name='Mensaje de transferencia a agente',
                                       help_text='Se envía al cliente cuando la IA transfiere a un agente humano')
    min_sesion = models.IntegerField(default=0, verbose_name='Minutos de sesión')
    departamentos = models.ManyToManyField('crm.DepartamentoChatBot', verbose_name='Departamentos', blank=True)
    modo_bot = models.CharField(
        max_length=15, choices=MODOS_BOT, default='ia',
        verbose_name='Modo del bot',
        help_text='Define si la sesión responde con flujo tradicional, agente IA, híbrido o sólo humanos.'
    )
    departamento_default = models.ForeignKey(
        'crm.DepartamentoChatBot', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sesiones_default',
        verbose_name='Departamento de entrada (tradicional)',
        help_text='Flujo que se ejecuta cuando llega un mensaje y no hay match por palabras clave.'
    )
    #IDIOMA
    language = models.CharField('Idioma', max_length=50, choices=LANGUAGES, default='es')
    agente_ia = models.ForeignKey('crm.AgentesIA', on_delete=models.PROTECT, null=True, blank=True)
    desconectado_manualmente = models.BooleanField(
        default=False, verbose_name='Desconectado manualmente',
        help_text='True cuando el usuario desconectó la sesión a propósito. El cron no intentará reconectarla.'
    )

    def is_connected(self):
        return self.estado == 'conectado'

    class Meta:
        verbose_name = 'Sesión WhatsApp'
        verbose_name_plural = 'Sesiones WhatsApp'

    def __str__(self):
        return f"{self.numero} - {self.nombre} | {self.estado}"

    def is_empty_session(self):
        from django.utils import timezone
        if not self.numero and self.contacts_length == 0:
            tiempo_transcurrido = timezone.now() - self.fecha_registro
            return tiempo_transcurrido.total_seconds() > 900  # 15 minutos
        return False

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
        # Limpiar espacios en blanco de los mensajes
        self.mensaje_bienvenida = remover_espacios_de_mas(self.mensaje_bienvenida)
        self.mensaje_despedida = remover_espacios_de_mas(self.mensaje_despedida)
        self.mensaje_handoff = remover_espacios_de_mas(self.mensaje_handoff)
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

    def get_foto_gris(self):
        try:
            if not self.contacto_foto:
                inicial = self.contacto_nombre[0].upper() if self.contacto_nombre else ''
                if inicial and inicial.isalpha():
                    return f"/static/images/initials/gris/{inicial}.png"
                return "/static/foto_defaultd.png"
            return self.contacto_foto
        except Exception:
            return "/static/foto_defaultd.png"

    def get_estado_color(self):
        if self.estado == 'activo':
            return 'success'
        elif self.estado == 'cerrado':
            return 'danger'
        return 'default'  # Por si acaso hay otro valor inesperado

    def __str__(self):
        return f"{self.contacto_numero} ({self.sesion.numero})"

    def get_mensajes_programados(self):
        return self.mensajes_programados.filter(status=True, enviado=False)

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


ESTADOS_CLASIFICACION = (
    (0, 'Sin Clasificar'),
    (1, 'Lead'),
    (2, 'Prospecto'),
    (3, 'Oportunidad'),
    (4, 'Cliente'),
    (5, 'No Interesado')
)

ESTADOS_CONVERSACION = (
    (0, 'Activo'),
    (1, 'Cerrado'),
)

ESTADO_MENSAJE_CHOICES = (
    ("MENU_DEPARTAMENTOS", "Menú Departamentos"),
    ("DEPARTAMENTO_ESCOGIDO", "Departamento Escogido"),
    ("OPCION_ESCOGIDA", "Opción Escogida"),
)

SENTIMIENTO_CHOICES = (
    ('muy_positiva', 'Muy positiva'),
    ('positiva', 'Positiva'),
    ('neutral', 'Neutral'),
    ('tibia', 'Tibia'),
    ('pasiva', 'Pasiva'),
    ('negativa', 'Negativa'),
    ('agresiva', 'Agresiva'),
)

SENTIMIENTO_EMOJI = {
    'muy_positiva': '😊', 'positiva': '🙂', 'neutral': '😐',
    'tibia': '😑', 'pasiva': '😶', 'negativa': '😕', 'agresiva': '😠',
}

SENTIMIENTO_COLOR = {
    'muy_positiva': 'success', 'positiva': 'success', 'neutral': 'secondary',
    'tibia': 'warning', 'pasiva': 'warning', 'negativa': 'danger', 'agresiva': 'danger',
}


class ConversacionWhatsApp(ModeloBase):
    objects = ConversacionWhatsAppManager()
    hashed_id = models.TextField(default='', verbose_name='ID encriptado', blank=True, null=True)
    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE, verbose_name='Contacto', related_name='conversaciones')
    order = models.PositiveIntegerField(default=0, verbose_name='Orden')
    bienvenida_enviado = models.BooleanField('Bienvenida Enviado', default=False)
    despedida_enviado = models.BooleanField('Despedida Enviado', default=False)
    # Campos para la gestión de la conversación
    clasificacion = models.IntegerField(choices=ESTADOS_CLASIFICACION, default=0, verbose_name='Clasificación')
    estado_conversacion = models.IntegerField(choices=ESTADOS_CONVERSACION, default=0, verbose_name='Estado de la conversación')
    # Campos para la gestión de mensajes
    conversacion_finalizada = models.BooleanField('Conversación finalizada', default=False)
    fecha_hora_expira = models.DateTimeField('Fecha y Hora que expira la conversación')
    fecha_fin_conversacion = models.DateTimeField('Fecha y Hora de cierre de la conversación', blank=True, null=True)
    duracion_conversacion = models.DurationField('Duración de la conversación', blank=True, null=True)
    estado_mensaje = models.CharField(
        'Estado actual del Mensaje', max_length=100, choices=ESTADO_MENSAJE_CHOICES, default="MENU_DEPARTAMENTOS"
    )
    memoria_archivo = models.FileField(upload_to='memorias/', blank=True, null=True)
    resumen_conversacion = models.TextField('Resumen de la conversación', blank=True, default='')
    # GenericForeignKey
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    modelo = GenericForeignKey('content_type', 'object_id')
    # ----------------------------------------------------------------
    fromMe = models.BooleanField('¿From Me?', default=False)
    # IA y asignación
    ai_activo = models.BooleanField('Bot activo', default=True)
    asignado_a = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conversaciones_asignadas', verbose_name='Asignado a'
    )
    fecha_asignacion = models.DateTimeField('Fecha de asignación', null=True, blank=True)
    nota_interna = models.TextField('Nota interna', blank=True, default='')
    primer_agente = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conversaciones_iniciadas', verbose_name='Primer agente en responder',
    )
    aprendizaje_procesado = models.BooleanField(
        default=False, verbose_name='Aprendizaje procesado',
        help_text='True cuando el cron ya extrajo pares Q&A de esta conversación para el vectorstore.'
    )
    bloquear_cierre = models.BooleanField(
        'Bloquear cierre automático', default=False,
        help_text='Si está activo, el cron no cerrará esta conversación aunque expire. '
                  'Se ignora cuando el bot IA está activo y la sesión supera su tiempo configurado.'
    )
    # Análisis de sentimiento (calculado al cerrar)
    sentimiento = models.CharField('Sentimiento', max_length=20, choices=SENTIMIENTO_CHOICES, blank=True, default='')
    puntuacion_sentimiento = models.IntegerField('Puntuación (1-10)', null=True, blank=True)

    class Meta:
        verbose_name = 'Conversación WhatsApp'
        verbose_name_plural = 'Conversaciones WhatsApp'
        ordering = ['-order']

    def get_estado_color(self):
        if self.estado == 0:
            return 'success'
        elif self.estado == 1:
            return 'danger'
        return 'default'

    def get_estado_color_conversacion(self):
        if self.conversacion_finalizada:
            return 'danger'
        return 'success'

    def get_sentimiento_emoji(self):
        return SENTIMIENTO_EMOJI.get(self.sentimiento, '')

    def get_sentimiento_color(self):
        return SENTIMIENTO_COLOR.get(self.sentimiento, 'secondary')

    def get_sentimiento_display_full(self):
        emoji = self.get_sentimiento_emoji()
        label = dict(SENTIMIENTO_CHOICES).get(self.sentimiento, '')
        score = f' ({self.puntuacion_sentimiento}/10)' if self.puntuacion_sentimiento else ''
        return f'{emoji} {label}{score}' if label else '—'

    def get_estado_color_clasificacion(self):
        if self.clasificacion == 0:
            return 'secondary'
        elif self.clasificacion == 1:
            return 'info'
        elif self.clasificacion == 2:
            return 'warning'
        elif self.clasificacion == 3:
            return 'primary'
        elif self.clasificacion == 4:
            return 'success'
        elif self.clasificacion == 5:
            return 'danger'
        return 'secondary'

    def traer_ultimo_mensaje(self):
        return self.mensajes.last()

    def resumir_conversacion(self):
        session = self.contacto.sesion
        if not self.resumen_conversacion and session.agente_ia and session.agente_ia.apikey.exists():
            agente = session.agente_ia
            for apikey in agente.apikey.all():
                try:
                    consultor = AgenteResumidor(
                        provider=apikey.proveedor, apikey=apikey.descripcion, conversacion=self
                    )
                    analisis = consultor.analizar_sentimiento()
                    # Guardar sentimiento
                    if analisis.get('sentimiento'):
                        self.sentimiento = analisis['sentimiento']
                        self.puntuacion_sentimiento = analisis.get('puntuacion')
                    # Usar el resumen extendido del análisis si lo tiene, o pedir uno aparte
                    resumen_analisis = analisis.get('resumen', '')
                    if resumen_analisis:
                        self.resumen_conversacion = resumen_analisis
                    else:
                        self.resumen_conversacion = consultor.resumir()
                except Exception:
                    continue
                break
            if not self.resumen_conversacion:
                self.resumen_conversacion = 'SIN RESUMEN'
            super().save()

    def get_foto_gris(self):
        try:
            if not self.contacto.contacto_foto:
                inicial = self.contacto.contacto_nombre[0].upper() if self.contacto.contacto_nombre else ''
                if inicial and inicial.isalpha():
                    return f"/static/images/initials/gris/{inicial}.png"
                return "/static/foto_defaultd.png"
            return self.contacto.contacto_foto
        except Exception:
            return "/static/foto_defaultd.png"

    def get_estado_color(self):
        if self.contacto.estado == 'activo':
            return 'success'
        elif self.contacto.estado == 'cerrado':
            return 'danger'
        return 'default'

    def get_estado_color_conversacion(self):
        if self.estado == 'activo':
            return 'success'
        elif self.estado == 'cerrado':
            return 'danger'
        return 'default'

    def numero_telefono(self):
        return self.contacto.numero_telefono

    def num_mensajes(self):
        return self.mensajes.count()

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

    def cerrar(self, *, enviar_despedida=True, respetar_asignacion_humana=False,
               respetar_bloqueo_cierre=False):
        """
        Cierra la conversación de forma unificada (manual y cronjob).

        Pasos:
          1. resumir_conversacion() — sentimiento + resumen vía IA (idempotente).
          2. Registra fecha_fin_conversacion y duracion_conversacion.
          3. Si enviar_despedida: ejecuta ReglaFinConversacion o, en su defecto,
             envía el mensaje_despedida clásico de la sesión.
          4. Marca despedida_enviado=True (si se envió algo),
             conversacion_finalizada=True y estado_conversacion=1.

        Flags:
          enviar_despedida: si False, no envía mensaje al cliente
                            (equivalente a 'terminar-sin-despedida').
          respetar_asignacion_humana: si True y hay asignado_a, no cierra.
          respetar_bloqueo_cierre: si True y bloquear_cierre=True con ai_activo=False,
                                   no cierra.

        Return: True si se cerró, False si fue saltado o ya estaba cerrada.
        """
        from crm.acciones_fin import ejecutar_acciones_fin
        from crm.models import ReglaFinConversacion
        from whatsapp.services import WhatsAppService

        if self.conversacion_finalizada:
            return False
        if respetar_asignacion_humana and self.asignado_a_id:
            return False
        if respetar_bloqueo_cierre and self.bloquear_cierre and not self.ai_activo:
            return False

        sesion = self.contacto.sesion

        self.resumir_conversacion()

        ahora = timezone.now()
        self.fecha_fin_conversacion = ahora
        if self.fecha_registro:
            self.duracion_conversacion = ahora - self.fecha_registro

        if enviar_despedida:
            regla = ReglaFinConversacion.para_sesion(sesion)
            if regla:
                agente_ia = getattr(sesion, 'agente_ia', None)
                contexto = {
                    'nombre_contacto': self.contacto.contacto_nombre or self.contacto.from_number,
                    'numero': self.contacto.from_number,
                    'sesion': getattr(sesion, 'nombre', str(sesion)),
                    'sesion_id': sesion.session_id,
                    'resumen': self.resumen_conversacion or '',
                    'agente': agente_ia.nombre if agente_ia else '',
                }
                ejecutar_acciones_fin(regla, contexto)
                self.despedida_enviado = True
            elif getattr(sesion, 'mensaje_despedida', None):
                resultado = WhatsAppService().send_text_message(
                    sesion.session_id,
                    self.contacto.from_number,
                    sesion.mensaje_despedida,
                    conversacion_id=self.id,
                    simularEscritura=True,
                )
                if not resultado.get('success'):
                    raise RuntimeError(resultado.get('error', 'Error enviando despedida'))
                self.despedida_enviado = True

        self.conversacion_finalizada = True
        self.estado_conversacion = 1

        self.save(update_fields=[
            'despedida_enviado',
            'conversacion_finalizada',
            'estado_conversacion',
            'fecha_fin_conversacion',
            'duracion_conversacion',
        ])
        return True

    @classmethod
    def obtener_o_crear_activa(cls, contacto):
        """
        Devuelve (conversacion, created). Busca una conversación activa del
        contacto (no expirada, no finalizada, estado 0); si no existe, crea
        una nueva con fecha_hora_expira según session.min_sesion.
        """
        conv = cls.objects.sin_expirar.filter(contacto=contacto).first()
        if conv:
            return conv, False
        min_sesion = int(getattr(contacto.sesion, 'min_sesion', None) or 10)
        conv = cls.objects.create(
            contacto=contacto,
            fecha_hora_expira=timezone.now() + relativedelta(minutes=min_sesion),
        )
        return conv, True


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
    archivo = models.FileField('Archivo', upload_to='whatsapp_media/', blank=True, null=True, max_length=10000)
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
    agente = models.ForeignKey(
        'autenticacion.Usuario', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mensajes_enviados', verbose_name='Agente que respondió'
    )

    # ID externo del mensaje (para poder identificarlo cuando se elimina o edita)
    mensaje_id_externo = models.CharField(max_length=100, blank=True, null=True)
    #IDIOMA
    language = models.CharField('Language', max_length=255, default='')

    @cached_property
    def get_archivo_url(self):
        return self.archivo and self.archivo.url or self.archivo_url or ''

    @cached_property
    def get_archivo_path(self):
        return self.archivo and self.archivo.path or os.path.join(MEDIA_ROOT, self.archivo_url) or ''

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


class HistorialAsignacion(models.Model):
    """Registro de cada vez que una conversación fue asignada a un agente."""
    conversacion = models.ForeignKey(
        ConversacionWhatsApp, on_delete=models.CASCADE, related_name='historial_asignaciones'
    )
    asignado_a = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asignaciones_recibidas', verbose_name='Asignado a'
    )
    asignado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asignaciones_realizadas', verbose_name='Asignado por'
    )
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de asignación')
    nota = models.TextField(blank=True, default='', verbose_name='Nota')

    class Meta:
        verbose_name = 'Historial de asignación'
        verbose_name_plural = 'Historial de asignaciones'
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.conversacion_id} → {self.asignado_a} ({self.fecha:%d/%m/%Y %H:%M})"


class MensajeWhatsAppProgramado(ModeloBase):
    contacto = models.ForeignKey(Contacto, on_delete=models.CASCADE, related_name='mensajes_programados')
    fecha = models.DateField(verbose_name='Fecha de envío programado', blank=True, null=True)
    hora = models.TimeField(verbose_name='Hora de envío programado', blank=True, null=True)
    mensaje = models.TextField(verbose_name='Mensaje a enviar', default='')
    archivo = models.FileField(upload_to='whatsapp_programados/', blank=True, null=True, verbose_name='Archivo adjunto')
    enviado = models.BooleanField(default=False, verbose_name='¿Enviado?')
    fecha_envio = models.DateTimeField(blank=True, null=True, verbose_name='Fecha y hora de envío')
    enviado_por = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Enviado por'
    )

    @cached_property
    def sesion(self):
        return self.contacto.sesion

    @cached_property
    def from_number(self):
        return self.contacto.from_number

    def get_enviado(self):
        return 'text-success fa fa-circle-check' if self.enviado else 'text-danger fa fa-times-circle'

    def __str__(self):
        return f"Mensaje programado para {self.contacto.contacto_nombre} el {self.fecha} a las {self.hora}"

    class Meta:
        verbose_name = 'Mensaje WhatsApp Programado'
        verbose_name_plural = 'Mensajes WhatsApp Programados'


ETAPAS_TRAZA = (
    # Eventos del lado Django (pipeline IA)
    ('webhook_recibido',    'Webhook recibido'),
    ('mensaje_guardado',    'Mensaje guardado en BD'),
    ('ia_desactivada',      'IA desactivada (sin agente o sin API Keys)'),
    ('agente_asignado',     'Agente IA asignado'),
    ('llm_invocado',        'LLM invocado'),
    ('llm_respondio',       'LLM devolvio respuesta'),
    ('llm_error',           'Error invocando LLM'),
    ('mensaje_enviado',     'Respuesta enviada a WhatsApp'),
    ('envio_fallido',       'Envio a WhatsApp fallo'),
    ('sin_respuesta',       'Ningun API Key logro responder'),
    ('error_general',       'Error inesperado en el pipeline'),
    ('fin_conversacion',    'Fin de conversacion detectado'),
    # Eventos del lado Node.js (servicio WhatsApp)
    ('node_mensaje_entrante',  '[Node] Mensaje entrante de WhatsApp'),
    ('node_webhook_disparado', '[Node] Webhook disparado a Django'),
    ('node_envio_intento',     '[Node] Intento de envio a baileys'),
    ('node_envio_exito',       '[Node] Baileys confirmo el envio'),
    ('node_envio_error',       '[Node] Error en baileys al enviar'),
    ('node_ack_recibido',      '[Node] ACK de WhatsApp recibido'),
    ('node_socket_caido',      '[Node] Socket de sesion caido'),
    ('node_reconectando',      '[Node] Reconectando sesion'),
    ('node_rate_limited',      '[Node] Rate limit alcanzado'),
)

NIVELES_TRAZA = (
    ('info',    'Info'),
    ('warning', 'Advertencia'),
    ('error',   'Error'),
    ('success', 'Exito'),
)


class TrazaMensajeIA(models.Model):
    """Registro cronologico de cada paso del pipeline de respuesta IA, para diagnosticar
    por que un mensaje no genero respuesta del bot."""
    sesion = models.ForeignKey(
        SesionWhatsApp, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='trazas', verbose_name='Sesion'
    )
    conversacion = models.ForeignKey(
        'whatsapp.ConversacionWhatsApp', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='trazas', verbose_name='Conversacion'
    )
    mensaje = models.ForeignKey(
        'whatsapp.MensajeWhatsApp', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='trazas', verbose_name='Mensaje'
    )
    numero = models.CharField(max_length=80, blank=True, null=True, db_index=True, verbose_name='Numero')
    etapa = models.CharField(max_length=30, choices=ETAPAS_TRAZA, db_index=True)
    nivel = models.CharField(max_length=10, choices=NIVELES_TRAZA, default='info', db_index=True)
    detalle = models.TextField(blank=True, null=True, verbose_name='Detalle / payload / error')
    latencia_ms = models.PositiveIntegerField(blank=True, null=True, verbose_name='Latencia (ms)')
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Traza de mensaje IA'
        verbose_name_plural = 'Trazas de mensajes IA'
        ordering = ['-fecha', '-id']
        indexes = [
            models.Index(fields=['numero', '-fecha']),
            models.Index(fields=['sesion', '-fecha']),
            models.Index(fields=['conversacion', '-fecha']),
        ]

    def __str__(self):
        return f"[{self.fecha:%Y-%m-%d %H:%M:%S}] {self.get_etapa_display()} ({self.nivel})"

    @property
    def icono(self):
        return {
            'webhook_recibido':  'fa-inbox',
            'mensaje_guardado':  'fa-database',
            'ia_desactivada':    'fa-robot',
            'agente_asignado':   'fa-user-gear',
            'llm_invocado':      'fa-microchip',
            'llm_respondio':     'fa-comment-dots',
            'llm_error':         'fa-triangle-exclamation',
            'mensaje_enviado':   'fa-paper-plane',
            'envio_fallido':     'fa-xmark',
            'sin_respuesta':     'fa-ban',
            'error_general':     'fa-bug',
            'fin_conversacion':  'fa-flag-checkered',
        }.get(self.etapa, 'fa-circle-info')

    @property
    def color(self):
        return {
            'info':    'primary',
            'success': 'success',
            'warning': 'warning',
            'error':   'danger',
        }.get(self.nivel, 'secondary')
        ordering = ['fecha', 'hora']