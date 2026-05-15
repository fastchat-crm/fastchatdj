from django.contrib import admin

from .models import (
    ExcepcionAgenda,
    GrupoAgenda,
    HorarioLaboral,
    Recurso,
    Servicio,
    Turno,
)


@admin.register(GrupoAgenda)
class GrupoAgendaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'moneda', 'recordatorio_horas_antes', 'zona_horaria', 'status')
    search_fields = ('nombre', 'descripcion')
    list_filter = ('moneda', 'status')


@admin.register(Recurso)
class RecursoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'grupo_agenda', 'orden', 'color', 'usuario', 'status')
    search_fields = ('nombre', 'grupo_agenda__nombre')
    list_filter = ('grupo_agenda', 'status')
    raw_id_fields = ('usuario',)
    ordering = ('grupo_agenda', 'orden', 'nombre')


@admin.register(HorarioLaboral)
class HorarioLaboralAdmin(admin.ModelAdmin):
    list_display = ('id', 'recurso', 'dia_semana', 'hora_inicio', 'hora_fin', 'duracion_slot_min', 'status')
    list_filter = ('dia_semana', 'recurso__grupo_agenda', 'status')
    search_fields = ('recurso__nombre',)


@admin.register(ExcepcionAgenda)
class ExcepcionAgendaAdmin(admin.ModelAdmin):
    list_display = ('id', 'recurso', 'fecha', 'tipo', 'hora_inicio', 'hora_fin', 'motivo', 'status')
    list_filter = ('tipo', 'recurso__grupo_agenda', 'status')
    search_fields = ('recurso__nombre', 'motivo')
    date_hierarchy = 'fecha'


@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'grupo_agenda', 'duracion_min', 'precio', 'orden', 'status')
    search_fields = ('nombre', 'grupo_agenda__nombre')
    list_filter = ('grupo_agenda', 'status')
    filter_horizontal = ('recursos',)


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ('id', 'contacto', 'servicio', 'recurso', 'inicio', 'fin', 'estado', 'origen', 'recordatorio_enviado', 'status')
    list_filter = ('estado', 'origen', 'recurso__grupo_agenda', 'recordatorio_enviado', 'status')
    search_fields = ('contacto__contacto_nombre', 'contacto__contacto_numero', 'servicio__nombre', 'recurso__nombre')
    date_hierarchy = 'inicio'
    raw_id_fields = ('contacto', 'conversacion', 'turno_anterior')
