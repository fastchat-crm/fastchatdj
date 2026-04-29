from django.db.models import Count, Q
from django.utils.safestring import mark_safe

from autenticacion.models import Usuario
from core.custom_models import ModelFormBase
from crm.models import DepartamentoChatBot
from .models import (
    SesionWhatsApp, Contacto, ConversacionWhatsApp, MensajeWhatsAppProgramado,
    ConfigMeta, PlantillaWhatsApp, ConfigInstagram, ConfigMessenger,
)


class SesionWhatsAppForm(ModelFormBase):
    class Meta:
        model = SesionWhatsApp
        fields = ('nombre', 'numero', 'min_sesion', 'language', 'proveedor',
                  'modo_bot', 'agente_ia',
                  'departamentos', 'departamento_default',
                  'mensaje_bienvenida', 'mensaje_despedida', 'mensaje_handoff',)

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(SesionWhatsAppForm, self).__init__(*args, **kwargs)
        self.fields['departamentos'].queryset = DepartamentoChatBot.objects.filter(status=True).order_by('nombre')
        self.fields['departamento_default'].queryset = DepartamentoChatBot.objects.filter(status=True).order_by('nombre')
        self.fields['departamento_default'].required = False
        self.fields['departamento_default'].empty_label = '— (ninguno) —'
        # El numero se llena solo (Baileys via QR, Meta via Graph API), pero
        # permitimos edicion manual por si el cliente quiere adelantarlo o
        # corregir algun caso borde. No es obligatorio.
        self.fields['numero'].required = False
        # ModelFormBase ya agrego el asterisco al label en su __init__ porque
        # el campo era required antes de este override. Lo reseteamos a texto
        # plano para que el label no muestre "Numero WhatsApp*".
        self.fields['numero'].label = 'Número WhatsApp'
        self.fields['numero'].widget.attrs['placeholder'] = 'Se detecta automaticamente (o escribilo si ya lo sabes)'
        self.fields['numero'].widget.attrs['inputmode'] = 'tel'
        self.fields['numero'].widget.attrs['autocomplete'] = 'off'
        self.fields['numero'].widget.attrs['pattern'] = '[0-9+\\-\\s]*'
        self.fields['numero'].widget.attrs['maxlength'] = '20'
        for k, v in self.fields.items():
            if k in ('mensaje_bienvenida', 'mensaje_despedida', 'mensaje_handoff',):
                self.fields[k].widget.attrs['rows'] = '5'
                self.fields[k].widget.attrs['class'] = "summernote"
            if k in ('min_sesion',):
                self.fields[k].widget.attrs['col'] = '3'
            if k in ('departamentos', 'departamento_default', 'language', 'agente_ia', 'proveedor'):
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['class'] = "jselect2"
            if k in ('proveedor',):
                self.fields[k].required = True
            if k in ('departamentos', 'departamento_default', 'language', 'agente_ia'):
                self.fields[k].required = False
            if k in ('modo_bot',):
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['class'] = "form-control"
            if k in ('nombre',):
                self.fields[k].widget.attrs['col'] = '9'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class PlantillaWhatsAppForm(ModelFormBase):
    class Meta:
        model = PlantillaWhatsApp
        fields = ('nombre', 'idioma', 'categoria',
                  'header_tipo', 'header_contenido',
                  'cuerpo', 'footer')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(PlantillaWhatsAppForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '6'
            if k in ('nombre',):
                self.fields[k].widget.attrs['placeholder'] = 'confirmacion_cita'
                self.fields[k].widget.attrs['pattern'] = '[a-z0-9_]+'
                self.fields[k].help_text = 'Solo minusculas, numeros y guiones bajos. Es el identificador en Meta.'
            if k in ('cuerpo',):
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['rows'] = '5'
                self.fields[k].widget.attrs['placeholder'] = 'Hola {{1}}, tu cita esta confirmada para el {{2}}.'
            if k in ('header_contenido', 'footer'):
                self.fields[k].widget.attrs['col'] = '12'
            if k in ('categoria', 'header_tipo', 'idioma'):
                self.fields[k].widget.attrs['class'] = 'form-control jselect2'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ConfigMetaForm(ModelFormBase):
    class Meta:
        model = ConfigMeta
        fields = ('waba_id', 'phone_number_id', 'business_account_id',
                  'display_phone_number', 'access_token',
                  'webhook_verify_token')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ConfigMetaForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            # Los campos Meta se guardan por la accion "guardar_config_meta"
            # (no por el submit principal del form de sesion). Los marcamos como
            # no requeridos a nivel HTML/Django para evitar que bloqueen el
            # submit principal cuando la sesion esta en modo Baileys. La
            # validacion real se hace manualmente en la vista.
            self.fields[k].required = False
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '6'
            self.fields[k].widget.attrs.pop('required', None)
            if k == 'access_token':
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['rows'] = '3'
            if k == 'webhook_verify_token':
                self.fields[k].widget.attrs['readonly'] = 'readonly'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ConfigInstagramForm(ModelFormBase):
    """Form para Instagram DM (Graph API). Mismo patron que ConfigMetaForm:
    todos los campos required=False a nivel HTML para no bloquear el submit
    del form principal de sesion. La validacion real se hace en la accion."""
    class Meta:
        model = ConfigInstagram
        fields = ('ig_user_id', 'page_id', 'username', 'access_token',
                  'webhook_verify_token')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].required = False
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '6'
            self.fields[k].widget.attrs.pop('required', None)
            if k == 'access_token':
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['rows'] = '3'
            if k == 'webhook_verify_token':
                self.fields[k].widget.attrs['readonly'] = 'readonly'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ConfigMessengerForm(ModelFormBase):
    """Form para Facebook Messenger (Page DMs). Igual patron que IG."""
    class Meta:
        model = ConfigMessenger
        fields = ('page_id', 'page_name', 'access_token',
                  'webhook_verify_token')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].required = False
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '6'
            self.fields[k].widget.attrs.pop('required', None)
            if k == 'access_token':
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['rows'] = '3'
            if k == 'webhook_verify_token':
                self.fields[k].widget.attrs['readonly'] = 'readonly'
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
