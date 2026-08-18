"""Motor de automatización transversal.

El motor de flujos que ya existe (`crm/motor_flujo_chatbot.py`) vive dentro de
la conversación: responde mensajes. Esto es distinto — reacciona a eventos de
**cualquier** parte del sistema y ejecuta acciones que pueden tardar días:

    cita cumplida  →  esperar 2 días  →  pedir reseña por WhatsApp
    contacto creado con etiqueta VIP  →  asignar asesor  →  notificar

La pieza que lo hace útil es que **el paso "esperar" se persiste**. Una
ejecución que llega a un `esperar` guarda en qué acción quedó y cuándo retomar;
un cron la levanta después. Sin eso, "esperar 2 días" exigiría un proceso vivo.

Ver `.ai/docs/estudio_gohighlevel.md` sección 5, Fase 1.3.
"""
from django.db import models
from django.utils import timezone

from autenticacion.models import Usuario
from core.custom_models import ModeloBase

# ---------------------------------------------------------------------------
# Eventos que pueden disparar una automatización.
# Cada uno lo emite el código de dominio llamando a `motor.disparar()`.
# El contexto que acompaña a cada evento está documentado en README.md.
# ---------------------------------------------------------------------------
EVENTO_CONTACTO_CREADO = 'contacto_creado'
EVENTO_CONVERSACION_INICIADA = 'conversacion_iniciada'
EVENTO_CONVERSACION_FINALIZADA = 'conversacion_finalizada'
EVENTO_ETIQUETA_AGREGADA = 'etiqueta_agregada'
EVENTO_CITA_CREADA = 'cita_creada'
EVENTO_CITA_CUMPLIDA = 'cita_cumplida'
EVENTO_OPORTUNIDAD_GANADA = 'oportunidad_ganada'
EVENTO_REGISTRO_CREADO = 'registro_creado'

EVENTO_CHOICES = (
    (EVENTO_CONTACTO_CREADO, 'Se creó un contacto'),
    (EVENTO_CONVERSACION_INICIADA, 'Se inició una conversación'),
    (EVENTO_CONVERSACION_FINALIZADA, 'Se finalizó una conversación'),
    (EVENTO_ETIQUETA_AGREGADA, 'Se agregó una etiqueta a un contacto'),
    (EVENTO_CITA_CREADA, 'Se agendó una cita'),
    (EVENTO_CITA_CUMPLIDA, 'Se cumplió una cita'),
    (EVENTO_OPORTUNIDAD_GANADA, 'Se ganó una oportunidad'),
    (EVENTO_REGISTRO_CREADO, 'Se creó un registro de un objeto personalizado'),
)

# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------
ACCION_ESPERAR = 'esperar'
ACCION_ENVIAR_WHATSAPP = 'enviar_whatsapp'
ACCION_ENVIAR_EMAIL = 'enviar_email'
ACCION_AGREGAR_ETIQUETA = 'agregar_etiqueta'
ACCION_ASIGNAR_ASESOR = 'asignar_asesor'
ACCION_WEBHOOK = 'webhook'
ACCION_NOTIFICAR = 'notificar'
ACCION_CREAR_REGISTRO = 'crear_registro'

ACCION_CHOICES = (
    (ACCION_ESPERAR, 'Esperar'),
    (ACCION_ENVIAR_WHATSAPP, 'Enviar mensaje de WhatsApp'),
    (ACCION_ENVIAR_EMAIL, 'Enviar correo'),
    (ACCION_AGREGAR_ETIQUETA, 'Agregar etiqueta al contacto'),
    (ACCION_ASIGNAR_ASESOR, 'Asignar asesor'),
    (ACCION_CREAR_REGISTRO, 'Crear un registro de objeto personalizado'),
    (ACCION_WEBHOOK, 'Llamar a un webhook'),
    (ACCION_NOTIFICAR, 'Notificar a un usuario'),
)

UNIDAD_CHOICES = (
    ('minutos', 'Minutos'),
    ('horas', 'Horas'),
    ('dias', 'Días'),
)

OPERADOR_CHOICES = (
    ('igual', 'es igual a'),
    ('distinto', 'es distinto de'),
    ('contiene', 'contiene'),
    ('no_contiene', 'no contiene'),
    ('existe', 'tiene algún valor'),
    ('vacio', 'está vacío'),
    ('mayor', 'es mayor que'),
    ('menor', 'es menor que'),
)

