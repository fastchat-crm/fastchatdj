import json
import os
from email.policy import default
from functools import cached_property

from dateutil.relativedelta import relativedelta
from django.conf.global_settings import LANGUAGES
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.files.base import ContentFile
from django.db import models
from django.db.models import Q
from django.utils import timezone

from agents_ai.agente_resumidor import AgenteResumidor
from core.crypto import EncryptedTextField
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

PROVEEDORES_SESION = (
    ('baileys',   'Baileys (WhatsApp Web)'),
    ('meta',      'Meta Cloud API'),
    ('instagram', 'Instagram DM'),
    ('messenger', 'Facebook Messenger'),
)

CANALES_ORIGEN = (
    ('whatsapp',  'WhatsApp'),
    ('instagram', 'Instagram'),
    ('messenger', 'Messenger'),
    ('otro',      'Otro'),
)

FUENTES_REFERRAL = (
    ('AD',         'Anuncio (CTWA/CTIG)'),
    ('POST',       'Post orgánico'),
    ('PAGE',       'Página'),
    ('BUSINESS',   'Catálogo/Business'),
    ('ORGANIC',    'Orgánico'),
    ('UNKNOWN',    'Desconocido'),
)

MODOS_BOT = (
    ('ninguno',     'Sin bot (sólo humanos)'),
    ('tradicional', 'Chatbot tradicional (flujo/menús/APIs)'),
    ('ia',          'Agente IA'),
)


class SesionWhatsApp(ModeloBase):
    nombre = models.CharField(max_length=150, blank=True, null=True, verbose_name='Nombre')
    numero = models.CharField(max_length=50, verbose_name='Número WhatsApp', default='')
    estado = models.CharField(max_length=20, choices=ESTADOS_SESION, default='pendiente')
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, null=True, blank=True, verbose_name='Asesor asignado')
    ultima_conexion = models.DateTimeField(blank=True, null=True, verbose_name='Última conexión')
    observacion = models.TextField(blank=True, null=True, verbose_name='Observaciones')
    session_id = models.CharField(max_length=255, unique=True, verbose_name='ID externo del proveedor',
                                  help_text='ID externo de la sesión: UUID del proceso Node (Baileys) o sinónimo del phone_number_id (Meta).')
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
    proveedor = models.CharField(
        max_length=20, choices=PROVEEDORES_SESION, default='baileys',
        verbose_name='Proveedor WhatsApp',
        help_text='Define el transporte: Baileys (no oficial, vía Node) o Meta Cloud API (oficial).'
    )
    mensaje_fuera_horario = models.TextField(
        blank=True, null=True, verbose_name='Mensaje fuera de horario',
        help_text='Se envía al contacto cuando escribe fuera del horario de atención configurado.'
    )
    zona_horaria = models.CharField(
        max_length=50, default='America/Guayaquil',
        verbose_name='Zona horaria',
        help_text='TZ database name, ej. America/Guayaquil, America/Bogota, UTC.'
    )
    auto_asignar_round_robin = models.BooleanField(
        'Auto-asignar a agentes (round-robin)', default=False,
        help_text='Al entrar una conversación sin agente, asignarla automáticamente al próximo agente disponible.'
    )
    pixel_meta = models.ForeignKey(
        'whatsapp.PixelMeta', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sesiones_vinculadas', verbose_name='Pixel Meta (CAPI)',
        help_text='Pixel al que se reportan conversiones de esta sesión.'
    )
    activo = models.BooleanField(
        'Sesión activa', default=True, db_index=True,
        help_text='Si está apagada, la sesión no procesa mensajes entrantes ni envía respuestas (corta consumo de API y costos del modelo IA). Útil para suspender el servicio de un cliente sin eliminar la sesión.'
    )

    @property
    def es_meta(self):
        return self.proveedor == 'meta'

    @property
    def es_baileys(self):
        return self.proveedor == 'baileys'

    @property
    def es_instagram(self):
        return self.proveedor == 'instagram'

    @property
    def es_messenger(self):
        return self.proveedor == 'messenger'

    def is_connected(self):
        return self.estado == 'conectado'

    def convs_del_mes(self):
        mes_ini = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return ConversacionWhatsApp.objects.filter(
            status=True,
            contacto__sesion=self,
            fecha_registro__gte=mes_ini,
        ).count()

    class Meta:
        verbose_name = 'Sesión WhatsApp'
        verbose_name_plural = 'Sesiones WhatsApp'

    def __str__(self):
        return f"{self.numero} - {self.nombre} | {self.estado}"

    def is_empty_session(self):
        from django.utils import timezone
        cb = getattr(self, 'config_baileys', None)
        contacts_length = cb.contacts_length if cb else 0
        if not self.numero and contacts_length == 0:
            tiempo_transcurrido = timezone.now() - self.fecha_registro
            return tiempo_transcurrido.total_seconds() > 900  # 15 minutos
        return False

    def save(self, *args, **kwargs):
        if self.estado == 'conectado':
            self.ultima_conexion = timezone.now()
        else:
            self.ultima_conexion = None
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
    # Etiquetas libres (tags) y canal de origen
    etiquetas = models.ManyToManyField(
        'whatsapp.EtiquetaContacto', blank=True, related_name='contactos',
        verbose_name='Etiquetas',
    )
    canal = models.CharField(
        max_length=20, choices=CANALES_ORIGEN, default='whatsapp',
        verbose_name='Canal', db_index=True,
        help_text='Canal por el que entró el contacto: whatsapp/instagram/messenger.'
    )
    # Identidad externa multi-canal: permite deduplicar el mismo usuario que
    # contacta por IG + WhatsApp. Lo llena el webhook respectivo.
    external_id = models.CharField(
        max_length=120, blank=True, null=True, db_index=True,
        verbose_name='ID externo',
        help_text='IGSID / PSID / wa_id según canal.'
    )
    # Identidad cross-app de Meta (formato "EC.xxxxx"). Meta lo manda en
    # contacts[].user_id en algunos eventos. A diferencia de wa_id (que es
    # el número), este ID es el mismo si el usuario contacta por WA + IG +
    # Messenger desde la misma cuenta. Útil para deduplicación y atribución
    # CAPI. Solo aplica a sesiones Meta Cloud API.
    meta_user_id = models.CharField(
        max_length=80, blank=True, null=True, db_index=True,
        verbose_name='Meta User ID',
        help_text='Identidad cross-app del usuario en Meta (EC.xxx). Solo Meta Cloud.'
    )
    # Referral de Click-to-WhatsApp ads. Meta lo manda cuando el contacto
    # entra por primera vez desde un anuncio. Estructura típica:
    #   {source_id, source_url, source_type, headline, body,
    #    media_type, media_url, ctwa_clid, thumbnail_url}
    # Lo guardamos completo en JSON para reportes de atribución posteriores.
    referral_meta = models.JSONField(
        blank=True, null=True,
        verbose_name='Referral Meta (CTWA)',
        help_text='Datos del Click-to-WhatsApp ad por el que entró el contacto.'
    )

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


