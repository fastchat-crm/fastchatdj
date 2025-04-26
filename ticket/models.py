from django.db import models

from autenticacion.models import Usuario
from core.custom_models import ModeloBase

class EquipoAtencion(ModeloBase):
    nombre = models.CharField(default='',max_length=200, verbose_name='Nombre del equipo')
    descripcion = models.TextField(default='', verbose_name='Descripción del equipo')
    lider = models.ForeignKey('autenticacion.Usuario', on_delete=models.CASCADE, verbose_name='Líder del equipo')
    integrantes = models.ManyToManyField('autenticacion.Usuario', verbose_name='Integrántes del equipo', related_name='integrantes')
    automatico = models.BooleanField(default=False,verbose_name='Distribución de requerimientos automática')
    esgestor = models.BooleanField(default=False, verbose_name='Es equipo gestor de todas las actividades')

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'Equipo'
        verbose_name_plural = 'Equipos'

class ProcesoAtencion(ModeloBase):
    empresa = models.ForeignKey('seguridad.Empresa', on_delete=models.CASCADE, verbose_name='Empresa')
    descripcion = models.TextField(default='', verbose_name='Descripción')
    equipos = models.ManyToManyField(EquipoAtencion, verbose_name='Equipos que participan en este proceso')
    automatico = models.BooleanField(default=False,verbose_name='Distribución de requerimientos automática')
    activo = models.BooleanField(default=True, verbose_name='Proceso activo')

    def __str__(self):
        return f'{self.empresa} | {self.descripcion}'

    def ids_lideres(self):
        lista = []
        for p in self.equipos.all():
            lista.append(p.lider.id)
        return lista

    def lista_integrantes(self):
        lista = []
        for p in self.equipos.all():
            lista.append({'value': p.lider.id, 'text': p.lider.full_name()})
            for ir in p.integrantes.all():
                lista.append({'value': ir.id, 'text': ir.full_name()})
        return lista

    def ids_integrantes(self):
        lista = []
        for p in self.equipos.all():
            lista.append(p.lider.id)
            for ir in p.integrantes.all():
                lista.append(ir.id)
        return lista

    class Meta:
        verbose_name = u"Proceso"
        verbose_name_plural = u"Procesos"

class TicketAtencion(ModeloBase):
    from .choices import PRIORIDAD, ESTADO_TICKET, TIPO_TICKET
    codigo = models.CharField(max_length=200, default='', verbose_name='Código de ticket')
    empresa = models.ForeignKey('seguridad.Empresa', blank=True, null=True,  on_delete=models.CASCADE, verbose_name='Empresa')
    usuario = models.ForeignKey('autenticacion.Usuario', on_delete=models.CASCADE, blank=True, null=True, verbose_name='Usuario que crea el ticket')
    proceso = models.ForeignKey(ProcesoAtencion, on_delete=models.CASCADE, blank=True, null=True, verbose_name='Proceso')
    titulo = models.CharField(max_length=5000, default='', verbose_name='Título')
    descripcion = models.TextField(default='', verbose_name='Descripción', blank=True, null=True)
    tipo = models.IntegerField(choices=TIPO_TICKET, default=1, verbose_name=u'Tipo de ticket')
    prioridad = models.IntegerField(choices=PRIORIDAD, default=1, verbose_name=u'Prioridad')
    estado = models.IntegerField(choices=ESTADO_TICKET, default=1, verbose_name=u'Estado')
    asignadoa = models.ForeignKey('autenticacion.Usuario', on_delete=models.CASCADE, blank=True, null=True, verbose_name='Asignado a', related_name='+')
    asignadopor = models.ForeignKey('autenticacion.Usuario', on_delete=models.CASCADE, blank=True, null=True, verbose_name='Asignado por', related_name='+')
    finicioactividad = models.DateTimeField(default=None, blank=True, null=True, verbose_name='Fecha que inicio la actividad')
    ffinactividad = models.DateTimeField(default=None, blank=True, null=True, verbose_name='Fecha que finalizo la actividad')
    fecha_vigencia = models.DateTimeField(default=None, blank=True, null=True, verbose_name='Fecha de vigencia')
    numero_ticket = models.IntegerField(default=1, verbose_name='Numero de ticket')
    archivo = models.FileField(upload_to='archivo_ticket/', blank=True, null=True, verbose_name=u'Archivo adjunto')

    def __str__(self):
        return '{}'.format(self.titulo)

    def get_color_estado(self):
        if self.estado == 1:
            return 'bg-secondary'
        elif self.estado == 2:
            return 'bg-secondary'
        elif self.estado == 3:
            return 'bg-primary'
        else:
            return 'bg-success'

    def get_color_prioridad(self):
        if self.prioridad == 1:
            return 'bg-success'
        elif self.prioridad == 2:
            return 'bg-warning'
        elif self.prioridad == 3:
            return 'bg-danger'
        else:
            return 'bg-secondary'

    def tipo_archivo(self):
        namefile = self.archivo.name
        ext = namefile[namefile.rfind("."):].lower()
        if ext in ['.pdf']:
            return {'formato': 'pdf', 'icon': 'fa-file-pdf text-danger'}
        elif ext in ['.png', '.jpg', '.jpeg', '.svg']:
            return {'formato': 'img', 'icon': 'fa-file-image texto-blue'}
        elif ext in ['.xls', '.xlsx', '.xlsx', '.xlsb']:
            return {'formato': 'excel', 'icon': 'fa-file-excel text-success'}
        elif ext in ['.docx', '.doc']:
            return {'formato': 'word', 'icon': 'fa-file-word text-primary'}
        else:
            return {'formato': 'otro', 'icon': 'fa-file text-secondary'}

    def component_archive(self):
        if not self.archivo:
            return ''
        tipo = self.tipo_archivo()
        if tipo['formato'] == 'pdf':
            return f'''
            <a href="{self.archivo.url}" class="doc_preview tb"
               data-width="2048" data-height="1365"
               data-fancybox="iframe{self.id}"
               id="doccargado_{self.archivo.name}"
               title="Visualizar archivo cargado"
               data-caption="Documento cargado: {self.archivo.name}">
                <i class="fas {tipo['icon']} fs-4"></i>
            </a>
            '''
        elif tipo['formato'] == 'img':
            return f'''
            <a href="{self.archivo.url}" data-fancybox="image"
               data-width="2048" data-height="1365"
               title="Visualizar imagen">
                <img src="{self.archivo.url}" alt="Imagen cargada" style="max-width: 60px; max-height: 60px;">
            </a>
            '''
        else:
            return f'''
            <a href="{self.archivo.url}" target="_blank" title="Descargar archivo">
                <i class="fas {tipo['icon']} fs-4"></i>
            </a>
            '''

        class Meta:
            verbose_name = u"Ticket"
            verbose_name_plural = u"Tickets"

    def get_comentario_asignacion(self):
        return self.comentarioticketatencion_set.filter(asignacion=True, status=True, usuario=self.asignadopor, rol=2).first()

    def last_commentario_integrante(self):
        return self.comentarioticketatencion_set.filter(status=True, usuario=self.asignadoa, rol=3).order_by('-fecha_registro').first()

    def comentarios(self):
        return self.comentarioticketatencion_set.filter(status=True).order_by('-fecha_registro')

    def comentarios_client(self):
        return self.comentarioticketatencion_set.filter(status=True, rol=1).order_by('-fecha_registro')

    class Meta:
        verbose_name = u'Ticket'
        verbose_name_plural = u'Tickets'
        ordering = ('-fecha_registro',)

