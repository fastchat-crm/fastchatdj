from datetime import datetime
from decimal import Decimal

from django.contrib.auth.models import Group
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator, FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.safestring import mark_safe

from area_geografica.models import Ciudad
from autenticacion.models import Usuario
from core.crypto import EncryptedTextField
from core.custom_models import ModeloBase, NormalModel
from core.models_utils import FileNameUploadToPath
from core.validadores import solo_numeros
from fastchatdj.settings import AUTH_USER_MODEL


class ErrorLog(models.Model):
    usuario = models.ForeignKey(AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name='Usuario', blank=True, null=True)
    archivo = models.TextField(verbose_name='Archivo', blank=True, null=True)
    metodo = models.CharField(max_length=100, verbose_name='Metodo', blank=True, null=True)
    accion = models.CharField(max_length=100, verbose_name='Acción', blank=True, null=True)
    tipo = models.CharField(max_length=100, verbose_name='Tipo Error', blank=True, null=True)
    linea = models.CharField(max_length=100, verbose_name='Linea', blank=True, null=True)
    descripcion = models.TextField(verbose_name='Descripción', blank=True, null=True)
    corregido = models.BooleanField(default=False, verbose_name="¿Error Corregido?")
    fecha = models.DateTimeField(verbose_name='Fecha', auto_now_add=True)

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        self.accion = self.accion.upper()
        super(ErrorLog, self).save(force_insert, force_update, using)

    def __str__(self):
        return "{} - {} - {} [{}]".format(self.tipo, self.linea, self.descripcion, self.accion)

    class Meta:
        verbose_name = 'ErrorLog'
        verbose_name_plural = 'ErrorLogs'
        ordering = ('-fecha', 'pk')


class UsuarioConectado(models.Model):
    user = models.ForeignKey(AUTH_USER_MODEL, on_delete=models.CASCADE, blank=True, null=True)
    sesion = models.ForeignKey("sessions.Session", on_delete=models.CASCADE, blank=True, null=True)
    dispositivo = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Dispositivo')
    ip = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Ip')
    fecha_conexion = models.DateTimeField(blank=True, null=True)

    def ultima_vez(self):
        fechaactual = timezone.now()
        tiempo = fechaactual - self.fecha_conexion
        return 'Hace {}'.format(str(tiempo).replace('day', 'dia').split('.')[0])

    def is_not_expired(self):
        from datetime import datetime
        return self.sesion.expire_date > datetime.now()


class AudiUsuarioTabla(models.Model):
    usuario = models.ForeignKey(AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name='Usuario', editable=False)
    usuario_admin = models.ForeignKey(AUTH_USER_MODEL, editable=False, on_delete=models.PROTECT,
                                      verbose_name='Usuario Administrador', blank=True, null=True,
                                      related_name="fk_usuario_admin")
    # GenericForeignKey
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    modelo = GenericForeignKey('content_type', 'object_id')
    # ----------------------------------------------------------------
    registroname = models.CharField(max_length=1000, editable=False, verbose_name='Registro Name')
    accion = models.CharField(max_length=100, verbose_name='Acción', editable=False)
    fecha = models.DateTimeField(verbose_name='Fecha', auto_now_add=True)
    datos_json = models.TextField(verbose_name="Datos en formato json", null=True, blank=True, editable=False)
    ip = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Ip')

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        self.registroname = str(self.registroname).upper()
        self.accion = self.accion.upper()
        super(AudiUsuarioTabla, self).save(force_insert, force_update, using)

    def get_model_name(self):
        return self.modelo.__class__.__name__ if self.modelo else ''

    def __str__(self):
        return "{} - {} - {} [{}]".format(self.usuario.username, self.modelo.__class__.__name__ if self.modelo else '', self.registroname, self.accion)

    class Meta:
        verbose_name = 'Auditoría Usuario'
        verbose_name_plural = 'Auditorías Usuarios'
        ordering = ('-fecha', 'pk')


PRIORIDAD_NOTIFICACION = (
    (1, u'Alta'),
    (2, u'Media'),
    (3, u'Baja')
)

TIPO_NOTIFICACION = (
    (1, u'Mensaje'),
    (2, u'Proceso'),
    (3, u'Información'),
    (4, u'Error')
)


