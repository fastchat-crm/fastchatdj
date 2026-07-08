from django import forms
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db.models import Value
from django.db.models.functions import Concat

from autenticacion.models import Usuario
from core.custom_models import ModelFormBase, FormBase
from core.funciones import generar_nombre
from seguridad.models import Configuracion, Modulo, ModuloGrupo, GroupModulo, Empresa, CredencialMetaApp, CabMarketingMailing, TaskMarketingMail


class ConfiguracionForm(ModelFormBase):
    class Meta:
        model = Configuracion
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion',  'fondo_perfil', 'banner_login','terminosycondiciones',)

    def __init__(self, *args, **kwargs):
        super(ConfiguracionForm, self).__init__(*args, **kwargs)
        self.fields["ico"].widget.attrs['data-default-file'] = self.instance.ico.url if self.instance.ico else ""
        self.fields["logo_sistema"].widget.attrs['data-default-file'] = self.instance.logo_sistema.url if self.instance.logo_sistema else ""
        self.fields["logo_sistema_white"].widget.attrs['data-default-file'] = self.instance.logo_sistema_white.url if self.instance.logo_sistema_white else ""
        # self.fields["imagenprincipal"].widget.attrs['data-default-file'] = self.instance.imagenprincipal.url if self.instance.imagenprincipal else ""
        self.fields["fondoprincipal"].widget.attrs['data-default-file'] = self.instance.fondoprincipal.url if self.instance.fondoprincipal else ""
        self.fields['ico'].widget.attrs['data-allowed-file-extensions'] = "jpg jpeg png tiff svg jfif"
        self.fields['logo_sistema'].widget.attrs['data-allowed-file-extensions'] = "jpg jpeg png tiff svg jfif"
        self.fields['logo_sistema_white'].widget.attrs['data-allowed-file-extensions'] = "jpg jpeg png tiff svg jfif"
        # self.fields['imagenprincipal'].widget.attrs['data-allowed-file-extensions'] = "jpg jpeg png tiff svg jfif"
        self.fields['fondoprincipal'].widget.attrs['data-allowed-file-extensions'] = "jpg jpeg png tiff svg jfif"

        canales = ('canal_whatsapp_qr_activo', 'canal_whatsapp_api_activo',
                   'canal_instagram_activo', 'canal_messenger_activo',
                   'canal_tiktok_activo', 'ia_features_activas', 'tika_activo')
        for k, v in self.fields.items():
            if k in ('ico', 'imagenprincipal', 'imagen_landing', 'logo_sistema', 'logo_sistema_white', 'direccion', 'fondoprincipal', 'nombre_empresa', 'alias', 'descripcion', 'telefono', 'email',  'email_notificacion', 'textoprincipal', 'textosecundario', 'web','titulo','dias_nuevo',):
                self.fields[k].widget.attrs['col'] = "6"
            if k in ('telefono', 'telefono_emergencia'):
                self.fields[k].widget.attrs['pattern'] = "\d*"
                self.fields[k].widget.attrs['title'] = "Sólo números"
                self.fields[k].widget.attrs['onKeyPress'] = "return soloNumeros(event)"
                self.fields[k].widget.attrs['pattern'] = "\d*"
            if k in ('valor_mensual', 'valor_anual'):
                self.fields[k].widget.attrs['title'] = "Sólo números"
                self.fields[k].widget.attrs['onKeyPress'] = "return soloNumeros1(event)"
            if k in canales:
                # NO overridear 'class' — ModelFormBase auto-aplica js-switch +
                # data-render=switchery para que se renderice como Switchery.
                self.fields[k].widget.attrs['col'] = "3"
                self.fields[k].required = False
            if k == 'tika_url':
                self.fields[k].widget.attrs['col'] = "6"
                self.fields[k].required = False
            if k == 'token_ia':
                self.fields[k].widget.attrs['col'] = "6"
                self.fields[k].required = False
                # Mostrar solo keys activas, en formato amigable
                from crm.models import ApiKeyIA
                self.fields[k].queryset = ApiKeyIA.objects.filter(estado=True, status=True).order_by('-id')
                self.fields[k].empty_label = '— Sin API Key (features IA del sistema deshabilitadas) —'


class CredencialMetaAppForm(ModelFormBase):
    class Meta:
        model = CredencialMetaApp
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion',
                   'fecha_registro', 'status', 'configuracion', 'ultima_sincronizacion')

    def __init__(self, *args, **kwargs):
        super(CredencialMetaAppForm, self).__init__(*args, **kwargs)
        # app_secret y system_user_token se muestran como password (render_value
        # para que al editar se vea el valor descifrado actual). Reusamos los
        # attrs que ya seteo el ModelFormBase (form-control, placeholder, etc.)
        # para que el estilo sea identico a los demas inputs.
        for campo in ('app_secret', 'system_user_token'):
            attrs_prev = dict(self.fields[campo].widget.attrs)
            # Quitar attrs de textarea (el campo viene de TextField) que no
            # aplican a un <input type=password>.
            attrs_prev.pop('cols', None)
            attrs_prev.pop('rows', None)
            self.fields[campo].widget = forms.PasswordInput(
                render_value=True, attrs=attrs_prev,
            )
        for k in self.fields:
            if k != 'es_tech_provider':
                self.fields[k].widget.attrs.setdefault('class', 'form-control')
            if k in ('app_id', 'app_secret', 'business_id', 'system_user_id'):
                self.fields[k].widget.attrs['col'] = "6"
            if k == 'system_user_token':
                self.fields[k].widget.attrs['col'] = "12"
            if k == 'es_tech_provider':
                self.fields[k].widget.attrs['col'] = "12"
                self.fields[k].required = False
            self.fields[k].widget.attrs.setdefault('autocomplete', 'off')