# Campos que trae el contexto de cada evento. Los usa el armador de condiciones
# de la UI para ofrecer una lista en vez de que el usuario adivine el nombre.
# Tiene que quedar en sync con lo que arma cada emisor (ver README.md).
CAMPOS_POR_EVENTO = {
    EVENTO_CONTACTO_CREADO: [
        ('contacto_nombre', 'Nombre del contacto'),
        ('numero', 'Número'),
        ('canal', 'Canal (whatsapp, instagram, messenger, tiktok)'),
        ('sesion', 'Nombre de la sesión'),
    ],
    EVENTO_CONVERSACION_INICIADA: [
        ('contacto_nombre', 'Nombre del contacto'),
        ('numero', 'Número'),
        ('canal', 'Canal'),
    ],
    EVENTO_CONVERSACION_FINALIZADA: [
        ('contacto_nombre', 'Nombre del contacto'),
        ('numero', 'Número'),
        ('clasificacion', 'Clasificación'),
        ('estado_atencion', 'Estado de atención'),
    ],
    EVENTO_ETIQUETA_AGREGADA: [
        ('etiqueta', 'Nombre de la etiqueta'),
        ('contacto_nombre', 'Nombre del contacto'),
        ('canal', 'Canal'),
    ],
    EVENTO_CITA_CREADA: [
        ('servicio', 'Servicio'),
        ('recurso', 'Recurso'),
        ('origen', 'Origen (manual, chatbot)'),
        ('reagendado', 'Es reagendada'),
    ],
    EVENTO_CITA_CUMPLIDA: [
        ('servicio', 'Servicio'),
        ('recurso', 'Recurso'),
        ('estado_anterior', 'Estado anterior'),
    ],
    EVENTO_OPORTUNIDAD_GANADA: [
        ('etapa', 'Etapa'),
        ('etapa_anterior', 'Etapa anterior'),
        ('pipeline', 'Pipeline'),
        ('valor', 'Valor'),
        ('moneda', 'Moneda'),
    ],
    EVENTO_REGISTRO_CREADO: [
        ('objeto', 'Nombre del objeto'),
        ('objeto_slug', 'Identificador del objeto'),
        ('titulo', 'Título del registro'),
        ('datos.<campo>', 'Un campo del registro — ej: datos.precio'),
    ],
}

ESTADO_PENDIENTE = 'pendiente'
ESTADO_ESPERANDO = 'esperando'
ESTADO_COMPLETADA = 'completada'
ESTADO_FALLIDA = 'fallida'
ESTADO_CANCELADA = 'cancelada'

ESTADO_EJECUCION_CHOICES = (
    (ESTADO_PENDIENTE, 'Pendiente'),
    (ESTADO_ESPERANDO, 'Esperando'),
    (ESTADO_COMPLETADA, 'Completada'),
    (ESTADO_FALLIDA, 'Fallida'),
    (ESTADO_CANCELADA, 'Cancelada'),
)


class Automatizacion(ModeloBase):
    """Un disparador con su lista ordenada de acciones."""
    usuario = models.ForeignKey(
        Usuario, on_delete=models.CASCADE, related_name='automatizaciones',
        verbose_name='Propietario'
    )
    nombre = models.CharField(max_length=150, verbose_name='Nombre')
    descripcion = models.TextField(blank=True, default='', verbose_name='Descripción')
    evento = models.CharField(
        max_length=40, choices=EVENTO_CHOICES, verbose_name='Cuándo se dispara',
        db_index=True
    )
    activo = models.BooleanField(
        default=True, verbose_name='Activa',
        help_text='Si se apaga, el disparador deja de crear ejecuciones nuevas. '
                  'Las que ya estaban esperando siguen su curso.'
    )
    condiciones = models.JSONField(
        blank=True, null=True, default=None, verbose_name='Condiciones',
        help_text='Lista de {campo, operador, valor}. Se evalúan contra el contexto '
                  'del evento y deben cumplirse todas.'
    )
    total_ejecuciones = models.PositiveIntegerField(default=0, editable=False)
    ultima_ejecucion = models.DateTimeField(blank=True, null=True, editable=False)

    class Meta:
        verbose_name = 'Automatización'
        verbose_name_plural = 'Automatizaciones'
        ordering = ('nombre',)

    def __str__(self):
        return self.nombre

    def acciones_activas(self):
        return self.acciones.filter(status=True).order_by('orden', 'id')

    def resumen_acciones(self):
        return ' → '.join(a.resumen() for a in self.acciones_activas()) or 'Sin acciones'


