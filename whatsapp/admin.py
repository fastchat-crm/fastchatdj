"""Admin Django para los modelos Meta. Pensado para debug — los flujos de
usuario final (configurar credenciales, plantillas, etc.) viven en el
dashboard, no en /admin/.
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    SesionWhatsApp,
    ConfigMeta,
    PlantillaWhatsApp,
    EventoMetaRecibido,
    EtiquetaContacto,
    PipelineVenta,
    EtapaPipeline,
    ConversacionEnPipeline,
    HistorialEtapaPipeline,
    HorarioAtencion,
    ExcepcionHorario,
    Campana,
    EnvioCampana,
    PixelMeta,
    EventoCAPI,
    ConfigInstagram,
    ConfigMessenger,
    DisponibilidadAgente,
    AsignacionAutomatica,
    WebhookSaliente,
    EntregaWebhookSaliente,
)


@admin.register(SesionWhatsApp)
class SesionWhatsAppAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'numero', 'proveedor', 'estado', 'usuario', 'fecha_modificacion')
    list_filter = ('proveedor', 'estado', 'modo_bot')
    search_fields = ('id', 'nombre', 'numero', 'session_id', 'whatsapp_id')
    readonly_fields = ('session_id', 'fecha_registro', 'fecha_modificacion', 'ultima_conexion')
    raw_id_fields = ('usuario', 'agente_ia', 'departamento_default')


@admin.register(ConfigMeta)
class ConfigMetaAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'sesion', 'phone_number_id', 'display_phone_number',
        'quality_rating', 'messaging_limit_tier', 'webhook_verificado',
        'ultima_sincronizacion',
    )
    list_filter = ('quality_rating', 'messaging_limit_tier')
    search_fields = ('waba_id', 'phone_number_id', 'display_phone_number', 'sesion__nombre', 'sesion__numero')
    readonly_fields = ('webhook_verificado_en', 'ultima_sincronizacion', 'fecha_registro', 'fecha_modificacion')
    raw_id_fields = ('sesion',)
    fieldsets = (
        ('Identificadores Meta', {
            'fields': ('sesion', 'waba_id', 'phone_number_id', 'business_account_id', 'display_phone_number')
        }),
        ('Credenciales', {
            'fields': ('access_token', 'app_id', 'app_secret'),
            'classes': ('collapse',),
        }),
        ('Webhook', {
            'fields': ('webhook_verify_token', 'webhook_verificado_en'),
        }),
        ('Estado Meta', {
            'fields': ('quality_rating', 'messaging_limit_tier', 'business_verification_status', 'ultima_sincronizacion'),
        }),
    )

    def webhook_verificado(self, obj):
        if obj.webhook_verificado_en:
            return format_html('<span style="color:green">SI</span>')
        return format_html('<span style="color:red">NO</span>')
    webhook_verificado.short_description = 'Webhook OK'


@admin.register(PlantillaWhatsApp)
class PlantillaWhatsAppAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'idioma', 'categoria', 'estado_meta', 'config_meta', 'veces_enviada', 'ultima_sincronizacion')
    list_filter = ('estado_meta', 'categoria', 'idioma', 'header_tipo')
    search_fields = ('nombre', 'cuerpo', 'id_meta', 'config_meta__waba_id')
    readonly_fields = ('id_meta', 'fecha_aprobacion', 'ultima_sincronizacion', 'veces_enviada', 'ultimo_envio', 'fecha_registro', 'fecha_modificacion')
    raw_id_fields = ('config_meta',)


@admin.register(EventoMetaRecibido)
class EventoMetaRecibidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'recibido_en', 'tipo_evento', 'config_meta', 'firma_valida', 'procesado', 'tiene_error')
    list_filter = ('tipo_evento', 'firma_valida', 'procesado')
    search_fields = ('tipo_evento', 'config_meta__waba_id', 'config_meta__phone_number_id', 'error_procesamiento')
    readonly_fields = ('config_meta', 'tipo_evento', 'payload_json', 'firma_valida', 'procesado', 'error_procesamiento', 'recibido_en', 'fecha_registro', 'fecha_modificacion')
    date_hierarchy = 'recibido_en'

    def has_add_permission(self, request):
        return False

    def tiene_error(self, obj):
        return bool(obj.error_procesamiento)
    tiene_error.boolean = True
    tiene_error.short_description = 'Error'


# ----------------------------------------------------------------------------
# CRM features
# ----------------------------------------------------------------------------

@admin.register(EtiquetaContacto)
class EtiquetaContactoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'color', 'descripcion', 'usuario_creacion')
    search_fields = ('nombre', 'descripcion')


class EtapaPipelineInline(admin.TabularInline):
    model = EtapaPipeline
    extra = 0
    fields = ('orden', 'nombre', 'color', 'probabilidad_cierre', 'es_ganado', 'es_perdido')


@admin.register(PipelineVenta)
class PipelineVentaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'es_default', 'descripcion')
    search_fields = ('nombre',)
    inlines = [EtapaPipelineInline]


@admin.register(EtapaPipeline)
class EtapaPipelineAdmin(admin.ModelAdmin):
    list_display = ('id', 'pipeline', 'orden', 'nombre', 'probabilidad_cierre', 'es_ganado', 'es_perdido')
    list_filter = ('pipeline', 'es_ganado', 'es_perdido')
    search_fields = ('nombre', 'pipeline__nombre')


@admin.register(ConversacionEnPipeline)
class ConversacionEnPipelineAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversacion', 'etapa', 'valor_estimado', 'moneda', 'fecha_cambio_etapa')
    list_filter = ('etapa__pipeline', 'etapa')
    raw_id_fields = ('conversacion', 'etapa')


@admin.register(HistorialEtapaPipeline)
class HistorialEtapaPipelineAdmin(admin.ModelAdmin):
    list_display = ('id', 'card', 'etapa_anterior', 'etapa_nueva', 'usuario', 'fecha')
    list_filter = ('etapa_nueva',)
    raw_id_fields = ('card', 'etapa_anterior', 'etapa_nueva', 'usuario')


@admin.register(HorarioAtencion)
class HorarioAtencionAdmin(admin.ModelAdmin):
    list_display = ('id', 'sesion', 'dia_semana', 'hora_inicio', 'hora_fin', 'activo')
    list_filter = ('dia_semana', 'activo', 'sesion')
    raw_id_fields = ('sesion',)


@admin.register(ExcepcionHorario)
class ExcepcionHorarioAdmin(admin.ModelAdmin):
    list_display = ('id', 'sesion', 'fecha', 'abierto', 'motivo')
    list_filter = ('abierto', 'sesion')
    date_hierarchy = 'fecha'
    raw_id_fields = ('sesion',)


class EnvioCampanaInline(admin.TabularInline):
    model = EnvioCampana
    extra = 0
    fields = ('contacto', 'estado', 'fecha_envio', 'respondio', 'error')
    readonly_fields = ('contacto', 'estado', 'fecha_envio', 'respondio', 'error')
    can_delete = False


@admin.register(Campana)
class CampanaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'sesion', 'tipo', 'estado', 'programada_para',
                    'total_objetivo', 'total_enviados', 'total_fallidos')
    list_filter = ('estado', 'tipo', 'sesion')
    search_fields = ('nombre', 'descripcion')
    raw_id_fields = ('sesion', 'plantilla')
    filter_horizontal = ('etiquetas_incluir', 'etiquetas_excluir')
    readonly_fields = ('fecha_inicio_real', 'fecha_fin_real', 'total_enviados',
                       'total_fallidos', 'total_respondidos', 'error_detalle')


@admin.register(EnvioCampana)
class EnvioCampanaAdmin(admin.ModelAdmin):
    list_display = ('id', 'campana', 'contacto', 'estado', 'fecha_envio', 'respondio', 'intentos')
    list_filter = ('estado', 'respondio')
    search_fields = ('campana__nombre', 'contacto__contacto_numero')
    raw_id_fields = ('campana', 'contacto')


@admin.register(PixelMeta)
class PixelMetaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'pixel_id', 'sesion', 'activo', 'test_event_code')
    list_filter = ('activo',)
    raw_id_fields = ('sesion',)


@admin.register(EventoCAPI)
class EventoCAPIAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_name', 'pixel', 'conversacion', 'event_time',
                    'valor', 'moneda', 'exitoso', 'response_status')
    list_filter = ('event_name', 'exitoso', 'pixel')
    date_hierarchy = 'event_time'
    raw_id_fields = ('pixel', 'conversacion')
    readonly_fields = ('payload_json', 'response_body', 'response_status')


@admin.register(ConfigInstagram)
class ConfigInstagramAdmin(admin.ModelAdmin):
    list_display = ('id', 'sesion', 'username', 'ig_user_id', 'page_id', 'webhook_verificado_en')
    search_fields = ('username', 'ig_user_id', 'page_id')
    raw_id_fields = ('sesion',)


@admin.register(ConfigMessenger)
class ConfigMessengerAdmin(admin.ModelAdmin):
    list_display = ('id', 'sesion', 'page_name', 'page_id', 'webhook_verificado_en')
    search_fields = ('page_name', 'page_id')
    raw_id_fields = ('sesion',)


@admin.register(DisponibilidadAgente)
class DisponibilidadAgenteAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario', 'disponible', 'max_conversaciones', 'ultimo_asignado_en')
    list_filter = ('disponible',)
    raw_id_fields = ('usuario',)
    filter_horizontal = ('sesiones', 'departamentos')


@admin.register(AsignacionAutomatica)
class AsignacionAutomaticaAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversacion', 'agente', 'estrategia', 'fecha')
    list_filter = ('estrategia',)
    raw_id_fields = ('conversacion', 'agente')
    date_hierarchy = 'fecha'


@admin.register(WebhookSaliente)
class WebhookSalienteAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'url', 'activo', 'fallos_consecutivos', 'ultima_entrega')
    list_filter = ('activo',)
    search_fields = ('nombre', 'url')


@admin.register(EntregaWebhookSaliente)
class EntregaWebhookSalienteAdmin(admin.ModelAdmin):
    list_display = ('id', 'webhook', 'evento', 'status_code', 'exitoso', 'fecha', 'latencia_ms')
    list_filter = ('exitoso', 'evento')
    date_hierarchy = 'fecha'
    raw_id_fields = ('webhook',)
    readonly_fields = ('payload', 'respuesta')