class ComentarioTicketAtencion(ModeloBase):
    from .choices import ROL_COMENTARIO
    ticket = models.ForeignKey(TicketAtencion, blank=True, null=True, on_delete=models.CASCADE, verbose_name=u'Ticket al que pertenece')
    usuario = models.ForeignKey('autenticacion.Usuario', on_delete=models.CASCADE, blank=True, null=True, verbose_name=u'Usuario que crea el comentario')
    mensaje = models.TextField(default='', verbose_name=u'Comentario', blank=True, null=True)
    rol = models.IntegerField(choices=ROL_COMENTARIO, default=1, verbose_name=u'Rol del usuario')
    asignacion = models.BooleanField(default=False, verbose_name=u'Es comentario de asignación de ticket')
    leyenda = models.CharField(default='', verbose_name=u"Leyenda del documento", max_length=200)
    archivo = models.FileField(upload_to='archivo_adjunto/', blank=True, null=True, verbose_name=u'Archivo adjunto')

    def __str__(self):
        return u'%s' % (self.ticket)

    def tipo_archivo(self):
        namefile = self.archivo.name
        ext = namefile[namefile.rfind("."):].lower()
        if ext in ['.pdf']:
            return {'formato': 'pdf', 'icon': 'fa-file-pdf text-danger'}
        elif ext in ['.png', '.jpg', '.jpeg', '.svg']:
            return {'formato': 'img', 'icon': 'fa-file-image texto-blue'}
        elif ext in ['.xls', '.xlsx', '.xlsx', '.xlsb']:
            return {'formato': 'excel', 'icon': 'fa-file-excel text-success'}
        elif ext in ['.docx', '.doc']:
            return {'formato': 'word', 'icon': 'fa-file-word text-primary'}
        else:
            return {'formato': 'otro', 'icon': 'fa-file text-secondary'}

    def component_archive(self):
        if not self.archivo:
            return ''
        tipo = self.tipo_archivo()
        if tipo['formato'] == 'pdf':
            return f'''
            <a href="{self.archivo.url}" class="doc_preview tb"
               data-width="2048" data-height="1365"
               data-fancybox="iframe{self.id}"
               id="doccargado_{self.archivo.name}"
               title="Visualizar archivo cargado"
               data-caption="Documento cargado: {self.archivo.name}">
                <i class="fas {tipo['icon']} fs-4"></i> {self.archivo.name}
            </a>
            '''
        elif tipo['formato'] == 'img':
            return f'''
            <a href="{self.archivo.url}" data-fancybox="image"
               data-width="2048" data-height="1365"
               title="Visualizar imagen">
                <img src="{self.archivo.url}" alt="Imagen cargada" style="max-width: 100px; max-height: 100px;">
            </a>
            '''
        else:
            return f'''
            <a href="{self.archivo.url}" target="_blank" title="Descargar archivo">
                <i class="fas {tipo['icon']} fs-4"></i> {self.archivo.name}
            </a>
            '''

        class Meta:
            verbose_name = u"Ticket"
            verbose_name_plural = u"Tickets"

    class Meta:
        verbose_name = u'Comentario de Ticket'
        verbose_name_plural = u'Comentarios de Tickets'
        ordering = ('fecha_registro',)