class Notificacion(ModeloBase):
    titulo = models.CharField(verbose_name=u'Titulo de la Notificación', max_length=300, null=True, blank=True)
    cuerpo = models.TextField(verbose_name=u'Cuerpo de la Notificación', null=True, blank=True)
    destinatario = models.ForeignKey('autenticacion.Usuario', verbose_name=u'Destinatario', on_delete=models.CASCADE)
    url = models.CharField(verbose_name=u'URL de enlace directo', max_length=300, null=True, blank=True)
    leido = models.BooleanField(default=False, verbose_name=u'Leído')
    fecha_hora_leido = models.DateTimeField(blank=True, null=True, verbose_name=u'Fecha y hora de leido')
    fecha_hora_visible = models.DateTimeField(blank=True, null=True, verbose_name=u'Fecha y hora visible')
    prioridad = models.IntegerField(choices=PRIORIDAD_NOTIFICACION, null=True, blank=True, verbose_name=u'Prioridad')
    tipo = models.IntegerField(choices=TIPO_NOTIFICACION, default=1, verbose_name=u'Tipo Notificación')
    en_proceso = models.BooleanField(default=False, verbose_name='En Proceso')
    error = models.BooleanField(default=False, verbose_name='Error al ejecutar el reporte')

    def color_str(self):
        color = 'text-black'
        if self.tipo == 1:
            color = 'text-info'
        elif self.tipo == 2:
            color = 'text-primary'
        elif self.tipo == 3:
            color = 'text-success'
        elif self.tipo == 4:
            color = 'text-danger'
        return color

    def __str__(self):
        return u'Notificación: %s - Para: %s' % (self.titulo, self.destinatario)

    def diasingresado(self):
        # fecha_registro es DateTimeField (ver ModeloBase). Antes se intentaba combinar
        # con self.hora_registro, que no existe como campo → AttributeError.
        fh = self.fecha_registro
        if fh is None:
            return ''
        if isinstance(fh, datetime):
            fecha_hora_registro = fh
        else:
            # En caso extremo de que sea un date, asume medianoche
            fecha_hora_registro = datetime.combine(fh, datetime.min.time())
        # Normalizar timezone para la resta
        tiempo_actual = timezone.now()
        if timezone.is_aware(tiempo_actual) and timezone.is_naive(fecha_hora_registro):
            fecha_hora_registro = timezone.make_aware(fecha_hora_registro, timezone.get_current_timezone())
        elif timezone.is_naive(tiempo_actual) and timezone.is_aware(fecha_hora_registro):
            tiempo_actual = timezone.make_aware(tiempo_actual, timezone.get_current_timezone())
        tiempo_transcurrido = tiempo_actual - fecha_hora_registro
        dias = tiempo_transcurrido.days
        segundos = tiempo_transcurrido.seconds
        horas = segundos // 3600
        minutos = (segundos // 60) % 60
        segundos = segundos % 60
        return f"{dias} días, {horas} horas, {minutos} minutos, {segundos} segundos"

    def save(self, *args, **kwargs):
        super(Notificacion, self).save(*args, **kwargs)

    class Meta:
        verbose_name = u"Notificación"
        verbose_name_plural = u"Notificaciones"
        ordering = ['destinatario', 'fecha_registro', ]


TIPO_ENTORNO = ((True, "Producción"), (False, "Test"),)


TIPO_AMBIENTE_SRI = (
    (1, u'PRUEBAS'),
    (2, u'PRODUCCIÓN'),
)


class Configuracion(ModeloBase):
    nombre_empresa = models.CharField(max_length=1000, verbose_name='Nombre de la Empresa')
    alias = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Alias')
    titulo = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Título Web')
    descripcion = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Descripción Web')
    telefono = models.CharField(max_length=20, blank=True, null=True, verbose_name='Teléfono Empresa')
    email = models.CharField(max_length=100, blank=True, null=True, verbose_name='Email Empresa')
    web = models.CharField(max_length=100, blank=True, null=True, verbose_name='Web')
    email_notificacion = models.CharField(max_length=100, blank=True, null=True, verbose_name='Email Notificaciones')
    direccion = models.CharField(max_length=5000, blank=True, null=True, verbose_name='Dirección Empresa')
    terminosycondiciones = models.TextField(blank=True, null=True, verbose_name='Terminos y Condiciones')
    # DASHBOARDS
    dias_nuevo = models.PositiveIntegerField(default=30, verbose_name='Días para considerar un producto como nuevo')
    # DATOS LOGOS/FONDOS
    ico = models.FileField(upload_to='configuracion/', max_length=600, blank=True, null=True, verbose_name='Favicon', validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])])
    logo_sistema = models.FileField(upload_to='configuracion/', validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])], max_length=600, blank=True, null=True, verbose_name='Logo')
    logo_sistema_white = models.FileField(upload_to='configuracion/', validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])], max_length=600, blank=True, null=True, verbose_name='Logo Blanco')
    fondo_perfil = models.FileField(upload_to='configuracion/fondo_perfil/', validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])], blank=True, null=True, verbose_name='Fondo de perfil de usuario', help_text='Se recomienda que la imagen tenga un tamaño de 500x281')
    banner_login = models.FileField(upload_to='configuracion/', validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])], blank=True, null=True, verbose_name='Fondo Login')
    fondoprincipal = models.FileField(upload_to='configuracion/', validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])], blank=True, null=True, verbose_name='Fondo Principal')
    imagenprincipal = models.FileField(upload_to='configuracion/', validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])], blank=True, null=True, verbose_name='Imagen Sobre Nosotros')
    imagen_landing = models.FileField(upload_to='configuracion/', validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])], blank=True, null=True, verbose_name='Imagen Landing')

    # CANALES DE MENSAJERIA — activar/desactivar cada transporte desde la UI.
    canal_whatsapp_qr_activo = models.BooleanField(
        default=True, verbose_name='Canal WhatsApp (QR / Baileys) activo',
        help_text='Si está OFF, la opción "QR Code" no aparece al agregar una nueva conexión.'
    )
    canal_whatsapp_api_activo = models.BooleanField(
        default=True, verbose_name='Canal WhatsApp Business API (Meta) activo',
        help_text='Requiere credenciales Meta App registradas.'
    )
    canal_instagram_activo = models.BooleanField(
        default=False, verbose_name='Canal Instagram Direct activo'
    )
    canal_messenger_activo = models.BooleanField(
        default=False, verbose_name='Canal Facebook Messenger activo'
    )
    canal_tiktok_activo = models.BooleanField(
        default=False, verbose_name='Canal TikTok activo'
    )

    # ── IA del sistema (sirve para features tipo "Crear con IA" globales) ──
    token_ia = models.ForeignKey(
        'crm.ApiKeyIA', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='configuraciones_que_usan',
        verbose_name='API Key IA del sistema',
        help_text='Key que usan las features globales de IA del CRM (ej: "Crear con IA" '
                  'en Departamentos Chatbot). Si está vacío, esas opciones quedan deshabilitadas.'
    )
    ia_features_activas = models.BooleanField(
        default=False, verbose_name='Features de IA del sistema activas',
        help_text='Switch maestro. Aunque haya token cargado, si esto está OFF las '
                  'opciones "Crear con IA" no aparecen.'
    )

    @staticmethod
    def get_instancia():
        from core.funciones import db_table_exists
        try:
            # confi = Configuracion.objects.first()
            confi = Configuracion.objects.first() if db_table_exists(
                Configuracion._meta.db_table) and Configuracion.objects.count() > 0 else Configuracion()
        except Exception as ex:
            confi = Configuracion()
        return confi

    class Meta:
        verbose_name = 'Configuración'
        verbose_name_plural = 'Configuración'
        permissions = (
            ("can_view_auditoria", "Puede ver auditorías"),
        )


