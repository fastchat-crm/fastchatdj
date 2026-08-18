from django.contrib import admin

from crm.models import (
    DepartamentoChatBot,
    OpcionDepartamentoChatBot,
    CredencialApiChatbot,
    EndpointApiChatbot,
    ConexionNodoChatbot,
    EstadoFlujoChatbot,
)


class OpcionInline(admin.TabularInline):
    model = OpcionDepartamentoChatBot
    extra = 0
    fields = ('orden', 'nombre', 'tipo_nodo', 'es_inicio', 'opcion_padre', 'status')
    show_change_link = True


@admin.register(DepartamentoChatBot)
class DepartamentoChatBotAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'es_default', 'activo_tradicional', 'status')
    list_filter = ('es_default', 'activo_tradicional', 'status')
    search_fields = ('nombre',)
    inlines = [OpcionInline]


class ConexionSalienteInline(admin.TabularInline):
    model = ConexionNodoChatbot
    fk_name = 'nodo_origen'
    extra = 0
    fields = ('etiqueta', 'orden', 'nodo_destino', 'descripcion', 'status')
    autocomplete_fields = ('nodo_destino',)


@admin.register(OpcionDepartamentoChatBot)
class OpcionDepartamentoChatBotAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'departamento', 'tipo_nodo', 'es_inicio', 'orden', 'status')
    list_filter = ('departamento', 'tipo_nodo', 'es_inicio', 'status')
    search_fields = ('nombre', 'respuesta')
    autocomplete_fields = ('departamento', 'opcion_padre', 'endpoint')
    inlines = [ConexionSalienteInline]
    fieldsets = (
        (None, {'fields': ('departamento', 'nombre', 'orden', 'es_inicio', 'status')}),
        ('Tipo y configuración', {'fields': ('tipo_nodo', 'respuesta', 'config')}),
        ('API (sólo tipo HTTP)', {'fields': ('endpoint',), 'classes': ('collapse',)}),
        ('Captura y validación', {
            'fields': ('variable_destino', 'validacion_tipo', 'validacion_expresion',
                       'mensaje_error', 'reintentos_max'),
            'classes': ('collapse',),
        }),
        ('Legacy / editor visual', {
            'fields': ('opcion_padre', 'posicion_x', 'posicion_y'),
            'classes': ('collapse',),
        }),
    )


@admin.register(CredencialApiChatbot)
class CredencialApiChatbotAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'status')
    list_filter = ('tipo', 'status')
    search_fields = ('nombre',)


@admin.register(EndpointApiChatbot)
class EndpointApiChatbotAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'base_url', 'credencial', 'timeout_seg', 'status')
    list_filter = ('credencial', 'status')
    search_fields = ('nombre', 'base_url')
    autocomplete_fields = ('credencial',)


@admin.register(ConexionNodoChatbot)
class ConexionNodoChatbotAdmin(admin.ModelAdmin):
    list_display = ('nodo_origen', 'etiqueta', 'nodo_destino', 'orden', 'status')
    list_filter = ('etiqueta', 'status')
    autocomplete_fields = ('nodo_origen', 'nodo_destino')


@admin.register(EstadoFlujoChatbot)
class EstadoFlujoChatbotAdmin(admin.ModelAdmin):
    list_display = ('conversacion', 'departamento', 'nodo_actual', 'intentos', 'finalizado', 'actualizado')
    list_filter = ('finalizado', 'departamento')
    readonly_fields = ('actualizado',)
    autocomplete_fields = ('departamento', 'nodo_actual')
    raw_id_fields = ('conversacion',)
