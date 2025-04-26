from datetime import datetime

from django import forms
from pkg_resources import require

from autenticacion.models import Usuario
from core.custom_models import FormBase
from seguridad.models import Empresa
from .funciones import generate_code_ticket, get_user_attend
from .models import EquipoAtencion, ProcesoAtencion, TicketAtencion, ComentarioTicketAtencion
from core.custom_forms import FormModeloBase

class EquipoForm(FormBase):
    nombre = forms.CharField(label=u"Nombre", max_length=200, widget=forms.TextInput(attrs={'placeholder': 'Describa el nombre del equipos', 'col': '12'}), required=True)
    descripcion = forms.CharField(label=u"Descripción", max_length=200, widget=forms.Textarea(attrs={'placeholder': 'Describa a que se dedica su equipo', 'col': '12', 'rows': '2'}), required=True)
    lider = forms.ModelChoiceField(label='Lider', queryset=Usuario.objects.filter(status=True))
    integrantes = forms.ModelMultipleChoiceField(label='Integrantes', queryset=Usuario.objects.filter(status=True))
    # automatico = forms.BooleanField(label='Distribución automática?', required=False, widget=forms.CheckboxInput(attrs={'col':'6'}))
    esgestor = forms.BooleanField(label='Es equipo gestor?', required=False, widget=forms.CheckboxInput(attrs={'col':'6'}))

    def save(self, commit=True):
        cleaned_data = self.cleaned_data
        # Si existe una instancia, actualiza sus valores; de lo contrario, crea una nueva
        equipo = self.instance if self.instance else EquipoAtencion()
        equipo.nombre =  cleaned_data.get('nombre', '')
        equipo.descripcion = cleaned_data.get('descripcion', '')
        equipo.lider = cleaned_data.get('lider', None)
        equipo.esgestor = cleaned_data.get('esgestor', False)
        # equipo.automatico = cleaned_data.get('automatico', False)

        if commit:
            equipo.save(self.request)
            integrantes = cleaned_data.get('integrantes', None)
            if integrantes:
                equipo.integrantes.set(integrantes)
            else:
                equipo.integrantes.clear()
        return equipo

class ProcesoForm(FormBase):
    empresa = forms.ModelChoiceField(label='Empresa', queryset=Empresa.objects.filter(status=True))
    descripcion = forms.CharField(label=u"Descripción", max_length=200, widget=forms.Textarea(attrs={'placeholder': 'Describa el proceso', 'col': '12', 'rows': '4'}), required=True)
    equipos = forms.ModelMultipleChoiceField(label='Equipos', queryset=EquipoAtencion.objects.filter(status=True))
    automatico = forms.BooleanField(label='Distribución automática?', required=False, widget=forms.CheckboxInput(attrs={'col': '6'}))
    def save(self, commit=True):
        cleaned_data = self.cleaned_data
        # Si existe una instancia, actualiza sus valores; de lo contrario, crea una nueva
        proceso = self.instance if self.instance else ProcesoAtencion()
        proceso.empresa = cleaned_data.get('empresa', None)
        proceso.descripcion = cleaned_data.get('descripcion', '')
        proceso.automatico = cleaned_data.get('automatico', False)
        if commit:
            proceso.save(self.request)
            equipos = cleaned_data.get('equipos', None)
            if equipos:
                proceso.equipos.set(equipos)
            else:
                proceso.equipos.clear()
        return proceso

class TicketForm(FormBase):
    empresa = forms.ModelChoiceField(label='Empresa', queryset=Empresa.objects.filter(status=True))
    proceso = forms.ModelChoiceField(label='Proceso', queryset=ProcesoAtencion.objects.filter(status=True))
    titulo = forms.CharField(label=u"Título", max_length=50, widget=forms.TextInput(attrs={'placeholder': 'Describa el título del ticket', 'col': '12'}), required=True)
    descripcion = forms.CharField(label=u"Descripción", max_length=5000, widget=forms.Textarea(attrs={'placeholder': 'Describa el proceso', 'col': '12', 'rows': '6'}), required=True)
    prioridad = forms.ChoiceField(label='Prioridad', choices=TicketAtencion.PRIORIDAD, initial=1)
    tipo = forms.ChoiceField(label='Tipo', choices=TicketAtencion.TIPO_TICKET, initial=1)
    archivo = forms.FileField(label='Archivo', required=False)


    def clean(self):
        cleaned_data = super().clean()
        archivo = cleaned_data.get('archivo', None)
        if archivo:
            # Validar tamaño del archivo (máximo 4 MB)
            if archivo.size > 4 * 1024 * 1024:
                self.add_error('archivo', "El archivo no debe exceder los 4 MB.")
        return cleaned_data

    def save(self, commit=True, request=None):
        cleaned_data = self.cleaned_data
        # Si existe una instancia, actualiza sus valores; de lo contrario, crea una nueva
        empresa = cleaned_data.get('empresa', None)
        archivo = cleaned_data.get('archivo', None)
        proceso = cleaned_data.get('proceso', None)
        ticket = self.instance if self.instance else TicketAtencion()
        if not self.instance:
            codigo, numero = generate_code_ticket(empresa)
            ticket.codigo = codigo
            ticket.numero_ticket = numero
        if archivo:
            extension = archivo.name.split('.')[-1]
            archivo.name = f'adjunto_{ticket.codigo}.{extension}'
            ticket.archivo = archivo
        ticket.empresa = empresa
        # ticket.usuario = user
        ticket.titulo = cleaned_data.get('titulo', '')
        ticket.descripcion = cleaned_data.get('descripcion', '')
        ticket.prioridad = cleaned_data.get('prioridad', 1)
        ticket.tipo = cleaned_data.get('tipo', 1)
        ticket.usuario = request.user
        ticket.proceso = proceso
        # procesos = empresa.procesoatencion_set.filter(status=True, activo=True)
        # if len(procesos) == 1:
        #     proceso = procesos.first()
        #     ticket.proceso = proceso
        if proceso.automatico:
            id_asignadoa = get_user_attend(proceso)
            ticket.asignadoa_id = id_asignadoa
            ticket.estado = 2
        if commit:
            ticket.save(request)
        return ticket

