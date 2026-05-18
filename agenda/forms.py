from django import forms

from .models import (
    EXCEPTION_TYPE_CHOICES,
    ExcepcionAgenda,
    GrupoAgenda,
    Recurso,
    Servicio,
)


class GrupoAgendaForm(forms.ModelForm):
    class Meta:
        model = GrupoAgenda
        fields = ['nombre', 'descripcion', 'moneda', 'recordatorio_horas_antes', 'zona_horaria', 'responsable']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 120,
                                             'placeholder': 'Ej: Clínica Central, Estudio A'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'maxlength': 500,
                                                 'placeholder': 'Notas opcionales sobre este grupo'}),
            'moneda': forms.Select(attrs={'class': 'form-select'}),
            'recordatorio_horas_antes': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 240}),
            'zona_horaria': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 64,
                                                   'placeholder': 'Ej: America/Guayaquil, UTC'}),
            'responsable': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        from autenticacion.models import Usuario
        self.fields['responsable'].queryset = Usuario.objects.filter(is_active=True).order_by('first_name', 'last_name')
        self.fields['responsable'].required = False
        self.fields['responsable'].empty_label = '— Ninguno —'
        for field in self.fields.values():
            field.required = field.required and field.label not in ('Descripción', 'Responsable')

    def save(self, commit=True):
        obj = super().save(commit=False)
        if commit:
            if self.request:
                obj.save(request=self.request)
            else:
                obj.save()
        return obj


class RecursoForm(forms.ModelForm):
    class Meta:
        model = Recurso
        fields = ['grupo_agenda', 'nombre', 'descripcion', 'color', 'usuario']
        widgets = {
            'grupo_agenda': forms.HiddenInput(),
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 120,
                                             'placeholder': 'Ej: Dr. Pérez, Box 1'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'maxlength': 500,
                                                 'placeholder': 'Notas opcionales'}),
            'color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color w-100',
                                            'style': 'height:38px;'}),
            'usuario': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        from autenticacion.models import Usuario
        self.fields['grupo_agenda'].queryset = GrupoAgenda.objects.filter(status=True).order_by('nombre')
        self.fields['usuario'].queryset = Usuario.objects.filter(is_active=True).order_by('first_name', 'last_name')
        self.fields['usuario'].required = False
        self.fields['usuario'].empty_label = '— Ninguno —'
        self.fields['descripcion'].required = False

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.pk:
            obj.orden = Recurso.objects.filter(grupo_agenda=obj.grupo_agenda, status=True).count()
        if commit:
            if self.request:
                obj.save(request=self.request)
            else:
                obj.save()
        return obj


class ServicioForm(forms.ModelForm):
    recursos = forms.ModelMultipleChoiceField(
        queryset=Recurso.objects.filter(status=True),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2'}),
        label='Recursos que ofrecen este servicio',
    )

    class Meta:
        model = Servicio
        fields = ['grupo_agenda', 'nombre', 'descripcion', 'duracion_min', 'precio', 'recursos']
        widgets = {
            'grupo_agenda': forms.HiddenInput(),
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 150,
                                             'placeholder': 'Ej: Consulta general, Corte de cabello'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'maxlength': 500,
                                                 'placeholder': 'Detalles opcionales mostrados en el menú del chatbot'}),
            'duracion_min': forms.NumberInput(attrs={'class': 'form-control', 'min': 5, 'max': 1440}),
            'precio': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        grupo_id = kwargs.pop('grupo_id', None)
        super().__init__(*args, **kwargs)
        self.fields['grupo_agenda'].queryset = GrupoAgenda.objects.filter(status=True).order_by('nombre')
        instance = kwargs.get('instance') or self.instance
        grupo_filtrar = None
        if instance and instance.pk and instance.grupo_agenda_id:
            grupo_filtrar = instance.grupo_agenda_id
        elif grupo_id:
            grupo_filtrar = int(grupo_id)
        if grupo_filtrar:
            self.fields['recursos'].queryset = Recurso.objects.filter(
                grupo_agenda_id=grupo_filtrar, status=True,
            ).order_by('orden', 'nombre')
        else:
            self.fields['recursos'].queryset = Recurso.objects.filter(status=True).order_by('grupo_agenda', 'orden', 'nombre')
        self.fields['descripcion'].required = False

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.pk:
            obj.orden = Servicio.objects.filter(grupo_agenda=obj.grupo_agenda, status=True).count()
        if commit:
            if self.request:
                obj.save(request=self.request)
            else:
                obj.save()
            self.save_m2m()
        return obj


class ExcepcionAgendaForm(forms.ModelForm):
    class Meta:
        model = ExcepcionAgenda
        fields = ['recurso', 'fecha', 'tipo', 'hora_inicio', 'hora_fin', 'motivo']
        widgets = {
            'recurso': forms.Select(attrs={'class': 'form-select'}),
            'fecha': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select', 'id': 'id_tipo_excepcion'}),
            'hora_inicio': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'hora_fin': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'motivo': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 255,
                                             'placeholder': 'Opcional: feriado, vacaciones, almuerzo, etc.'}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        grupo_id = kwargs.pop('grupo_id', None)
        super().__init__(*args, **kwargs)
        recursos_qs = Recurso.objects.filter(status=True).select_related('grupo_agenda')
        instance = kwargs.get('instance') or self.instance
        grupo_filtrar = None
        if instance and instance.pk and instance.recurso_id:
            grupo_filtrar = instance.recurso.grupo_agenda_id
        elif grupo_id:
            grupo_filtrar = int(grupo_id)
        if grupo_filtrar:
            recursos_qs = recursos_qs.filter(grupo_agenda_id=grupo_filtrar)
        self.fields['recurso'].queryset = recursos_qs.order_by('grupo_agenda', 'orden', 'nombre')
        self.fields['hora_inicio'].required = False
        self.fields['hora_fin'].required = False
        self.fields['motivo'].required = False

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('tipo')
        hi = cleaned.get('hora_inicio')
        hf = cleaned.get('hora_fin')
        if tipo in ('block_range', 'add_range'):
            if not hi or not hf:
                raise forms.ValidationError('El rango horario requiere hora de inicio y fin.')
            if hi >= hf:
                raise forms.ValidationError('La hora de inicio debe ser anterior a la de fin.')
        if tipo == 'block_day':
            cleaned['hora_inicio'] = None
            cleaned['hora_fin'] = None
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.tipo == 'block_day':
            obj.hora_inicio = None
            obj.hora_fin = None
        if commit:
            if self.request:
                obj.save(request=self.request)
            else:
                obj.save()
        return obj