class CredencialMetaApp(ModeloBase):
    """Credenciales de la Meta App (nivel organizacion).

    Una misma Meta App puede administrar varias WABAs / IG Business / Pages.
    Por eso `app_id` y `app_secret` viven aca (singleton via OneToOne con
    Configuracion) y NO duplicados en cada ConfigMeta/ConfigInstagram/ConfigMessenger.
    """
    configuracion = models.OneToOneField(
        Configuracion, on_delete=models.CASCADE,
        related_name='credencial_meta', verbose_name='Configuración'
    )
    app_id = models.CharField(
        max_length=50, verbose_name='Meta App ID',
        help_text='ID de la aplicacion creada en Meta for Developers.'
    )
    app_secret = EncryptedTextField(
        verbose_name='Meta App Secret',
        help_text='Secret de la App. Se guarda cifrado.'
    )
    config_id = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='Embedded Signup Config ID',
        help_text='Configuration ID del Embedded Signup de WhatsApp Business '
                  '(Meta for Developers → Whatsapp → Configuration). Necesario '
                  'para el flow de conexion guiada.'
    )
    business_id = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='Business Manager ID',
        help_text='ID del Business Manager dueño de la App (opcional).'
    )
    system_user_id = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='System User ID',
        help_text='ID del System User usado para emitir tokens long-lived.'
    )
    system_user_token = EncryptedTextField(
        blank=True, null=True,
        verbose_name='System User Token',
        help_text='Token long-lived del System User. Se guarda cifrado.'
    )
    es_tech_provider = models.BooleanField(
        default=False,
        verbose_name='¿Aprobado como Tech Provider por Meta?',
        help_text='Mientras esté en NO, las sesiones se conectan cargando '
                  'WABA ID + Phone Number ID + access token a mano (modo manual). '
                  'Activá esta opción cuando Meta apruebe tu acceso avanzado: '
                  'recién ahí se habilita el popup Embedded Signup de un solo clic.'
    )
    ultima_sincronizacion = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Última sincronización'
    )

    class Meta:
        verbose_name = 'Credencial Meta App'
        verbose_name_plural = 'Credenciales Meta App'

    def __str__(self):
        return f"Meta App {self.app_id}"


