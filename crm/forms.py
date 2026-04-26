from django import forms
from django.db import models

from autenticacion.models import Usuario
from core.custom_forms import FormModeloBase
from core.custom_models import ModelFormBase
from crm.models import PerfilNegocioIA, ActividadEconomica, Industria, ProductoIA, ServicioIA, RespuestaEntrenadaIA, \
    DepartamentoChatBot, AgentesIA, ApiKeyIA, HerramientaAgente, FaqAgente


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
    class Meta:
        model = DepartamentoChatBot
        fields = ('nombre', 'color', 'mensaje_saludo',
                  'palabras_clave', 'es_default', 'activo_tradicional')

    def __init__(self, *args, **kwargs):
        ver = kwargs.pop('ver') if 'ver' in kwargs else False
        super(DepartamentoChatBotForm, self).__init__(*args, **kwargs)
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
            elif k in ('es_default', 'activo_tradicional'):
                self.fields[k].widget.attrs['class'] = 'form-check-input'
                self.fields[k].widget.attrs['col'] = '6'
                self.fields[k].required = False

            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'


class AddPerfilDepartamentoChatBotForm(FormModeloBase):
    usuarios = forms.ModelMultipleChoiceField(label='Personas', queryset=Usuario.objects.filter(status=True))


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

_SWITCH_FIELDS = ('anotar_listas', 'humanizar_timing')


class AgentesIAForm(ModelFormBase):
    class Meta:
        model = AgentesIA
        # NOTA: `modelo` ya NO está aquí — ahora vive en ApiKeyIA (diferentes
        # providers por key, cada uno con sus propios modelos).
        fields = (
            'nombre', 'apikey', 'prompt_template', 'anotar_listas',
            'cfg_faiss_k', 'cfg_faiss_fetch_k', 'cfg_max_context_chars', 'cfg_max_static_chars',
            'cfg_history_turns', 'cfg_user_snippet', 'cfg_ai_snippet',
            'cfg_max_output_tokens', 'cfg_topic_anchor_chars',
            # Humanizacion (preset + persona + estilo + timing)
            'personalidad_preset',
            'nombre_bot', 'personalidad', 'tono', 'estilo_escritura', 'temperature',
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
                    if callable(default):
                        try:
                            default = default()
                        except Exception:
                            default = None
                    if default is not None and default != models.NOT_PROVIDED:
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


class ApiKeyIAForm(ModelFormBase):
    class Meta:
        model = ApiKeyIA
        fields = ('alias', 'proveedor', 'modelo', 'descripcion', 'usuario', 'contrasena', 'estado')

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
            if k in ('proveedor',):
                self.fields[k].widget.attrs['class'] = "form-control jselect"
                self.fields[k].widget.attrs['col'] = '6'
            if k == 'modelo':
                self.fields[k].widget.attrs['class'] = 'form-control'
                self.fields[k].widget.attrs['col'] = '6'
            if ver:
                self.fields[k].widget.attrs['readonly'] = 'readonly'