class PerfilContacto(ModeloBase):
    """Memoria persistente cruzada entre conversaciones para un Contacto.

    Se construye/actualiza cuando se cierra una conversación (cron
    `aprender_conversaciones`). Se inyecta como contexto extra en futuras
    conversaciones vía la variable `{historial_contacto}` del prompt, para que
    el bot reconozca al cliente recurrente sin tener que releer todo el historial.
    """
    contacto = models.OneToOneField(
        Contacto, on_delete=models.CASCADE, related_name='perfil_persistente',
        verbose_name='Contacto',
    )
    resumen = models.TextField(
        blank=True, default='',
        verbose_name='Resumen persistente',
        help_text='Ventana rodante del historial del cliente: últimos N resúmenes de conversaciones cerradas.'
    )
    intereses_json = models.JSONField(
        default=dict, blank=True,
        verbose_name='Intereses y patrones',
        help_text='Estructura libre. Ej: {"productos_favoritos": ["pizza napolitana"], "horario_comun": "noche"}.'
    )
    total_conversaciones = models.PositiveIntegerField(
        default=0, verbose_name='Total conversaciones procesadas',
    )
    ultima_interaccion = models.DateTimeField(
        null=True, blank=True, verbose_name='Última interacción'
    )
    fecha_ultimo_resumen = models.DateTimeField(
        null=True, blank=True, verbose_name='Fecha del último resumen',
    )

    # Cap de la ventana rodante — chars. Más de esto trunca desde el inicio.
    VENTANA_CHARS = 3000

    class Meta:
        verbose_name = 'Perfil persistente de contacto'
        verbose_name_plural = 'Perfiles persistentes de contactos'

    def __str__(self):
        return f"Perfil {self.contacto_id} ({self.total_conversaciones} conv)"

    def agregar_resumen(self, texto_resumen: str, fecha=None) -> None:
        """Anexa un resumen nuevo a la ventana rodante, trunca desde el inicio
        si excede VENTANA_CHARS. Pensado para correr al cierre de conversación.
        """
        texto_resumen = (texto_resumen or '').strip()
        if not texto_resumen:
            return
        fecha = fecha or timezone.now()
        entrada = f"[{fecha.strftime('%Y-%m-%d')}] {texto_resumen}".strip()
        base = (self.resumen or '').strip()
        nuevo = f"{base}\n{entrada}".strip() if base else entrada
        # Rolling window: si excede, tirar desde el inicio hasta caber.
        if len(nuevo) > self.VENTANA_CHARS:
            exceso = len(nuevo) - self.VENTANA_CHARS
            nuevo = nuevo[exceso:].lstrip('\n')
            # Asegurar que arranque en una línea completa
            if '\n' in nuevo:
                nuevo = nuevo[nuevo.find('\n') + 1:]
        self.resumen = nuevo
        self.total_conversaciones = (self.total_conversaciones or 0) + 1
        self.ultima_interaccion = fecha
        self.fecha_ultimo_resumen = fecha
        self.save(update_fields=[
            'resumen', 'total_conversaciones', 'ultima_interaccion',
            'fecha_ultimo_resumen', 'fecha_modificacion',
        ])


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

    # Atribución de campaña (Click-to-WhatsApp / Click-to-Instagram ads).
    # Se llena al recibir el primer mensaje de una conversación si el payload
    # Meta trae bloque `referral` (o el homólogo en Instagram Graph API).
    origen_canal = models.CharField(
        'Canal de origen', max_length=20, choices=CANALES_ORIGEN,
        default='whatsapp', db_index=True,
    )
    referral_source_type = models.CharField(
        'Tipo de fuente referral', max_length=20, choices=FUENTES_REFERRAL,
        blank=True, default='', db_index=True,
    )
    ctwa_clid = models.CharField(
        'CTWA click ID', max_length=300, blank=True, null=True, db_index=True,
        help_text='Click-to-WhatsApp/IG click ID que envía Meta. Usar como event_id en CAPI.'
    )
    ad_id = models.CharField('Ad ID', max_length=100, blank=True, null=True, db_index=True)
    adset_id = models.CharField('Adset ID', max_length=100, blank=True, null=True, db_index=True)
    campaign_id = models.CharField('Campaign ID', max_length=100, blank=True, null=True, db_index=True)
    referral_source_url = models.URLField('URL fuente', max_length=1000, blank=True, null=True)
    referral_headline = models.CharField('Titular referral', max_length=500, blank=True, null=True)
    referral_body = models.TextField('Cuerpo referral', blank=True, null=True)
    referral_medium = models.CharField('Media type referral', max_length=20, blank=True, null=True)
    referral_payload_json = models.JSONField('Payload referral crudo', null=True, blank=True)
    # Fuente de campaña interna (broadcast desde el propio CRM). Enlaza con EnvioCampana
    campana_origen = models.ForeignKey(
        'whatsapp.Campana', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conversaciones_generadas', verbose_name='Campaña origen',
    )
    # CAPI: marca si ya se envió el evento Lead/Purchase al pixel
    capi_lead_enviado = models.BooleanField('Lead reportado a CAPI', default=False)
    capi_purchase_enviado = models.BooleanField('Purchase reportado a CAPI', default=False)

    # Snapshot del proveedor al momento de atender la conversacion. Se congela
    # porque la sesion puede migrar de proveedor luego (ej. Baileys -> Meta) y
    # el historial debe reflejar con que servicio se atendio originalmente.
    proveedor_atencion = models.CharField(
        'Proveedor de atencion', max_length=20, choices=PROVEEDORES_SESION,
        blank=True, default='', db_index=True,
        help_text='Servicio con el que se atendio esta conversacion (baileys/meta/etc). Se congela al crearla.'
    )

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
                        provider=apikey.proveedor, apikey=apikey.descripcion, conversacion=self,
                        apikey_obj=apikey, agente_obj=agente,
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
    def mensajes_no_leidos(self):
        # Mensajes entrantes del contacto aun sin marcar como leidos. Se usa
        # en el listado solo para conversaciones abiertas; las finalizadas
        # no muestran badge (no hay "pendiente" que atender).
        return self.mensajes.filter(leido=False, remitente=self.contacto_numero).count()

    @cached_property
    def sesion(self):
        return self.contacto.sesion

    @cached_property
    def sesion_id(self):
        return self.contacto.sesion_id

    @cached_property
    def proveedor_efectivo(self):
        """Proveedor con el que se atendio la conversacion.
        Usa el snapshot `proveedor_atencion` si esta seteado (conversaciones
        nuevas); si no, cae al proveedor actual de la sesion (conversaciones
        anteriores a la migracion). Siempre preferir este helper sobre
        `sesion.proveedor` para renderizar badges — no cambia aunque la
        sesion migre de transporte despues."""
        return self.proveedor_atencion or getattr(self.sesion, 'proveedor', '') or ''

    @property
    def atendida_por_meta(self):
        return self.proveedor_efectivo == 'meta'

    @property
    def atendida_por_baileys(self):
        return self.proveedor_efectivo == 'baileys'

    @property
    def atendida_por_instagram(self):
        return self.proveedor_efectivo == 'instagram'

    @property
    def atendida_por_messenger(self):
        return self.proveedor_efectivo == 'messenger'

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
             envía el mensaje_despedida clásico de la sesión. Crea
             MensajeWhatsApp local + TrazaMensajeIA para que el envío quede
             en el historial de la conversación y en /whatsapp/trazas/.
          4. Marca despedida_enviado=True (si se envió algo),
             conversacion_finalizada=True y estado_conversacion=1.
          5. Siempre deja una traza 'fin_conversacion' indicando qué pasó
             con la despedida (enviada / fallida / omitida).

        Comportamiento ante fallo de envío: NO bloquea el cierre. Logueamos
        la falla y cerramos igual — la conversación queda cerrada, y el
        operador puede ver en las trazas por qué la despedida no llegó.

        Flags:
          enviar_despedida: si False, no envía mensaje al cliente.
          respetar_asignacion_humana: si True y hay asignado_a, no cierra.
          respetar_bloqueo_cierre: si True y bloquear_cierre=True con ai_activo=False,
                                   no cierra.

        Return: True si se cerró, False si fue saltado o ya estaba cerrada.
        """
        import logging as _logging
        from crm.acciones_fin import ejecutar_acciones_fin
        from crm.models import ReglaFinConversacion
        from whatsapp.services import get_whatsapp_service

        _log = _logging.getLogger(__name__)

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

        # Estado del flujo de despedida (para la traza final).
        despedida_estado = 'omitida'   # omitida | enviada | fallida
        despedida_detalle = ''
        despedida_error = ''

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
                try:
                    ejecutar_acciones_fin(regla, contexto)
                    self.despedida_enviado = True
                    despedida_estado = 'enviada'
                    despedida_detalle = f'regla_id={regla.id} acciones_ejecutadas'
                except Exception as ex:
                    _log.exception("ReglaFinConversacion fallo en cerrar()")
                    despedida_estado = 'fallida'
                    despedida_error = f'regla_id={regla.id}: {ex}'

            elif getattr(sesion, 'mensaje_despedida', None):
                texto_despedida = sesion.mensaje_despedida
                try:
                    resultado = get_whatsapp_service(sesion).send_text_message(
                        sesion.session_id,
                        self.contacto.from_number,
                        texto_despedida,
                        conversacion_id=self.id,
                        simularEscritura=True,
                    )
                except Exception as ex:
                    resultado = {'success': False, 'error': str(ex)}

                if resultado.get('success'):
                    self.despedida_enviado = True
                    despedida_estado = 'enviada'
                    despedida_detalle = f"message_id={resultado.get('message_id', '')}"
                    # Crear MensajeWhatsApp local para que aparezca en el
                    # historial de la conversación. Para Meta es la única
                    # vía (no hay webhook que lo cree). Para Baileys, Node
                    # podría emitir message_sent — usamos
                    # mensaje_id_externo único para que el handler ignore
                    # el duplicado si llega después.
                    try:
                        msg_id_ext = resultado.get('message_id') or ''
                        ya_existe = (
                            msg_id_ext
                            and MensajeWhatsApp.objects
                                .filter(conversacion=self, mensaje_id_externo=msg_id_ext)
                                .exists()
                        )
                        if not ya_existe:
                            MensajeWhatsApp.objects.create(
                                conversacion=self,
                                remitente=sesion.numero or '',
                                mensaje=texto_despedida,
                                tipo='texto',
                                fecha=timezone.now(),
                                leido=True,
                                fecha_leido=timezone.now(),
                                es_automatico=True,
                                ia_generado=False,
                                mensaje_id_externo=msg_id_ext,
                                estado_envio='enviado',
                            )
                    except Exception:
                        _log.exception("No pude persistir MensajeWhatsApp de despedida")
                else:
                    despedida_estado = 'fallida'
                    despedida_error = str(resultado.get('error', 'Error desconocido'))[:500]
                    _log.warning(
                        "Despedida no enviada para conv=%s sesion=%s: %s",
                        self.id, sesion.session_id, despedida_error,
                    )
            else:
                despedida_detalle = 'sin regla y sin mensaje_despedida configurado'

        # Cerrar SIEMPRE — no bloqueamos por fallo de envío. La traza
        # registra qué pasó para que el operador pueda revisar.
        self.conversacion_finalizada = True
        self.estado_conversacion = 1

        self.save(update_fields=[
            'despedida_enviado',
            'conversacion_finalizada',
            'estado_conversacion',
            'fecha_fin_conversacion',
            'duracion_conversacion',
        ])

        # Traza final — visible en /whatsapp/trazas/ filtrando por
        # etapa=fin_conversacion. Imprescindible para que el operador
        # pueda diagnosticar por qué un cliente no recibió despedida.
        try:
            partes = [f'estado_despedida={despedida_estado}']
            if not enviar_despedida:
                partes.append('flag_enviar_despedida=False')
            if despedida_detalle:
                partes.append(despedida_detalle)
            if despedida_error:
                partes.append(f'error={despedida_error}')
            partes.append(f'transporte={getattr(sesion, "proveedor", "?")}')
            nivel = 'error' if despedida_estado == 'fallida' else (
                'success' if despedida_estado == 'enviada' else 'info'
            )
            TrazaMensajeIA.objects.create(
                sesion=sesion,
                conversacion=self,
                numero=self.contacto.from_number or '',
                etapa='fin_conversacion',
                nivel=nivel,
                detalle=' | '.join(partes)[:4000],
            )
        except Exception:
            _log.exception("No pude registrar traza fin_conversacion")

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
        proveedor_snapshot = getattr(contacto.sesion, 'proveedor', '') or ''
        conv = cls.objects.create(
            contacto=contacto,
            fecha_hora_expira=timezone.now() + relativedelta(minutes=min_sesion),
            proveedor_atencion=proveedor_snapshot,
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

    # Estado de envío (salientes). Meta lo actualiza via ACK webhook;
    # Baileys puede hacerlo si alguna vez exponemos message_ack del Node.
    # Vacío '' = no aplica (mensaje entrante del cliente).
    ESTADO_ENVIO_CHOICES = (
        ('pendiente', 'Pendiente'),
        ('enviado',   'Enviado'),
        ('entregado', 'Entregado'),
        ('leido',     'Leído'),
        ('fallido',   'Fallido'),
    )
    estado_envio = models.CharField(
        max_length=15, choices=ESTADO_ENVIO_CHOICES, default='', blank=True,
    )
    error_envio = models.TextField(blank=True, null=True)
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


class MenuRapidoSesion(ModeloBase):
    """Menú de respuesta rápida configurable por sesión.

    El operador define menús reutilizables (ej. "Catálogo", "Horarios",
    "Pago"). Cuando está atendiendo una conversación, hace click en el chip
    del menú y se envía como Meta interactive button-list (≤3 botones) o
    interactive list (≤10 ítems). En Baileys cae a texto numerado.

    Cada `MenuRapidoSesion.opciones` es una lista de dicts:
        [{"etiqueta": "Ver precios", "valor": "ver_precios"}, ...]
    El `valor` es lo que llega como `button_reply.id` cuando el cliente toca.
    """
    sesion = models.ForeignKey(
        SesionWhatsApp, on_delete=models.CASCADE,
        related_name='menus_rapidos', verbose_name='Sesión',
    )
    nombre = models.CharField('Nombre del menú', max_length=80,
                              help_text='Etiqueta del chip que ve el operador (ej. Catálogo, Horarios).')
    color = models.CharField('Color del chip', max_length=20, default='#16a34a',
                             help_text='Hex del badge en la barra (ej. #16a34a).')
    cuerpo = models.TextField('Cuerpo del mensaje', default='',
                              help_text='Texto que acompaña los botones (≤1024 chars en Meta).')
    header = models.CharField('Header (opcional)', max_length=60, blank=True, default='',
                              help_text='Línea superior del menú interactivo (≤60 chars Meta).')
    footer = models.CharField('Footer (opcional)', max_length=60, blank=True, default='',
                              help_text='Línea inferior del menú interactivo (≤60 chars Meta).')
    opciones = models.JSONField('Opciones (lista de botones)', default=list, blank=True,
                                help_text='[{"etiqueta": "Texto botón", "valor": "id_opt"}, ...]. Máx 10.')

    class Meta:
        verbose_name = 'Menú rápido de sesión'
        verbose_name_plural = 'Menús rápidos de sesión'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.sesion_id} · {self.nombre}'


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
    # Eventos del webservice externo (/api/ia/consultar/)
    ('ws_request',      '[WS] Solicitud recibida'),
    ('ws_respuesta',    '[WS] Respuesta entregada'),
    ('ws_sin_agente',   '[WS] Agente no encontrado'),
    ('ws_error',        '[WS] Error procesando solicitud'),
    # Eventos del chatbot tradicional (motor de flujo)
    ('chatbot_ruteo',   '[Chatbot] Ruteo a departamento'),
    ('chatbot_http',    '[Chatbot] Llamada HTTP del flujo'),
    ('chatbot_nodo',    '[Chatbot] Transición de nodo'),
    ('chatbot_error',   '[Chatbot] Error en el flujo'),
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
    apikey = models.ForeignKey(
        'crm.ApiKeyIA', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='trazas', verbose_name='Api Key / Token WS',
        help_text='Solo lo llena el pipeline del webservice externo.'
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
            models.Index(fields=['apikey', '-fecha']),
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
            'ws_request':        'fa-cloud-arrow-down',
            'ws_respuesta':      'fa-cloud-arrow-up',
            'ws_sin_agente':     'fa-user-slash',
            'ws_error':          'fa-plug-circle-xmark',
        }.get(self.etapa, 'fa-circle-info')

    @property
    def color(self):
        return {
            'info':    'primary',
            'success': 'success',
            'warning': 'warning',
            'error':   'danger',
        }.get(self.nivel, 'secondary')


# ============================================================================
# Modelos especificos de Baileys (WhatsApp Web)
# ============================================================================


class ConfigBaileys(ModeloBase):
    """Configuracion y estado runtime de una sesion Baileys (via Node.js).

    Existe solo cuando la sesion tiene proveedor='baileys'. Contiene los
    campos que antes vivian en SesionWhatsApp pero solo aplicaban al
    transporte Baileys."""
    sesion = models.OneToOneField(
        SesionWhatsApp, on_delete=models.CASCADE,
        related_name='config_baileys', verbose_name='Sesión'
    )
    qr_code = models.TextField(
        blank=True, null=True, verbose_name='Código QR actual (Base64)'
    )
    whatsapp_id = models.CharField(
        max_length=250, default='', blank=True, verbose_name='WhatsApp ID'
    )
    desconectado_manualmente = models.BooleanField(
        default=False, verbose_name='Desconectado manualmente',
        help_text='True cuando el usuario desconectó la sesión a propósito. El cron no intentará reconectarla.'
    )
    contacts_list = models.TextField(
        default='[]', verbose_name='Lista de Contactos'
    )
    contacts_length = models.PositiveIntegerField(
        default=0, verbose_name='Cantidad de contactos'
    )
    foto = models.TextField(
        blank=True, null=True, verbose_name='Foto'
    )
    fecha_expira_inactivo = models.DateTimeField(
        default=default_expira_10_min, verbose_name='Fecha de expiración por inactividad'
    )
    error_mensaje = models.TextField(
        blank=True, null=True, verbose_name='Último error'
    )

    class Meta:
        verbose_name = 'Configuración Baileys'
        verbose_name_plural = 'Configuraciones Baileys'

    def __str__(self):
        return f"Baileys · {self.sesion.numero or self.sesion.session_id}"


# ============================================================================
# Modelos especificos de Meta Cloud API
# ============================================================================

QUALITY_RATING_META = (
    ('GREEN',   'Alta'),
    ('YELLOW',  'Media'),
    ('RED',     'Baja'),
    ('UNKNOWN', 'Desconocida'),
)

MESSAGING_LIMIT_TIER = (
    ('TIER_50',        '50 conversaciones/día'),
    ('TIER_250',       '250 conversaciones/día'),
    ('TIER_1K',        '1.000 conversaciones/día'),
    ('TIER_10K',       '10.000 conversaciones/día'),
    ('TIER_100K',      '100.000 conversaciones/día'),
    ('TIER_UNLIMITED', 'Ilimitado'),
)


class ConfigMeta(ModeloBase):
    """Configuracion Meta Cloud API por sesion. OneToOne con SesionWhatsApp.

    Existe solo cuando la sesion tiene proveedor='meta'. Contiene credenciales
    y metadata que solo aplica a este transporte."""
    sesion = models.OneToOneField(
        SesionWhatsApp, on_delete=models.CASCADE,
        related_name='config_meta', verbose_name='Sesion'
    )

    # Identificadores Meta
    waba_id = models.CharField(
        max_length=100, db_index=True,
        verbose_name='WhatsApp Business Account ID',
        help_text='ID de la cuenta WABA en Meta. Una WABA puede contener varios numeros.'
    )
    phone_number_id = models.CharField(
        max_length=100, unique=True,
        verbose_name='Phone Number ID',
        help_text='ID del numero especifico en Meta. Usado como routing ID para enviar mensajes.'
    )
    business_account_id = models.CharField(
        max_length=100, blank=True, null=True,
        verbose_name='Business Account ID (opcional)'
    )
    display_phone_number = models.CharField(
        max_length=30, blank=True, null=True,
        verbose_name='Numero visible',
        help_text='Numero formateado tal como Meta lo muestra (+593 99 999 9999).'
    )
    verified_name = models.CharField(
        max_length=100, blank=True, null=True,
        verbose_name='Nombre verificado',
        help_text='Nombre del negocio verificado por Meta. Se sincroniza desde Graph.'
    )

    # Credenciales (cifradas en BD via Fernet — transparente en Python).
    # Las credenciales App-level (app_id, app_secret) viven en
    # seguridad.CredencialMetaApp (singleton por organizacion).
    access_token = EncryptedTextField(
        verbose_name='System User Access Token',
        help_text='Token long-lived emitido por Meta. Se guarda cifrado.'
    )

    # Webhook
    webhook_verify_token = models.CharField(
        max_length=60,
        verbose_name='Verify token del webhook',
        help_text='Token auto-generado que el cliente copia al configurar el webhook en Meta.'
    )
    webhook_verificado_en = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Webhook verificado en'
    )

    # Estado reportado por Meta
    quality_rating = models.CharField(
        max_length=20, choices=QUALITY_RATING_META, default='UNKNOWN',
        verbose_name='Quality rating'
    )
    messaging_limit_tier = models.CharField(
        max_length=30, choices=MESSAGING_LIMIT_TIER, blank=True, null=True,
        verbose_name='Limite de mensajeria'
    )
    business_verification_status = models.CharField(
        max_length=30, blank=True, null=True,
        verbose_name='Estado de verificacion del negocio'
    )

    # Foto de perfil (cache local). Meta no devuelve la foto en consultas
    # normales — la obtenemos solo cuando el operador la sube desde el panel.
    # Guardamos data: URL base64 para mostrarla en el avatar del card sin
    # depender de URLs de Meta (que pueden expirar). Mismo nombre `foto` que
    # ConfigBaileys.foto para mantener convención cross-transporte.
    foto = models.TextField(
        blank=True, null=True, verbose_name='Foto de perfil',
        help_text='Cache local (data URL base64) de la última foto subida. Vacío hasta que el operador suba una.'
    )

    # Auditoria
    ultima_sincronizacion = models.DateTimeField(null=True, blank=True)
    alta_manual = models.BooleanField(
        default=False,
        verbose_name='¿Alta manual (sin Embedded Signup)?',
        help_text='True si la sesión se conectó cargando los IDs a mano '
                  '(modo previo a Tech Provider). False si pasó por el popup OAuth.'
    )

    class Meta:
        verbose_name = 'Configuracion Meta'
        verbose_name_plural = 'Configuraciones Meta'

    def __str__(self):
        return f"Meta · WABA {self.waba_id} · {self.display_phone_number or self.phone_number_id}"


CATEGORIAS_PLANTILLA = (
    ('UTILITY',        'Utilidad'),
    ('MARKETING',      'Marketing'),
    ('AUTHENTICATION', 'Autenticacion'),
)

ESTADOS_PLANTILLA_META = (
    ('BORRADOR',  'Borrador (no enviada a Meta)'),
    ('PENDING',   'Pendiente de aprobacion'),
    ('APPROVED',  'Aprobada'),
    ('REJECTED',  'Rechazada'),
    ('PAUSED',    'Pausada'),
    ('DISABLED',  'Deshabilitada'),
)

HEADER_TIPOS_PLANTILLA = (
    ('NONE',     'Sin encabezado'),
    ('TEXT',     'Texto'),
    ('IMAGE',    'Imagen'),
    ('VIDEO',    'Video'),
    ('DOCUMENT', 'Documento'),
)


class PlantillaWhatsApp(ModeloBase):
    """Plantilla de mensaje pre-aprobada por Meta.

    Necesaria para iniciar conversaciones fuera de la ventana de 24h o para
    enviar contenido promocional. Se administra via API de Meta y su estado
    se sincroniza con esta tabla."""
    config_meta = models.ForeignKey(
        ConfigMeta, on_delete=models.CASCADE,
        related_name='plantillas', verbose_name='Configuracion Meta'
    )

    # Identidad
    nombre = models.CharField(
        max_length=512,
        verbose_name='Nombre',
        help_text='Slug en minusculas con guiones bajos. Ej: confirmacion_cita.'
    )
    idioma = models.CharField(
        max_length=10, default='es',
        verbose_name='Idioma',
        help_text='Codigo ISO que espera Meta. Ej: es, es_MX, en_US.'
    )
    categoria = models.CharField(
        max_length=20, choices=CATEGORIAS_PLANTILLA,
        verbose_name='Categoria Meta'
    )

    # Contenido
    header_tipo = models.CharField(
        max_length=20, choices=HEADER_TIPOS_PLANTILLA, default='NONE',
        verbose_name='Tipo de encabezado'
    )
    header_contenido = models.TextField(
        blank=True, null=True,
        verbose_name='Contenido del encabezado',
        help_text='Texto con {{1}}, o URL de imagen/video/documento segun tipo.'
    )
    cuerpo = models.TextField(
        verbose_name='Cuerpo',
        help_text='Texto principal. Usa {{1}}, {{2}} para variables.'
    )
    footer = models.CharField(
        max_length=60, blank=True, null=True,
        verbose_name='Pie (opcional)'
    )
    botones_json = models.JSONField(
        default=list, blank=True,
        verbose_name='Botones',
        help_text='Lista de botones. Cada uno: {"type": "URL|QUICK_REPLY|PHONE_NUMBER", "text": "...", "url": "..."}'
    )
    variables_json = models.JSONField(
        default=list, blank=True,
        verbose_name='Variables',
        help_text='Metadata de cada placeholder. Ej: [{"nombre": "cliente", "ejemplo": "Hector"}]'
    )

    # Estado Meta
    id_meta = models.CharField(
        max_length=100, blank=True, null=True,
        verbose_name='ID en Meta',
        help_text='ID que devuelve Meta al crear la plantilla.'
    )
    estado_meta = models.CharField(
        max_length=20, choices=ESTADOS_PLANTILLA_META, default='BORRADOR',
        verbose_name='Estado en Meta'
    )
    motivo_rechazo = models.TextField(blank=True, null=True, verbose_name='Motivo de rechazo')
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    ultima_sincronizacion = models.DateTimeField(null=True, blank=True)

    # Uso
    veces_enviada = models.PositiveIntegerField(default=0, verbose_name='Veces enviada')
    ultimo_envio = models.DateTimeField(null=True, blank=True, verbose_name='Ultimo envio')

    class Meta:
        verbose_name = 'Plantilla WhatsApp'
        verbose_name_plural = 'Plantillas WhatsApp'
        unique_together = [('config_meta', 'nombre', 'idioma')]
        ordering = ['-fecha_modificacion', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.idioma}) · {self.get_estado_meta_display()}"

    @property
    def aprobada(self):
        return self.estado_meta == 'APPROVED'

    @property
    def color_estado(self):
        return {
            'BORRADOR': 'secondary',
            'PENDING':  'warning',
            'APPROVED': 'success',
            'REJECTED': 'danger',
            'PAUSED':   'info',
            'DISABLED': 'dark',
        }.get(self.estado_meta, 'secondary')


class TarifaPlantillaMeta(ModeloBase):
    pais = models.CharField(
        max_length=2, default='EC',
        verbose_name='Pais (ISO-3166 alpha-2)',
        help_text='Codigo ISO de 2 letras. Ej: EC, MX, CO, PE, US.'
    )
    categoria = models.CharField(
        max_length=20, choices=CATEGORIAS_PLANTILLA,
        verbose_name='Categoria Meta'
    )
    precio = models.DecimalField(
        max_digits=10, decimal_places=6,
        verbose_name='Precio por mensaje',
        help_text='Costo unitario por mensaje de plantilla. Ej: 0.0626 para Marketing en Ecuador.'
    )
    moneda = models.CharField(
        max_length=3, default='USD',
        verbose_name='Moneda',
        help_text='ISO-4217. Por defecto USD (Meta factura en USD).'
    )
    vigencia_desde = models.DateField(
        verbose_name='Vigente desde',
        help_text='Fecha desde la cual aplica este precio.'
    )
    vigencia_hasta = models.DateField(
        null=True, blank=True,
        verbose_name='Vigente hasta',
        help_text='Vacio = vigente indefinidamente. Se llena cuando Meta cambia precios.'
    )
    notas = models.TextField(
        blank=True, null=True,
        verbose_name='Notas',
        help_text='Observaciones internas sobre esta tarifa.'
    )

    class Meta:
        verbose_name = 'Tarifa Plantilla Meta'
        verbose_name_plural = 'Tarifas Plantillas Meta'
        ordering = ['pais', 'categoria', '-vigencia_desde']
        indexes = [
            models.Index(fields=['pais', 'categoria', 'vigencia_desde']),
        ]

    def __str__(self):
        return f"{self.pais} · {self.get_categoria_display()} · {self.precio} {self.moneda}"

    @staticmethod
    def vigente(pais, categoria, fecha=None):
        from datetime import date
        f = fecha or date.today()
        qs = TarifaPlantillaMeta.objects.filter(
            status=True, pais=pais, categoria=categoria,
            vigencia_desde__lte=f,
        ).filter(
            Q(vigencia_hasta__isnull=True) | Q(vigencia_hasta__gte=f)
        ).order_by('-vigencia_desde')
        return qs.first()


class MetaWebhookHit(models.Model):
    """Auditoria de bajo nivel: cada request HTTP que toca /whatsapp/meta_webhook/.

    Diferencia con `EventoMetaRecibido`: este modelo guarda TODO hit (GET
    handshake, POST con JSON invalido, 401/403/404, etc.) ANTES de cualquier
    validacion. Sirve para diagnosticar por que Meta dice "Recent Activity OK"
    pero `EventoMetaRecibido` esta vacio (firma invalida, JSON malformado,
    etc.) o el inverso (Django nunca recibio porque proxy bloqueo).
    """
    DIRECCIONES = (('in', 'Entrante (Meta→nosotros)'), ('out', 'Saliente (nosotros→Meta)'))

    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    direccion = models.CharField(max_length=4, choices=DIRECCIONES, default='in', db_index=True)
    method = models.CharField(max_length=10, db_index=True)
    url = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Solo outbound: URL Graph API contra la que pegamos.'
    )
    status_code = models.PositiveSmallIntegerField(default=0, db_index=True)
    ip = models.CharField(max_length=64, blank=True, default='')
    user_agent = models.CharField(max_length=256, blank=True, default='')
    query_string = models.CharField(max_length=512, blank=True, default='')
    signature_presente = models.BooleanField(default=False)
    body_length = models.PositiveIntegerField(default=0)
    body_preview = models.CharField(
        max_length=600, blank=True, default='',
        help_text='Primeros ~600 chars del body request.'
    )
    response_preview = models.CharField(
        max_length=600, blank=True, default='',
        help_text='Solo outbound: primeros ~600 chars de la respuesta de Meta.'
    )
    latencia_ms = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Solo outbound: ms hasta recibir respuesta de Meta.'
    )
    nota = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Tipo de operacion (send_text, handshake, etc.).'
    )

    class Meta:
        verbose_name = 'Hit HTTP webhook Meta'
        verbose_name_plural = 'Hits HTTP webhook Meta'
        ordering = ['-fecha', '-id']
        indexes = [
            models.Index(fields=['direccion', '-fecha']),
            models.Index(fields=['method', '-fecha']),
            models.Index(fields=['status_code', '-fecha']),
        ]

    def __str__(self):
        return f"[{self.fecha:%Y-%m-%d %H:%M:%S}] {self.method} {self.status_code} {self.ip}"


class EventoMetaRecibido(ModeloBase):
    """Auditoria cruda de cada webhook que Meta envia a Django.

    Se guarda el payload completo para poder reprocesar o diagnosticar. Es el
    equivalente Meta de las trazas Baileys — pero del lado de la recepcion, no
    del pipeline IA."""
    config_meta = models.ForeignKey(
        ConfigMeta, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='eventos_recibidos',
        verbose_name='Configuracion Meta'
    )
    tipo_evento = models.CharField(
        max_length=50, db_index=True,
        verbose_name='Tipo de evento',
        help_text='Ej: messages, statuses, message_template_status_update.'
    )
    payload_json = models.JSONField(verbose_name='Payload crudo')
    firma_valida = models.BooleanField(
        default=False,
        verbose_name='Firma HMAC valida',
        help_text='True si X-Hub-Signature-256 coincide con app_secret.'
    )
    procesado = models.BooleanField(default=False, verbose_name='Procesado')
    error_procesamiento = models.TextField(blank=True, null=True)
    recibido_en = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Evento Meta recibido'
        verbose_name_plural = 'Eventos Meta recibidos'
        ordering = ['-recibido_en', '-id']
        indexes = [
            models.Index(fields=['tipo_evento', '-recibido_en']),
            models.Index(fields=['procesado', '-recibido_en']),
        ]

    def __str__(self):
        return f"[{self.recibido_en:%Y-%m-%d %H:%M:%S}] {self.tipo_evento}"


# ============================================================================
# CRM: Etiquetas (tags), Pipeline (Kanban), Horarios, Campañas
# ============================================================================

class EtiquetaContacto(ModeloBase):
    """Etiquetas libres aplicables a contactos para segmentación."""
    nombre = models.CharField('Nombre', max_length=80)
    color = models.CharField(
        'Color', max_length=20, default='#0d6efd',
        help_text='Color HEX para badge. Ej: #0d6efd'
    )
    descripcion = models.CharField('Descripción', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'Etiqueta'
        verbose_name_plural = 'Etiquetas'
        ordering = ['nombre']
        constraints = [
            models.UniqueConstraint(
                fields=['usuario_creacion', 'nombre'],
                name='whatsapp_etiqueta_unica_por_usuario',
            )
        ]

    def __str__(self):
        return self.nombre


class PipelineVenta(ModeloBase):
    """Pipeline/tablero Kanban de ventas. Puede haber varios (ej: Ventas, Soporte)."""
    nombre = models.CharField('Nombre', max_length=120)
    descripcion = models.CharField('Descripción', max_length=255, blank=True, default='')
    es_default = models.BooleanField('Pipeline por defecto', default=False)

    class Meta:
        verbose_name = 'Pipeline de ventas'
        verbose_name_plural = 'Pipelines de ventas'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class EtapaPipeline(ModeloBase):
    """Columna del Kanban. Orden determina posición izquierda→derecha."""
    pipeline = models.ForeignKey(
        PipelineVenta, on_delete=models.CASCADE, related_name='etapas'
    )
    nombre = models.CharField('Nombre', max_length=80)
    orden = models.PositiveIntegerField('Orden', default=0, db_index=True)
    color = models.CharField('Color', max_length=20, default='#6c757d')
    probabilidad_cierre = models.PositiveIntegerField(
        'Probabilidad cierre (%)', default=0,
        help_text='0-100. Usado para forecast ponderado.'
    )
    es_ganado = models.BooleanField('Estado ganado (cerrado con éxito)', default=False)
    es_perdido = models.BooleanField('Estado perdido', default=False)

    class Meta:
        verbose_name = 'Etapa de pipeline'
        verbose_name_plural = 'Etapas de pipeline'
        ordering = ['pipeline', 'orden']

    def __str__(self):
        return f"{self.pipeline.nombre} · {self.nombre}"


class ConversacionEnPipeline(ModeloBase):
    """Posición de una conversación dentro de un pipeline (card en Kanban)."""
    conversacion = models.ForeignKey(
        ConversacionWhatsApp, on_delete=models.CASCADE,
        related_name='pipelines', verbose_name='Conversación',
    )
    etapa = models.ForeignKey(
        EtapaPipeline, on_delete=models.PROTECT, related_name='cards',
        verbose_name='Etapa actual',
    )
    valor_estimado = models.DecimalField(
        'Valor estimado', max_digits=14, decimal_places=2, default=0,
        help_text='Monto potencial del negocio. Usado para forecast.',
    )
    moneda = models.CharField('Moneda', max_length=8, default='USD')
    orden_en_etapa = models.PositiveIntegerField('Orden en etapa', default=0)
    fecha_cambio_etapa = models.DateTimeField(auto_now=True)
    fecha_cierre_esperado = models.DateField('Cierre esperado', null=True, blank=True)
    nota = models.TextField('Nota', blank=True, default='')

    class Meta:
        verbose_name = 'Card en pipeline'
        verbose_name_plural = 'Cards en pipeline'
        ordering = ['etapa__orden', 'orden_en_etapa']
        constraints = [
            models.UniqueConstraint(
                fields=['conversacion', 'etapa'],
                name='whatsapp_card_unica_conversacion_etapa',
            )
        ]

    def __str__(self):
        return f"{self.conversacion_id} en {self.etapa}"


class HistorialEtapaPipeline(models.Model):
    """Traza de cambios de etapa para una conversación (para análisis de funnel)."""
    card = models.ForeignKey(
        ConversacionEnPipeline, on_delete=models.CASCADE,
        related_name='historial',
    )
    etapa_anterior = models.ForeignKey(
        EtapaPipeline, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    etapa_nueva = models.ForeignKey(
        EtapaPipeline, on_delete=models.CASCADE,
        related_name='+',
    )
    usuario = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True,
    )
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    motivo = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'Historial de etapa'
        verbose_name_plural = 'Historial de etapas'
        ordering = ['-fecha']


# ----------------------------------------------------------------------------
# Horarios de atención (business hours)
# ----------------------------------------------------------------------------

DIAS_SEMANA = (
    (0, 'Lunes'),
    (1, 'Martes'),
    (2, 'Miércoles'),
    (3, 'Jueves'),
    (4, 'Viernes'),
    (5, 'Sábado'),
    (6, 'Domingo'),
)


class HorarioAtencion(ModeloBase):
    """Horario de atención por sesión. Fuera de horario, el bot responde con
    `mensaje_fuera_horario` y/o no enruta a agentes humanos."""
    sesion = models.ForeignKey(
        SesionWhatsApp, on_delete=models.CASCADE,
        related_name='horarios', verbose_name='Sesión',
    )
    dia_semana = models.IntegerField('Día de la semana', choices=DIAS_SEMANA, db_index=True)
    hora_inicio = models.TimeField('Hora inicio')
    hora_fin = models.TimeField('Hora fin')
    activo = models.BooleanField('Activo', default=True)

    class Meta:
        verbose_name = 'Horario de atención'
        verbose_name_plural = 'Horarios de atención'
        ordering = ['sesion', 'dia_semana', 'hora_inicio']

    def __str__(self):
        return f"{self.get_dia_semana_display()} {self.hora_inicio:%H:%M}–{self.hora_fin:%H:%M}"


class ExcepcionHorario(ModeloBase):
    """Feriados u otras fechas cerradas/abiertas que sobrescriben el horario semanal."""
    sesion = models.ForeignKey(
        SesionWhatsApp, on_delete=models.CASCADE,
        related_name='excepciones_horario', verbose_name='Sesión',
    )
    fecha = models.DateField('Fecha')
    abierto = models.BooleanField('¿Abierto este día?', default=False)
    hora_inicio = models.TimeField('Hora inicio', null=True, blank=True)
    hora_fin = models.TimeField('Hora fin', null=True, blank=True)
    motivo = models.CharField('Motivo', max_length=200, blank=True, default='')

    class Meta:
        verbose_name = 'Excepción de horario'
        verbose_name_plural = 'Excepciones de horario'
        ordering = ['sesion', 'fecha']
        constraints = [
            models.UniqueConstraint(
                fields=['sesion', 'fecha'],
                name='whatsapp_excepcion_horario_unica_por_sesion',
            )
        ]

    def __str__(self):
        return f"{self.sesion} · {self.fecha} · {'abierto' if self.abierto else 'cerrado'}"


# Campos adicionales para mensaje fuera de horario viven en SesionWhatsApp, añadidos via migración.


# ----------------------------------------------------------------------------
# Campañas masivas
# ----------------------------------------------------------------------------

TIPOS_CAMPANA = (
    ('texto',     'Texto plano'),
    ('plantilla', 'Plantilla Meta'),
    ('media',     'Media con caption'),
)

ESTADOS_CAMPANA = (
    ('borrador',   'Borrador'),
    ('programada', 'Programada'),
    ('enviando',   'Enviando'),
    ('completada', 'Completada'),
    ('pausada',    'Pausada'),
    ('cancelada',  'Cancelada'),
    ('error',      'Con errores'),
)


class Campana(ModeloBase):
    """Campaña de mensajería masiva (broadcast). Define audiencia + contenido + cronograma."""
    nombre = models.CharField('Nombre', max_length=150)
    descripcion = models.TextField('Descripción', blank=True, default='')
    sesion = models.ForeignKey(
        SesionWhatsApp, on_delete=models.PROTECT,
        related_name='campanas', verbose_name='Sesión emisora',
    )
    tipo = models.CharField('Tipo', max_length=20, choices=TIPOS_CAMPANA, default='texto')
    estado = models.CharField('Estado', max_length=20, choices=ESTADOS_CAMPANA, default='borrador', db_index=True)

    # Contenido según tipo
    mensaje_texto = models.TextField('Mensaje', blank=True, default='')
    archivo = models.FileField(upload_to='campanas/', blank=True, null=True)
    plantilla = models.ForeignKey(
        PlantillaWhatsApp, on_delete=models.PROTECT, null=True, blank=True,
        related_name='campanas', verbose_name='Plantilla Meta',
    )
    plantilla_variables = models.JSONField(
        'Variables plantilla', default=dict, blank=True,
        help_text='{"nombre": "contacto_nombre"} mapea placeholder→campo del contacto.'
    )

    # Audiencia: filtros declarativos sobre contactos
    etiquetas_incluir = models.ManyToManyField(
        EtiquetaContacto, blank=True, related_name='campanas_incluir',
        verbose_name='Etiquetas a incluir',
    )
    etiquetas_excluir = models.ManyToManyField(
        EtiquetaContacto, blank=True, related_name='campanas_excluir',
        verbose_name='Etiquetas a excluir',
    )
    canales = models.JSONField(
        'Canales permitidos', default=list, blank=True,
        help_text='Lista de canales: ["whatsapp","instagram","messenger"]. Vacío = todos.'
    )
    filtro_clasificacion = models.JSONField(
        'Clasificaciones', default=list, blank=True,
        help_text='Lista de integers 0-5 (Sin Clasificar..No Interesado). Vacío = todas.'
    )
    filtro_json = models.JSONField(
        'Filtros adicionales', default=dict, blank=True,
        help_text='Reservado para filtros futuros (rango fechas, min_mensajes, etc.)'
    )

    # Cronograma
    programada_para = models.DateTimeField('Programada para', null=True, blank=True, db_index=True)
    ventana_inicio = models.TimeField('Ventana inicio', null=True, blank=True,
                                      help_text='Solo enviar dentro de este rango horario.')
    ventana_fin = models.TimeField('Ventana fin', null=True, blank=True)
    throttle_por_minuto = models.PositiveIntegerField(
        'Throttle (msg/min)', default=20,
        help_text='Tope de envíos por minuto para no gatillar rate limits.'
    )

    # Ejecución
    fecha_inicio_real = models.DateTimeField('Inicio real', null=True, blank=True)
    fecha_fin_real = models.DateTimeField('Fin real', null=True, blank=True)
    total_objetivo = models.PositiveIntegerField('Total objetivo', default=0)
    total_enviados = models.PositiveIntegerField('Enviados', default=0)
    total_fallidos = models.PositiveIntegerField('Fallidos', default=0)
    total_respondidos = models.PositiveIntegerField('Respondidos', default=0)
    error_detalle = models.TextField('Detalle de error', blank=True, default='')

    class Meta:
        verbose_name = 'Campaña'
        verbose_name_plural = 'Campañas'
        ordering = ['-fecha_registro']
        indexes = [
            models.Index(fields=['estado', '-fecha_registro']),
            models.Index(fields=['sesion', '-fecha_registro']),
        ]

    def __str__(self):
        return f"{self.nombre} · {self.get_estado_display()}"

    @property
    def progreso_pct(self):
        if not self.total_objetivo:
            return 0
        return int(round(100 * (self.total_enviados + self.total_fallidos) / self.total_objetivo))

    @property
    def tasa_respuesta_pct(self):
        if not self.total_enviados:
            return 0
        return int(round(100 * self.total_respondidos / self.total_enviados))


ESTADOS_ENVIO_CAMPANA = (
    ('pendiente', 'Pendiente'),
    ('enviando',  'Enviando'),
    ('enviado',   'Enviado'),
    ('fallido',   'Fallido'),
    ('respondido','Respondido'),
    ('saltado',   'Saltado'),
)


class EnvioCampana(ModeloBase):
    """Registro por-contacto de una campaña. Uno por contacto objetivo."""
    campana = models.ForeignKey(
        Campana, on_delete=models.CASCADE, related_name='envios',
    )
    contacto = models.ForeignKey(
        Contacto, on_delete=models.CASCADE, related_name='envios_campana',
    )
    estado = models.CharField(
        max_length=20, choices=ESTADOS_ENVIO_CAMPANA, default='pendiente', db_index=True
    )
    mensaje_enviado = models.TextField('Mensaje enviado', blank=True, default='')
    mensaje_id_externo = models.CharField(max_length=120, blank=True, default='')
    intentos = models.PositiveSmallIntegerField('Intentos', default=0)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    respondio = models.BooleanField('Respondió', default=False)
    fecha_respuesta = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Envío de campaña'
        verbose_name_plural = 'Envíos de campaña'
        ordering = ['campana', 'contacto']
        constraints = [
            models.UniqueConstraint(
                fields=['campana', 'contacto'],
                name='whatsapp_envio_campana_unique',
            )
        ]
        indexes = [
            models.Index(fields=['estado', 'campana']),
        ]


# ----------------------------------------------------------------------------
# Meta Conversions API (CAPI / Pixel)
# ----------------------------------------------------------------------------

class PixelMeta(ModeloBase):
    """Configuración del Pixel/Dataset de Meta para reportar conversiones vía CAPI.

    Un pixel puede estar asociado a una sesión o ser compartido entre varias
    (por eso es ForeignKey opcional + flag `compartido`). Cuando una conversación
    cambia a Lead/Cliente, el servicio CAPI envía un evento al pixel.
    """
    nombre = models.CharField('Nombre', max_length=120)
    pixel_id = models.CharField('Pixel ID / Dataset ID', max_length=50, db_index=True)
    access_token = models.TextField(
        'CAPI Access Token',
        help_text='System User token con permiso ads_management sobre este pixel.'
    )
    test_event_code = models.CharField(
        'Test event code', max_length=50, blank=True, default='',
        help_text='Si está lleno, los eventos salen en modo test (solo visibles en Test Events).'
    )
    sesion = models.ForeignKey(
        SesionWhatsApp, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pixels', verbose_name='Sesión (opcional)',
    )
    activo = models.BooleanField('Activo', default=True)
    evento_lead_nombre = models.CharField(
        'Nombre evento Lead', max_length=50, default='Lead',
        help_text='Nombre del evento estándar Meta que se dispara al clasificar como Lead.'
    )
    evento_purchase_nombre = models.CharField(
        'Nombre evento Purchase', max_length=50, default='Purchase'
    )

    class Meta:
        verbose_name = 'Pixel Meta (CAPI)'
        verbose_name_plural = 'Pixels Meta (CAPI)'

    def __str__(self):
        return f"{self.nombre} · {self.pixel_id}"


class EventoCAPI(ModeloBase):
    """Log de cada evento enviado a Meta CAPI — para auditoría y reintentos."""
    pixel = models.ForeignKey(
        PixelMeta, on_delete=models.CASCADE, related_name='eventos_enviados'
    )
    conversacion = models.ForeignKey(
        ConversacionWhatsApp, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='eventos_capi'
    )
    event_name = models.CharField('Nombre evento', max_length=50, db_index=True)
    event_id = models.CharField('Event ID (dedup)', max_length=200, db_index=True)
    event_time = models.DateTimeField('Event time', db_index=True)
    valor = models.DecimalField('Valor', max_digits=12, decimal_places=2, default=0)
    moneda = models.CharField('Moneda', max_length=8, default='USD')
    ctwa_clid = models.CharField(max_length=300, blank=True, null=True)
    payload_json = models.JSONField('Payload enviado', default=dict, blank=True)
    response_status = models.PositiveSmallIntegerField('HTTP status', null=True, blank=True)
    response_body = models.TextField('Respuesta Meta', blank=True, default='')
    exitoso = models.BooleanField('Éxito', default=False, db_index=True)
    error = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Evento CAPI'
        verbose_name_plural = 'Eventos CAPI'
        ordering = ['-event_time']
        indexes = [
            models.Index(fields=['-event_time', 'event_name']),
            models.Index(fields=['exitoso', '-event_time']),
        ]

    def __str__(self):
        return f"{self.event_name} · {self.event_time:%Y-%m-%d %H:%M}"


# ----------------------------------------------------------------------------
# Instagram + Messenger configs (paralelo a ConfigMeta)
# ----------------------------------------------------------------------------

class ConfigInstagram(ModeloBase):
    """Configuración Instagram Graph API (DMs) por sesión. OneToOne con sesión
    de proveedor='instagram'."""
    sesion = models.OneToOneField(
        SesionWhatsApp, on_delete=models.CASCADE,
        related_name='config_instagram', verbose_name='Sesión'
    )
    ig_user_id = models.CharField('Instagram User ID', max_length=100, db_index=True,
                                  help_text='IG Business Account ID (17..).')
    page_id = models.CharField('Facebook Page ID', max_length=100, db_index=True,
                               help_text='Página FB linkeada al IG Business.')
    username = models.CharField('@username', max_length=120, blank=True, default='')
    access_token = models.TextField('Access Token (Page)',
                                    help_text='Page access token con instagram_manage_messages.')
    webhook_verify_token = models.CharField(max_length=60)
    webhook_verificado_en = models.DateTimeField(null=True, blank=True)
    ultima_sincronizacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Configuración Instagram'
        verbose_name_plural = 'Configuraciones Instagram'

    def __str__(self):
        return f"IG · {self.username or self.ig_user_id}"


class ConfigMessenger(ModeloBase):
    """Configuración Messenger Platform (Facebook Page) por sesión."""
    sesion = models.OneToOneField(
        SesionWhatsApp, on_delete=models.CASCADE,
        related_name='config_messenger', verbose_name='Sesión'
    )
    page_id = models.CharField('Facebook Page ID', max_length=100, db_index=True)
    page_name = models.CharField('Page Name', max_length=200, blank=True, default='')
    access_token = models.TextField('Page access token',
                                    help_text='Token con pages_messaging.')
    webhook_verify_token = models.CharField(max_length=60)
    webhook_verificado_en = models.DateTimeField(null=True, blank=True)
    ultima_sincronizacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Configuración Messenger'
        verbose_name_plural = 'Configuraciones Messenger'

    def __str__(self):
        return f"Messenger · {self.page_name or self.page_id}"


# ----------------------------------------------------------------------------
# Round-robin: disponibilidad de agentes
# ----------------------------------------------------------------------------

class DisponibilidadAgente(ModeloBase):
    """Estado de disponibilidad por agente. El enrutador round-robin solo asigna
    conversaciones a agentes con `disponible=True`."""
    usuario = models.OneToOneField(
        Usuario, on_delete=models.CASCADE,
        related_name='disponibilidad', verbose_name='Agente',
    )
    disponible = models.BooleanField('Disponible', default=True, db_index=True)
    max_conversaciones = models.PositiveIntegerField(
        'Máx. conversaciones simultáneas', default=20,
        help_text='Round-robin no asigna más allá de este tope.'
    )
    sesiones = models.ManyToManyField(
        SesionWhatsApp, blank=True, related_name='agentes_disponibles',
        verbose_name='Sesiones que atiende',
        help_text='Sesiones cuyas conversaciones pueden asignarse a este agente. Vacío = todas.'
    )
    departamentos = models.ManyToManyField(
        'crm.DepartamentoChatBot', blank=True, related_name='agentes_disponibles',
        verbose_name='Departamentos',
    )
    auto_respuesta_fuera_linea = models.TextField(
        'Auto-respuesta fuera de línea', blank=True, default='',
    )
    ultimo_asignado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Disponibilidad de agente'
        verbose_name_plural = 'Disponibilidades de agentes'
        ordering = ['usuario']

    def __str__(self):
        return f"{self.usuario} · {'disponible' if self.disponible else 'offline'}"


class AsignacionAutomatica(models.Model):
    """Traza de cada asignación automática hecha por el round-robin."""
    conversacion = models.ForeignKey(
        ConversacionWhatsApp, on_delete=models.CASCADE,
        related_name='asignaciones_auto',
    )
    agente = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asignaciones_recibidas_auto',
    )
    estrategia = models.CharField(
        max_length=30, default='round_robin',
        help_text='round_robin | least_loaded | manual',
    )
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    motivo = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        verbose_name = 'Asignación automática'
        verbose_name_plural = 'Asignaciones automáticas'
        ordering = ['-fecha']


# ----------------------------------------------------------------------------
# Webhooks salientes (outbound integrations estilo Zapier)
# ----------------------------------------------------------------------------

EVENTOS_INTEGRACION = (
    ('conversacion.nueva',        'Conversación nueva'),
    ('conversacion.cerrada',      'Conversación cerrada'),
    ('conversacion.clasificada',  'Conversación reclasificada'),
    ('conversacion.etiquetada',   'Etiqueta agregada'),
    ('conversacion.etapa',        'Cambio de etapa pipeline'),
    ('contacto.nuevo',            'Contacto nuevo'),
    ('mensaje.entrante',          'Mensaje entrante'),
    ('mensaje.saliente',          'Mensaje saliente'),
    ('campana.completada',        'Campaña completada'),
)


class WebhookSaliente(ModeloBase):
    """Webhook configurable que dispara POST a una URL externa ante eventos del
    CRM. Permite integración estilo Zapier/Make sin dependencia directa."""
    nombre = models.CharField('Nombre', max_length=120)
    url = models.URLField('URL destino', max_length=500)
    eventos = models.JSONField(
        'Eventos suscritos', default=list,
        help_text='Lista de eventos. Ej: ["conversacion.nueva","mensaje.entrante"]'
    )
    secret = models.CharField(
        'Secret HMAC', max_length=100, blank=True, default='',
        help_text='Si se define, firma el body con HMAC-SHA256 en header X-FC-Signature.'
    )
    activo = models.BooleanField('Activo', default=True)
    headers_extra = models.JSONField('Headers extra', default=dict, blank=True)
    fallos_consecutivos = models.PositiveIntegerField('Fallos consecutivos', default=0)
    ultimo_error = models.TextField(blank=True, default='')
    ultima_entrega = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Webhook saliente'
        verbose_name_plural = 'Webhooks salientes'
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} → {self.url}"


class EntregaWebhookSaliente(models.Model):
    """Log de cada entrega (attempt) de webhook saliente."""
    webhook = models.ForeignKey(
        WebhookSaliente, on_delete=models.CASCADE, related_name='entregas'
    )
    evento = models.CharField(max_length=50, db_index=True)
    payload = models.JSONField()
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    respuesta = models.TextField(blank=True, default='')
    exitoso = models.BooleanField(default=False, db_index=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    latencia_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Entrega webhook'
        verbose_name_plural = 'Entregas webhook'
        ordering = ['-fecha']