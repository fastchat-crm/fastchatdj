from django.contrib import admin

from .models import LlamadaVoz, MensajeVoz


@admin.register(LlamadaVoz)
class LlamadaVozAdmin(admin.ModelAdmin):
    list_display = ('id', 'proveedor', 'numero_origen', 'numero_destino', 'estado', 'fecha_inicio', 'duracion_segundos')
    list_filter = ('proveedor', 'estado')
    search_fields = ('numero_origen', 'numero_destino', 'stream_sid', 'call_sid')
    readonly_fields = ('fecha_inicio', 'fecha_fin')


@admin.register(MensajeVoz)
class MensajeVozAdmin(admin.ModelAdmin):
    list_display = ('id', 'llamada', 'rol', 'texto', 'latencia_ms', 'fecha')
    list_filter = ('rol',)
    search_fields = ('texto',)