class Modulo(ModeloBase):
    url = models.CharField(max_length=100)
    nombre = models.CharField(max_length=100)
    orden = models.IntegerField(default=0)

    def __str__(self):
        return '{} ({})'.format(self.nombre, self.url)

    class Meta:
        verbose_name = 'URL del Sidebar'
        verbose_name_plural = 'URLs del Sidebar'
        ordering = ['nombre']


class GroupModulo(ModeloBase):
    group = models.OneToOneField(Group, on_delete=models.CASCADE)
    modulos = models.ManyToManyField(Modulo)

    def __str__(self):
        return '{}'.format(self.group.name)

    class Meta:
        verbose_name = 'Asignar Urls a cada rol de usuario'
        verbose_name_plural = 'Asignar Urls a cada rol de usuario'
        ordering = ('pk',)


class ModuloGrupo(ModeloBase):
    nombre = models.CharField(max_length=100)
    icono = models.CharField(max_length=100)
    modulos = models.ManyToManyField(Modulo)
    prioridad = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return '{} {}'.format(self.nombre, self.prioridad)

    class Meta:
        verbose_name = 'Grupo de URLs del Sidebar'
        verbose_name_plural = 'Grupos de URLs del Sidebar'
        ordering = ('prioridad', 'nombre')
        # permissions = (
        #     ('')
        # )

    def modulos_ordenados(self):
        return self.modulos.all().order_by('orden')

    def modulos_activos(self):
        return self.modulos.filter(status=True).order_by('orden')

def slug_name(self):
    from django.utils.text import slugify
    return slugify(self.name)


Group.add_to_class("slug_name", slug_name)


class SessionUser(NormalModel):
    user = models.ForeignKey(AUTH_USER_MODEL, on_delete=models.CASCADE)
    session = models.OneToOneField("sessions.Session", on_delete=models.CASCADE)
    dispositivo = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Dispositivo')
    ip = models.CharField(max_length=1000, blank=True, null=True, verbose_name='Ip')
    codigounico = models.TextField("Código Único de navegador")
    fecha_conexion = models.DateTimeField(auto_now_add=True)
    areageografica = models.CharField("Área Geográfica", max_length=500, null=True, blank=True)

    @staticmethod
    def nuevo(request):
        from core.funciones import get_client_ip
        from django.contrib.sessions.models import Session
        ucc = SessionUser.objects.get_or_create(session_id=Session.objects.get(session_key=request.session.session_key).pk,
                                                   user_id=request.user.pk, codigounico=request.COOKIES.get('SISTEMA_DEVICE_ID') or 'SINCODIGO')[0]
        ucc.fecha_conexion = datetime.now()
        ucc.ip = get_client_ip(request)
        ucc.save()
        return ucc

    def ultima_vez(self):
        fechaactual = datetime.now()
        tiempo = fechaactual - self.fecha_conexion.astimezone(timezone.get_current_timezone()).replace(tzinfo=None)
        return 'Hace {}'.format(str(tiempo).replace('day', 'dia').split('.')[0])

    def is_not_expired(self):
        from datetime import datetime
        return self.session.expire_date > datetime.now()


class Empresa(ModeloBase):
    responsables = models.ManyToManyField('autenticacion.Usuario', verbose_name='Responsables')
    nombre = models.CharField(max_length=100, verbose_name='Nombre')
    logo = models.FileField(upload_to='empresa/logo/',validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'tiff', 'svg', "jfif"])],blank=True, null=True, verbose_name='Logo')

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'

class IntegranteEmpresa(ModeloBase):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, verbose_name='Empresa')
    usuario = models.ForeignKey("autenticacion.Usuario", on_delete=models.CASCADE, verbose_name='Usuario')


    def __str__(self):
        return f"{self.usuario} - {self.empresa}"

    class Meta:
        verbose_name = 'Integrante de Empresa'
        verbose_name_plural = 'Integrantes de Empresas'
        unique_together = ('empresa', 'usuario')

class CronLogEjecucion(models.Model):
    proceso = models.TextField(verbose_name='Proceso', blank=True, null=True)
    detalle = models.TextField(verbose_name='Detalle de Ejecución', blank=True, null=True)
    fecha = models.DateField(verbose_name='Fecha', auto_now_add=True)
    hora = models.TimeField(verbose_name='Hora', auto_now_add=True)
    conexito = models.BooleanField(default=True, verbose_name='Con Exito')

    def save(self, force_insert=False, force_update=False, using=None, **kwargs):
        super(CronLogEjecucion, self).save(force_insert, force_update, using)

    def __str__(self):
        return f"{self.fecha} {self.hora} - {self.proceso} - {self.detalle}"

    class Meta:
        verbose_name = 'Log de Ejecución'
        verbose_name_plural = 'Log de Ejecución'
        ordering = ('-fecha', 'pk')