class AccionAutomatizacion(ModeloBase):
    """Un paso dentro de una automatización."""
    automatizacion = models.ForeignKey(
        Automatizacion, on_delete=models.CASCADE, related_name='acciones',
        verbose_name='Automatización'
    )
    orden = models.PositiveSmallIntegerField(default=0, verbose_name='Orden')
    tipo = models.CharField(max_length=30, choices=ACCION_CHOICES, verbose_name='Acción')
    parametros = models.JSONField(default=dict, verbose_name='Parámetros')

    class Meta:
        verbose_name = 'Acción de automatización'
        verbose_name_plural = 'Acciones de automatización'
        ordering = ('orden', 'id')

    def __str__(self):
        return self.resumen()

    def resumen(self):
        p = self.parametros or {}
        if self.tipo == ACCION_ESPERAR:
            return f"esperar {p.get('cantidad', 0)} {p.get('unidad', 'minutos')}"
        if self.tipo == ACCION_ENVIAR_WHATSAPP:
            return 'enviar WhatsApp'
        if self.tipo == ACCION_ENVIAR_EMAIL:
            return 'enviar correo'
        if self.tipo == ACCION_AGREGAR_ETIQUETA:
            return f"etiquetar «{p.get('etiqueta', '')}»"
        if self.tipo == ACCION_ASIGNAR_ASESOR:
            return 'asignar asesor'
        if self.tipo == ACCION_CREAR_REGISTRO:
            return f"crear {p.get('objeto_slug', 'registro')}"
        if self.tipo == ACCION_WEBHOOK:
            return 'llamar webhook'
        if self.tipo == ACCION_NOTIFICAR:
            return 'notificar'
        return self.get_tipo_display()

    def demora(self):
        """timedelta de una acción `esperar`. Cero para las demás."""
        from datetime import timedelta
        if self.tipo != ACCION_ESPERAR:
            return timedelta()
        p = self.parametros or {}
        try:
            cantidad = int(p.get('cantidad') or 0)
        except (TypeError, ValueError):
            cantidad = 0
        unidad = p.get('unidad') or 'minutos'
        if unidad == 'dias':
            return timedelta(days=cantidad)
        if unidad == 'horas':
            return timedelta(hours=cantidad)
        return timedelta(minutes=cantidad)


class EjecucionAutomatizacion(ModeloBase):
    """Una corrida concreta. Sobrevive a los `esperar`.

    `indice_accion` guarda en qué paso quedó y `ejecutar_en` cuándo retomar; el
    cron `procesar_automatizaciones` levanta las que ya vencieron.
    """
    automatizacion = models.ForeignKey(
        Automatizacion, on_delete=models.CASCADE, related_name='ejecuciones',
        verbose_name='Automatización'
    )
    contexto = models.JSONField(default=dict, verbose_name='Contexto del evento')
    estado = models.CharField(
        max_length=15, choices=ESTADO_EJECUCION_CHOICES, default=ESTADO_PENDIENTE,
        db_index=True, verbose_name='Estado'
    )
    indice_accion = models.PositiveSmallIntegerField(
        default=0, verbose_name='Acción actual',
        help_text='Posición dentro de la lista de acciones donde retomar.'
    )
    ejecutar_en = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name='Ejecutar a partir de'
    )
    intentos = models.PositiveSmallIntegerField(default=0, verbose_name='Intentos')
    error = models.TextField(blank=True, default='', verbose_name='Último error')

    class Meta:
        verbose_name = 'Ejecución de automatización'
        verbose_name_plural = 'Ejecuciones de automatización'
        ordering = ('-id',)
        indexes = [
            models.Index(fields=['estado', 'ejecutar_en'], name='autom_ejec_estado_fecha'),
        ]

    def __str__(self):
        return f'{self.automatizacion.nombre} #{self.pk} ({self.get_estado_display()})'


class LogAutomatizacion(ModeloBase):
    """Traza por acción ejecutada. Es lo que se mira cuando algo no pasó."""
    ejecucion = models.ForeignKey(
        EjecucionAutomatizacion, on_delete=models.CASCADE, related_name='logs',
        verbose_name='Ejecución'
    )
    accion = models.CharField(max_length=30, blank=True, default='', verbose_name='Acción')
    ok = models.BooleanField(default=True, verbose_name='Resultado')
    detalle = models.TextField(blank=True, default='', verbose_name='Detalle')

    class Meta:
        verbose_name = 'Log de automatización'
        verbose_name_plural = 'Logs de automatización'
        ordering = ('id',)

    def __str__(self):
        return f'{self.accion}: {"ok" if self.ok else "error"}'
