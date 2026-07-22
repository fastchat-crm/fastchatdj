from django import forms
from django.db import models

from autenticacion.models import Usuario
from core.custom_forms import FormModeloBase
from core.custom_models import ModelFormBase
from crm.models import PerfilNegocioIA, ActividadEconomica, Industria, ProductoIA, ServicioIA, RespuestaEntrenadaIA, \
    DepartamentoChatBot, AgentesIA, ApiKeyIA, HerramientaAgente, FaqAgente, \
    EndpointApiChatbot, CredencialApiChatbot, Cliente


class PerfilNegocioIAForm(ModelFormBase):
    class Meta:
        model = PerfilNegocioIA
        fields = (
            'industria', 'actividad', 'nombre_empresa', 'sitio_web', 'localidad',
            'publico_objetivo', 'descripcion_empresa',
        )

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        self.fields['industria'].queryset = Industria.objects.filter(status=True)
        self.fields['industria'].widget.attrs['data-urladd'] = "/crm/entrenamiento/?action=add_new_industria"
        self.fields['actividad'].queryset = ActividadEconomica.objects.filter(status=True)
        self.fields['actividad'].widget.attrs['data-urladd'] = "/crm/entrenamiento/?action=add_new_actividad"
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].required = True
            if k in ('descripcion_empresa', 'publico_objetivo'):
                self.fields[k].widget.attrs['rows'] = 3
            if k in ('industria', 'actividad'):
                self.fields[k].widget.attrs['class'] = 'form-control select2'
            if k in ('industria', 'actividad', 'nombre_empresa', 'sitio_web', 'localidad'):
                self.fields[k].widget.attrs['col'] = '6'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class IndustriaForm(ModelFormBase):
    class Meta:
        model = Industria
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(IndustriaForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ActividadEconomicaForm(ModelFormBase):
    class Meta:
        model = ActividadEconomica
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ActividadEconomicaForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ProductoIAForm(ModelFormBase):
    class Meta:
        model = ProductoIA
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status', 'perfil')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ProductoIAForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class ServicioIAForm(ModelFormBase):
    class Meta:
        model = ServicioIA
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status', 'perfil')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(ServicioIAForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class RespuestaEntrenadaIAForm(ModelFormBase):
    class Meta:
        model = RespuestaEntrenadaIA
        exclude = ('usuario_modificacion', 'fecha_modificacion', 'usuario_creacion', 'fecha_registro', 'status', 'perfil')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(RespuestaEntrenadaIAForm, self).__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'



class DepartamentoChatBotForm(ModelFormBase):
    # Campo virtual: el operador edita una línea por trigger (más cómodo que
    # un JSON crudo). Se serializa a lista al guardar.
    reset_triggers_lineas = forms.CharField(
        required=False,
        label='Triggers de reset',
        help_text='Una palabra/frase por línea. Si el cliente envía cualquiera, '
                  'el flujo se reinicia desde el saludo. Aplica a este depto solamente.',
        widget=forms.Textarea(attrs={
            'rows': 4, 'col': '12',
            'placeholder': 'reiniciar\ncancelar\nvolver al inicio\notra placa',
        }),
    )

    class Meta:
        model = DepartamentoChatBot
        fields = ('nombre', 'color', 'mensaje_saludo',
                  'palabras_clave', 'es_default', 'activo_tradicional',
                  'mensaje_reset')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(DepartamentoChatBotForm, self).__init__(*args, **kwargs)
        # Pre-cargar triggers existentes en formato textarea.
        if self.instance and self.instance.pk:
            triggers = self.instance.reset_triggers or []
            if isinstance(triggers, list):
                self.fields['reset_triggers_lineas'].initial = '\n'.join(
                    str(t) for t in triggers if str(t or '').strip()
                )
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            if k in ('nombre',):
                self.fields[k].widget.attrs['col'] = '8'
                self.fields[k].widget.attrs['placeholder'] = 'Ej: Matrículas y cobranzas'
            elif k in ('color',):
                self.fields[k].widget.attrs['col'] = '4'
                self.fields[k].widget = forms.TextInput(attrs={
                    'type': 'color', 'class': 'form-control', 'col': '4',
                })
            elif k == 'mensaje_saludo':
                self.fields[k].widget.attrs['rows'] = 3
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['placeholder'] = (
                    '🎓 Hola {{contacto.nombre}}, bienvenido al Centro de Atención. '
                    '¿En qué te ayudo hoy?'
                )
                self.fields[k].required = False
            elif k == 'palabras_clave':
                self.fields[k].widget.attrs['rows'] = 4
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['placeholder'] = (
                    'matricula\nmatrícula\ninscripción\npago\nsaldo'
                )
                self.fields[k].required = False
            elif k == 'mensaje_reset':
                self.fields[k].widget.attrs['rows'] = 2
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['placeholder'] = (
                    '🔄 Empezamos de nuevo. ¿En qué te ayudo?'
                )
                self.fields[k].required = False
            elif k in ('es_default', 'activo_tradicional'):
                self.fields[k].widget.attrs['class'] = 'form-check-input'
                self.fields[k].widget.attrs['col'] = '6'
                self.fields[k].required = False

            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw = self.cleaned_data.get('reset_triggers_lineas') or ''
        instance.reset_triggers = [
            line.strip().lower() for line in raw.splitlines() if line.strip()
        ]
        if commit:
            instance.save()
        return instance


_CFG_RANGES = {
    'cfg_faiss_k':            (1, 20),
    'cfg_faiss_fetch_k':      (5, 80),
    'cfg_max_context_chars':  (500, 16000),
    'cfg_max_static_chars':   (500, 10000),
    'cfg_history_turns':      (1, 30),
    'cfg_user_snippet':       (50, 1500),
    'cfg_ai_snippet':         (50, 4000),
    'cfg_max_output_tokens':  (200, 8000),
    'cfg_topic_anchor_chars': (50, 800),
    # Humanizacion — rangos que <input type=number> enforza en el browser
    'humaniz_chars_burbuja_ideal': (80,  400),
    'humaniz_chars_burbuja_max':   (150, 600),
    'humaniz_max_burbujas':        (1,   8),
    'humaniz_lectura_cps':         (30,  200),
    'humaniz_escritura_cps':       (10,  60),
}

_CFG_RANGES_FLOAT = {
    'temperature':                 (0.0,  1.0, 0.05),
    'humaniz_lectura_max_seg':     (1.0,  10.0, 0.5),
    'humaniz_escritura_min_seg':   (0.0,  3.0, 0.1),
    'humaniz_escritura_max_seg':   (2.0,  15.0, 0.5),
}

_SWITCH_FIELDS = ('anotar_listas', 'humanizar_timing', 'memoria_rag_activa')


class AgentesIAForm(ModelFormBase):
    class Meta:
        model = AgentesIA
        # NOTA: `modelo` ya NO está aquí — ahora vive en ApiKeyIA (diferentes
        # providers por key, cada uno con sus propios modelos).
        fields = (
            'nombre', 'apikey', 'prompt_template', 'anotar_listas',
            'cfg_faiss_k', 'cfg_faiss_fetch_k', 'cfg_max_context_chars', 'cfg_max_static_chars',
            'cfg_history_turns', 'cfg_user_snippet', 'cfg_ai_snippet',
            'cfg_max_output_tokens', 'cfg_topic_anchor_chars', 'memoria_rag_activa',
            # Humanizacion (preset + persona + estilo + timing)
            'personalidad_preset',
            'nombre_bot', 'mensaje_bienvenida', 'personalidad', 'tono', 'estilo_escritura', 'temperature',
            'humanizar_timing',
            'humaniz_chars_burbuja_ideal', 'humaniz_chars_burbuja_max', 'humaniz_max_burbujas',
            'humaniz_lectura_cps', 'humaniz_escritura_cps',
            'humaniz_lectura_max_seg', 'humaniz_escritura_min_seg', 'humaniz_escritura_max_seg',
        )

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        self.fields['apikey'].queryset = ApiKeyIA.objects.filter(status=True)

        # Si es un agente nuevo (sin pk), forzamos que cada input arranque con
        # el default del modelo como valor inicial. Django ModelForm ya lo hace
        # para algunos casos pero con defaults que son callables o Decimal/enum
        # a veces queda en blanco; esto normaliza el comportamiento asi el
        # usuario ve los valores recomendados listos para aceptar o ajustar.
        if not (self.instance and self.instance.pk):
            for name, f in self.fields.items():
                try:
                    model_field = AgentesIA._meta.get_field(name)
                except Exception:
                    continue
                if f.initial in (None, ''):
                    default = getattr(model_field, 'default', None)
                    # NOT_PROVIDED es la clase sentinel cuando el field no tiene
                    # default. Es callable (cualquier clase lo es), asi que hay
                    # que descartarla antes de invocar default().
                    if default is models.NOT_PROVIDED:
                        continue
                    if callable(default):
                        try:
                            default = default()
                        except Exception:
                            default = None
                    if default is not None:
                        f.initial = default
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('apikey', 'tono'):
                self.fields[k].widget.attrs['class'] = 'select2'
            if k in _SWITCH_FIELDS:
                self.fields[k].widget.attrs['class'] = "js-switch"
                self.fields[k].widget.attrs['data-render'] = "switchery"
                self.fields[k].widget.attrs['data-theme'] = "default"
                self.fields[k].widget.attrs['col'] = '12'
            if k in _CFG_RANGES:
                lo, hi = _CFG_RANGES[k]
                self.fields[k].widget.attrs['class'] = 'form-control form-control-sm'
                self.fields[k].widget.attrs['col'] = '6'
                self.fields[k].widget.attrs['min'] = str(lo)
                self.fields[k].widget.attrs['max'] = str(hi)
                self.fields[k].widget.input_type = 'number'
            if k in _CFG_RANGES_FLOAT:
                lo, hi, step = _CFG_RANGES_FLOAT[k]
                self.fields[k].widget.attrs['class'] = 'form-control form-control-sm'
                self.fields[k].widget.attrs['col'] = '6'
                self.fields[k].widget.attrs['min']  = str(lo)
                self.fields[k].widget.attrs['max']  = str(hi)
                self.fields[k].widget.attrs['step'] = str(step)
                self.fields[k].widget.input_type = 'number'
            if k in ('personalidad', 'estilo_escritura'):
                self.fields[k].widget.attrs['rows'] = '3'
                self.fields[k].widget.attrs['col']  = '12'
            if k == 'mensaje_bienvenida':
                self.fields[k].widget.attrs['rows'] = '3'
                self.fields[k].widget.attrs['col']  = '12'
                self.fields[k].widget.attrs['placeholder'] = (
                    'Ej: ¡Hola! 👋 Soy Sofía. Te ayudo con tu plan de salud. '
                    '¿Me das tu cédula (10 dígitos) para empezar?'
                )
            if k in ('nombre_bot',):
                self.fields[k].widget.attrs['col'] = '6'
            if k == 'personalidad_preset':
                # El preset se elige clickeando una card visual; el <select>
                # lo dejamos visible como fallback accesible y para form post.
                self.fields[k].widget.attrs['class'] = 'form-select form-select-sm personalidad-preset-select'
                self.fields[k].widget.attrs['col'] = '12'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class HerramientaAgenteForm(ModelFormBase):
    class Meta:
        model = HerramientaAgente
        fields = (
            'nombre_amigable', 'nombre', 'descripcion', 'metodo', 'url',
            'ubicacion_params', 'timeout', 'plantilla_respuesta', 'activo',
        )

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control form-control-sm'
            self.fields[k].widget.attrs['col'] = '12'
            if k in ('metodo', 'ubicacion_params'):
                self.fields[k].widget.attrs['class'] = 'form-select form-select-sm'
                self.fields[k].widget.attrs['col'] = '6'
            if k == 'timeout':
                self.fields[k].widget.attrs['col'] = '6'
                self.fields[k].widget.attrs['min'] = '1'
                self.fields[k].widget.attrs['max'] = '30'
            if k == 'activo':
                self.fields[k].widget.attrs['class'] = "js-switch"
                self.fields[k].widget.attrs['data-render'] = "switchery"
                self.fields[k].widget.attrs['data-theme'] = "default"
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class FaqAgenteForm(ModelFormBase):
    class Meta:
        model = FaqAgente
        fields = ('pregunta', 'respuesta', 'prioridad', 'estado')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control form-control-sm'
            self.fields[k].widget.attrs['col'] = '12'
            if k == 'prioridad':
                self.fields[k].widget.attrs['col'] = '6'
                self.fields[k].widget.attrs['min'] = '0'
                self.fields[k].widget.attrs['max'] = '100'
            if k == 'estado':
                self.fields[k].widget.attrs['class'] = 'form-select form-select-sm'
                self.fields[k].widget.attrs['col'] = '6'
            if k in ('pregunta', 'respuesta'):
                self.fields[k].widget.attrs['rows'] = '2' if k == 'pregunta' else '3'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


_PREFIJO_MODELO_POR_PROVEEDOR = {2: 'gemini-', 3: 'gpt-', 4: 'claude-', 6: 'deepseek-'}
_NOMBRE_PROVEEDOR = {2: 'Gemini', 3: 'OpenAI', 4: 'Claude', 5: 'Ollama', 6: 'DeepSeek', 7: 'Huawei MaaS', 8: 'Ollama Local'}
_PROVEEDORES_REQUIEREN_BASE_URL = (7,)


class ApiKeyIAForm(ModelFormBase):
    class Meta:
        model = ApiKeyIA
        fields = ('alias', 'proveedor', 'modelo', 'descripcion', 'base_url', 'usuario', 'contrasena', 'estado')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        for k, v in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '6'
            if k in ('estado'):
                self.fields[k].widget.attrs['class'] = "js-switch"
                self.fields[k].widget.attrs['data-render'] = "switchery"
                self.fields[k].widget.attrs['data-theme'] = "default"
                self.fields[k].widget.attrs['col'] = '3'
            if k in ('descripcion',):
                self.fields[k].widget.attrs['col'] = '12'
            if k in ('base_url',):
                self.fields[k].required = False
                self.fields[k].widget.attrs['col'] = '12'
                self.fields[k].widget.attrs['placeholder'] = 'http://localhost:11434 (Ollama) · URL del despliegue (Huawei MaaS) · vacío = default'
            if k in ('proveedor',):
                self.fields[k].widget.attrs['class'] = "form-control jselect"
                self.fields[k].widget.attrs['col'] = '6'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'

    def clean(self):
        cleaned = super().clean()
        proveedor = cleaned.get('proveedor')
        modelo = (cleaned.get('modelo') or '').strip()
        base_url = (cleaned.get('base_url') or '').strip()
        if proveedor and modelo:
            prefijo = _PREFIJO_MODELO_POR_PROVEEDOR.get(proveedor)
            if prefijo and not modelo.startswith(prefijo):
                nombre = _NOMBRE_PROVEEDOR.get(proveedor, 'el proveedor seleccionado')
                self.add_error('modelo', f'El modelo seleccionado no es compatible con {nombre}. Elige un modelo que empiece con "{prefijo}" o déjalo vacío para usar el default.')
        if proveedor in _PROVEEDORES_REQUIEREN_BASE_URL and not base_url:
            nombre = _NOMBRE_PROVEEDOR.get(proveedor, 'este proveedor')
            self.add_error('base_url', f'{nombre} requiere la Base URL del despliegue.')
        if proveedor in (2, 3, 4, 5) and base_url:
            cleaned['base_url'] = ''
        return cleaned


class CredencialApiChatbotForm(ModelFormBase):
    """Form de credenciales API (Bearer / Basic / ApiKey / Custom).
    `secretos` es un JSON libre — el contenido depende de `tipo`.
    """
    class Meta:
        model = CredencialApiChatbot
        fields = ('nombre', 'tipo', 'secretos', 'descripcion')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        for k, _ in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'
        self.fields['nombre'].widget.attrs['col'] = '6'
        self.fields['tipo'].widget.attrs['col'] = '6'
        self.fields['tipo'].widget.attrs['class'] = 'form-control jselect'
        self.fields['secretos'].widget = forms.Textarea(attrs={
            'class': 'form-control font-monospace', 'rows': 4, 'col': '12',
            'placeholder': 'Bearer: {"token": "..."} · Basic: {"usuario": "...", "password": "..."} · '
                           'ApiKey header: {"nombre_header": "X-API-Key", "valor": "..."}',
        })
        self.fields['descripcion'].widget = forms.Textarea(attrs={
            'class': 'form-control', 'rows': 2, 'col': '12',
        })


class EndpointApiChatbotForm(ModelFormBase):
    """Form de endpoints API reutilizables (host + auth + headers default)."""
    class Meta:
        model = EndpointApiChatbot
        fields = ('nombre', 'base_url', 'credencial', 'headers_default',
                  'timeout_seg', 'descripcion')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        self.fields['credencial'].queryset = CredencialApiChatbot.objects.filter(
            status=True
        ).order_by('nombre')
        self.fields['credencial'].required = False
        self.fields['credencial'].empty_label = '— Sin credencial (público) —'
        for k, _ in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '12'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'
        self.fields['nombre'].widget.attrs['col'] = '6'
        self.fields['timeout_seg'].widget.attrs['col'] = '6'
        self.fields['base_url'].widget.attrs['col'] = '12'
        self.fields['base_url'].widget.attrs['placeholder'] = 'https://api.miservicio.com'
        self.fields['credencial'].widget.attrs['col'] = '12'
        self.fields['credencial'].widget.attrs['class'] = 'form-control jselect'
        self.fields['headers_default'].widget = forms.Textarea(attrs={
            'class': 'form-control font-monospace', 'rows': 3, 'col': '12',
            'placeholder': '{"Accept": "application/json", "Content-Type": "application/json"}',
        })
        self.fields['descripcion'].widget = forms.Textarea(attrs={
            'class': 'form-control', 'rows': 2, 'col': '12',
        })


class ClienteForm(ModelFormBase):
    class Meta:
        model = Cliente
        fields = (
            'cedula', 'nombres', 'apellidos', 'email', 'telefono', 'ciudad',
            'edad', 'fecha_nacimiento', 'sexo', 'canal_origen',
            'contacto_origen', 'conversacion_origen', 'sesion_origen',
            'departamento_origen', 'notas',
        )

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super().__init__(*args, **kwargs)
        for k, _ in self.fields.items():
            self.fields[k].widget.attrs['class'] = 'form-control'
            self.fields[k].widget.attrs['col'] = '6'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'
        self.fields['notas'].widget = forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3, 'col': '12',
        })
        for fk in ('contacto_origen', 'conversacion_origen',
                   'sesion_origen', 'departamento_origen'):
            self.fields[fk].widget.attrs['class'] = 'form-control select2'
            self.fields[fk].required = False