class ConfiguracionTerminosForm(ModelFormBase):
    class Meta:
        model = Configuracion
        fields = ('terminosycondiciones',)

    def __init__(self, *args, **kwargs):
        super(ConfiguracionTerminosForm, self).__init__(*args, **kwargs)


class ModuloForm(ModelFormBase):
    class Meta:
        model = Modulo
        exclude = ( 'usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')


class GroupForm(ModelFormBase):
    class Meta:
        model = Group
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super(GroupForm, self).__init__(*args, **kwargs)
        self.fields['permissions'].queryset = self.fields['permissions'].queryset.\
            annotate(full_name_db=Concat('content_type__app_label', Value('__'), 'content_type__model')).\
            exclude(full_name_db__in=['sessions__session', 'auth__permission', 'contenttypes__contenttype',
                                     'admin__logentry', 'authtoken__token', 'seguridad__usuarioconectado', 'seguridad__carousel', 'seguridad__redsocial', 'seguridad__errorlog', 'seguridad__audiusuariotabla',
                                     'background_task__completedtask', 'background_task__task', 'webpush__subscriptioninfo',
                                      'webpush__pushinformation', 'webpush__group', 'authtoken__tokenproxy', 'ventas__pedidodetalle',
                                      'autenticacion__codigo', 'seguridad__usuarionotificacion', 'seguridad__sessionuser']).\
            exclude(content_type__app_label__in=("dobra", "reportes"))

        for k, v in self.fields.items():
            self.fields[k].widget.attrs['col'] = "12"

class ModuloGrupoForm(ModelFormBase):
    class Meta:
        model = ModuloGrupo
        exclude = ( 'usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        kwargs["no_requeridos"] = ["modulos"]
        super(ModuloGrupoForm, self).__init__(*args, **kwargs)
        self.fields['modulos'].queryset = self.fields['modulos'].queryset.order_by('orden')
        self.fields['modulos'].widget = forms.HiddenInput()
        self.initial["modulos"] = ""


class GroupModuloForm(ModelFormBase):
    class Meta:
        model = GroupModulo
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        kwargs["no_requeridos"] = ["modulos", "group"]
        super(GroupModuloForm, self).__init__(*args, **kwargs)
        self.fields['modulos'].queryset = self.fields['modulos'].queryset.order_by('orden')
        self.fields["group"].widget = forms.HiddenInput()
        self.fields["group"].required = False  # ✅ también puedes ponerlo explícito por si acaso


class EmpresaForm(FormBase):
    nombre = forms.CharField(label='Nombre', max_length=100, required=True)
    responsables = forms.ModelMultipleChoiceField(label='Responsables',queryset=Usuario.objects.filter(status=True))
    logo = forms.ImageField(label='Logo', required=False)

    def clean(self):
        cleaned_data = super().clean()
        archivo = cleaned_data.get('logo', None)
        if archivo:
            # Validar tamaño del archivo (máximo 4 MB)
            if archivo.size > 4 * 1024 * 1024:
                self.add_error('logo', "El archivo no debe exceder los 4 MB.")
        return cleaned_data

    def save(self, commit=True, request=None):
        cleaned_data = self.cleaned_data
        archivo = cleaned_data.get('logo', None)
        empresa = self.instance if self.instance else Empresa()
        if archivo:
            extension = archivo.name.split('.')[-1]
            archivo._name = generar_nombre(f'logo_{empresa.id}', f'archivo.{extension}')
            empresa.logo = archivo
        empresa.nombre = cleaned_data.get('nombre', '')
        if commit:
            empresa.save(request)
            responsables = cleaned_data.get('responsables', None)
            if responsables:
                empresa.responsables.set(responsables)
            else:
                empresa.responsables.clear()
        return empresa


class CabMarketingMailingForm(ModelFormBase):
    class Meta:
        model = CabMarketingMailing
        fields = ('name', 'file')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['file'].widget = forms.FileInput(attrs={'class': 'dropify', 'col': '12'})
        self.fields['file'].required = True
        self.fields['file'].help_text = u'Max size 10MB, .xls or .xlsx format'


class MarketingMailSendForm(ModelFormBase):
    class Meta:
        model = TaskMarketingMail
        fields = ('cab', 'title', 'body', 'envia_copia', 'correo_copia', 'image')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cab'].widget.attrs['class'] = 'jselect2'
        self.fields['cab'].queryset = CabMarketingMailing.objects.filter(status=True)
        self.fields['body'].widget = forms.Textarea(attrs={'rows': '5', 'class': 'summernote'})
        self.fields['image'].widget = forms.FileInput(attrs={'class': 'dropify', 'col': '12'})
        self.fields['correo_copia'].widget.attrs['placeholder'] = 'Enter the CC email address'
        self.fields['title'].widget.attrs['placeholder'] = 'Enter the email subject'


class SendMailingForm(ModelFormBase):
    class Meta:
        model = TaskMarketingMail
        fields = ()
