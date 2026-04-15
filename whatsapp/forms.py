from django.db.models import Count, Q
from django.utils.safestring import mark_safe

from autenticacion.models import Usuario
from core.custom_models import ModelFormBase
from crm.models import DepartamentoChatBot
from .models import SesionWhatsApp, Contacto, ConversacionWhatsApp, MensajeWhatsAppProgramado


class SesionWhatsAppForm(ModelFormBase):
    class Meta:
        model = SesionWhatsApp
        fields = ('nombre', 'min_sesion', 'language', 'modo_bot', 'agente_ia',
                  'departamentos', 'departamento_default',
                  'mensaje_bienvenida', 'mensaje_despedida', 'mensaje_handoff',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(SesionWhatsAppForm, self).__init__(*args, **kwargs)
        self.fields['departamentos'].queryset = DepartamentoChatBot.objects.filter(status=True).order_by('nombre')
        self.fields['departamento_default'].queryset = DepartamentoChatBot.objects.filter(status=True).order_by('nombre')
        self.fields['departamento_default'].required = False
        self.fields['departamento_default'].empty_label = '— (ninguno) —'
        for k, v in self.fields.items():
            if k in ('mensaje_bienvenida', 'mensaje_despedida', 'mensaje_handoff',):
                self.fields[k].widget.attrs['rows'] = '5'
                self.fields[k].widget.attrs['class'] = "summernote"
            if k in ('min_sesion',):
                self.fields[k].widget.attrs['col'] = '3'
            if k in ('departamentos', 'departamento_default', 'language', 'agente_ia'):
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['class'] = "jselect2"
                self.fields[k].required = False
            if k in ('modo_bot',):
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['class'] = "form-control"
            if k in ('nombre',):
                self.fields[k].widget.attrs['col'] = '9'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class AddContactoForm(ModelFormBase):
    class Meta:
        model = Contacto
        fields = ('sesion','numero_telefono', 'contacto_nombre', 'contacto_foto')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(AddContactoForm, self).__init__(*args, **kwargs)
        self.fields['sesion'].queryset = SesionWhatsApp.objects.filter(status=True)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('contacto_foto',):
                self.fields[k].widget.input_type = 'file'
                self.fields[k].widget.attrs['dropify'] = 'dropify'
                self.fields[k].widget.attrs['accept'] = 'image/*'
            if k in ('sesion',):
                self.fields[k].widget.attrs['class'] = 'select2'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'

class ContactoForm(ModelFormBase):
    class Meta:
        model = Contacto
        fields = ('numero_telefono', 'contacto_nombre', 'contacto_foto')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ContactoForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('contacto_foto',):
                self.fields[k].widget.input_type = 'file'
                self.fields[k].widget.attrs['dropify'] = 'dropify'
                self.fields[k].widget.attrs['accept'] = 'image/*'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class CambiarClasificacionForm(ModelFormBase):
    class Meta:
        model = ConversacionWhatsApp
        fields = ('clasificacion',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(CambiarClasificacionForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('clasificacion',):
                self.fields[k].widget.attrs['class'] = 'jselect2'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class CambiarNombreContactoForm(ModelFormBase):
    class Meta:
        model = Contacto
        fields = ('contacto_nombre',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(CambiarNombreContactoForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class AsignarAgenteForm(ModelFormBase):
    class Meta:
        model = ConversacionWhatsApp
        fields = ('asignado_a', 'nota_interna')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Queryset con carga de trabajo anotada
        agentes = Usuario.objects.filter(is_active=True).annotate(
            carga=Count(
                'conversaciones_asignadas',
                filter=Q(conversaciones_asignadas__conversacion_finalizada=False)
            )
        ).order_by('first_name')

        # Etiquetas con carga: "Juan Pérez (3 activas)"
        choices = [('', '---------')]
        for u in agentes:
            label = u.get_full_name() or u.username
            if u.carga:
                label += f'  ({u.carga} activa{"s" if u.carga != 1 else ""})'
            choices.append((u.pk, label))

        from django import forms as dj_forms
        self.fields['asignado_a'] = dj_forms.ChoiceField(
            choices=choices,
            required=False,
            label='Asignar a',
        )
        self.fields['asignado_a'].widget.attrs['class'] = 'jselect2'
        self.fields['asignado_a'].widget.attrs['col'] = '12'

        self.fields['nota_interna'].widget.attrs['class'] = 'form-control'
        self.fields['nota_interna'].widget.attrs['rows'] = '3'
        self.fields['nota_interna'].widget.attrs['col'] = '12'
        self.fields['nota_interna'].widget.attrs['placeholder'] = 'Nota interna para el agente (no se envía al cliente)…'
        self.fields['nota_interna'].label = 'Nota interna'
        self.fields['nota_interna'].required = False

    def save(self, commit=True):
        instance = super(ModelFormBase, self).save(commit=False)
        pk = self.cleaned_data.get('asignado_a') or None
        instance.asignado_a_id = int(pk) if pk else None
        instance.nota_interna = self.cleaned_data.get('nota_interna', '')
        if commit:
            instance.save(update_fields=['asignado_a', 'nota_interna', 'fecha_asignacion',
                                         'ai_activo'])
        return instance


class MensajeWhatsAppProgramadoForm(ModelFormBase):
    class Meta:
        model = MensajeWhatsAppProgramado
        fields = ('fecha', 'hora', 'mensaje', 'archivo',)

    def __init__(self, *args, **kwargs):
        super(MensajeWhatsAppProgramadoForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('fecha', 'hora',):
                self.fields[k].widget.attrs['col'] = '6'
            if k in ('fecha', 'hora',):
                self.fields[k].label = mark_safe(self.fields[k].label + '<span style="color:red;margin-left:2px;"><strong>*</strong></span>')
                self.fields[k].widget.attrs['required'] = "true"
                self.fields[k].required = True
            if k in ('mensaje',):
                self.fields[k].widget.attrs['rows'] = '10'
                self.fields[k].widget.attrs['class'] = "summernote"
            if k in ('archivo',):
                self.fields[k].widget.attrs['dropify'] = 'dropify'