class AsignarTicketForm(FormBase):
    proceso = forms.ModelChoiceField(label='Proceso', queryset=ProcesoAtencion.objects.filter(status=True))
    asignadoa = forms.ModelChoiceField(label='Asignado a', queryset=Usuario.objects.filter(status=True))
    mensaje = forms.CharField(label=u"Mensaje", max_length=1000, widget=forms.Textarea(attrs={'placeholder': 'Describa el proceso', 'col': '12', 'rows': '6'}), required=True)
    archivo = forms.FileField(label='Archivo', required=False)
    fecha_vigencia = forms.DateField(label='Fecha de vigencia', initial=datetime.now(), required=False)

    def clean(self):
        cleaned_data = super().clean()
        archivo = cleaned_data.get('archivo', None)
        if archivo:
            # Validar tamaño del archivo (máximo 4 MB)
            if archivo.size > 4 * 1024 * 1024:
                self.add_error('archivo', "El archivo no debe exceder los 4 MB.")
        return cleaned_data

    def save(self, commit=True, request=None):
        cleaned_data = self.cleaned_data
        archivo = cleaned_data.get('archivo', None)
        asignadoa = cleaned_data.get('asignadoa', None)
        # Si existe una instancia, actualiza sus valores; de lo contrario, crea una nueva
        ticket = self.instance if self.instance else TicketAtencion()
        if asignadoa != ticket.asignadoa:
            ticket.finicioactividad = None
            ticket.ffinactividad = None
        ticket.asignadoa = asignadoa
        ticket.asignadopor = request.user
        ticket.fecha_vigencia = cleaned_data.get('fecha_vigencia', None)
        ticket.proceso = cleaned_data.get('proceso', None)
        comentario = ticket.get_comentario_asignacion()
        comentario = comentario if comentario else ComentarioTicketAtencion()
        comentario.ticket = ticket
        comentario.usuario = request.user
        comentario.mensaje = cleaned_data.get('mensaje', '')
        comentario.rol = 2
        if archivo:
            extension = archivo.name.split('.')[-1]
            archivo.name = f'adjunto_{ticket.codigo}.{extension}'
            comentario.archivo = archivo
        comentario.asignacion = True
        if commit:
            ticket.save(request)
            comentario.save(request)
        return ticket

class CambiarEstadoTicketForm(FormBase):
    estado = forms.ChoiceField(label='Estado', choices=TicketAtencion.ESTADO_TICKET[1:], initial=2)
    mensaje = forms.CharField(label=u"Mensaje", max_length=1000, widget=forms.Textarea(attrs={'placeholder': 'Describa un mensaje a transmitir', 'col': '12', 'rows': '6'}), required=False)
    archivo = forms.FileField(label='Archivo', required=False)

    def clean(self):
        cleaned_data = super().clean()
        instance = self.instance
        if not instance or not instance.asignadoa:
            return ValueError('Para poder cambiar de estado el ticket debe estar asignado a un usuario')
        archivo = cleaned_data.get('archivo', None)
        if archivo:
            # Validar tamaño del archivo (máximo 4 MB)
            if archivo.size > 4 * 1024 * 1024:
                self.add_error('archivo', "El archivo no debe exceder los 4 MB.")
        return cleaned_data

    def save(self, commit=True, request=None):
        from datetime import datetime
        hoy= datetime.now()
        cleaned_data = self.cleaned_data
        archivo = cleaned_data.get('archivo', None)
        mensaje = cleaned_data.get('mensaje', None)
        # Si existe una instancia, actualiza sus valores; de lo contrario, crea una nueva
        ticket = self.instance if self.instance else TicketAtencion()
        ticket.estado = int(cleaned_data.get('estado', 2))
        if ticket.estado == 2:
            ticket.ffinactividad = None
            ticket.finicioactividad = None
        if ticket.estado == 3 and not ticket.finicioactividad:
            ticket.finicioactividad = hoy
        elif ticket.estado == 4:
            if not ticket.finicioactividad:
                ticket.finicioactividad = hoy
            ticket.ffinactividad = hoy

        if commit:
            ticket.save(request)
            if archivo or mensaje:
                # comentario = ticket.last_commentario_integrante()
                comentario = ComentarioTicketAtencion()
                comentario.ticket = ticket
                comentario.usuario = request.user
                comentario.mensaje = cleaned_data.get('mensaje', '')
                comentario.rol = 2
                if archivo:
                    extension = archivo.name.split('.')[-1]
                    archivo.name = f'adjunto_{ticket.codigo}.{extension}'
                    comentario.archivo = archivo
                comentario.save(request)
        return ticket