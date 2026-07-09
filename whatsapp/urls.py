from django.urls import re_path, path

from .view_conversaciones_finalizadas import conversacionesFinalizadasView
from .view_conversaciones_pendiente_reconexion import conversacionesPendienteReconexionView
from .view_sesiones import sesionesView, mensajes_rapidos_view
from .view_sesion_activa import set_sesion_activa
from .meta_oauth_view import meta_oauth_start, meta_oauth_callback
from .meta_manual_view import (
    meta_manual_validar, meta_manual_conectar, meta_test_message, meta_registrar_numero,
    meta_request_code, meta_verify_code,
)
from .meta_diagnostico_view import (
    meta_diagnostico, meta_suscribir_waba_action, meta_configurar_webhook_action,
    meta_corregir_waba_action, meta_validar_conexion_action, meta_cambiar_nombre_action,
)
from .meta_webhook_log_view import meta_webhook_log, meta_webhook_log_poll, meta_webhook_log_detalle
from .meta_webhook_hits_view import meta_webhook_hits, meta_webhook_hits_poll, meta_webhook_hit_detalle
from .meta_foto_perfil_view import meta_actualizar_foto_perfil
from .view_conversaciones import conversacionesView
from .sync_contacts import sync_contacts_view
from .update_profile_view import update_profile_view
from .view_contacto import contactoView
from .view_trazas import trazasView
from .webhook_baileys_view import webhook_handler
from .webhook_batch_view import webhook_handler_batch
from .heartbeat_view import heartbeat_receiver
from .trace_receiver_view import trace_receiver
from .meta_webhook_view import meta_webhook
from .meta_social_webhook_view import instagram_webhook, messenger_webhook
from .tiktok_webhook_view import tiktok_webhook
from .view_plantillas import plantillasView
from .view_tarifas import tarifasView
from .view_etiquetas import etiquetasView
from .view_pipeline import pipelineView
from .view_campanas import campanasView
from .view_horarios import horariosView
from .view_analytics import analyticsView
from .view_supervision import supervisionView
from . import api_rest

whatsapp_urls = (
    {
        "nombre": "Sesiones",
        "url": 'sesiones/',
        "vista": sesionesView,
    },
    {
        "nombre": "Conversaciones",
        "url": 'conversaciones/',
        "vista": conversacionesView,
    },
    {
        "nombre": "Conversaciones finalizadas",
        "url": 'conversaciones-finalizadas/',
        "vista": conversacionesFinalizadasView,
    },
    {
        "nombre": "Conversaciones pendiente reconexión",
        "url": 'conversaciones-pendiente-reconexion/',
        "vista": conversacionesPendienteReconexionView,
    },
    {
        "nombre": "Contactos",
        "url": 'contacto/',
        "vista": contactoView,
    },
    {
        "nombre": "Trazas / Logs (IA y conversaciones)",
        "url": 'trazas/',
        "vista": trazasView,
    },
    {
        "nombre": "Plantillas WhatsApp",
        "url": 'plantillas/',
        "vista": plantillasView,
    },
    {
        "nombre": "Tarifas Meta",
        "url": 'tarifas/',
        "vista": tarifasView,
    },
    {
        "nombre": "Etiquetas",
        "url": 'etiquetas/',
        "vista": etiquetasView,
    },
    {
        "nombre": "Pipeline de ventas",
        "url": 'pipeline/',
        "vista": pipelineView,
    },
    {
        "nombre": "Campañas",
        "url": 'campanas/',
        "vista": campanasView,
    },
    {
        "nombre": "Horarios de atención",
        "url": 'horarios/',
        "vista": horariosView,
    },
    {
        "nombre": "Analytics",
        "url": 'analytics/',
        "vista": analyticsView,
    },
    {
        "nombre": "Supervision",
        "url": 'supervision/',
        "vista": supervisionView,
    },
)

urlpatterns = [
    path('webhook_handler/', webhook_handler, name='whatsapp_webhook_handler'),
    path('webhook_handler/batch/', webhook_handler_batch, name='whatsapp_webhook_handler_batch'),
    path('heartbeat/', heartbeat_receiver, name='whatsapp_heartbeat'),
    path('trace/', trace_receiver, name='whatsapp_trace_receiver'),
    path('meta_webhook/', meta_webhook, name='whatsapp_meta_webhook'),
    path('meta/oauth/start/', meta_oauth_start, name='whatsapp_meta_oauth_start'),
    path('meta/oauth/callback/', meta_oauth_callback, name='whatsapp_meta_oauth_callback'),
    path('meta/manual/validar/', meta_manual_validar, name='whatsapp_meta_manual_validar'),
    path('meta/manual/conectar/', meta_manual_conectar, name='whatsapp_meta_manual_conectar'),
    path('meta/test-message/<int:sesion_id>/', meta_test_message, name='whatsapp_meta_test_message'),
    path('sesiones/<int:sesion_id>/mensajes-rapidos/', mensajes_rapidos_view, name='whatsapp_mensajes_rapidos'),
    path('sesiones/<int:sesion_id>/registrar-numero/', meta_registrar_numero, name='whatsapp_meta_registrar_numero'),
    path('sesiones/<int:sesion_id>/request-code/', meta_request_code, name='whatsapp_meta_request_code'),
    path('sesiones/<int:sesion_id>/verify-code/', meta_verify_code, name='whatsapp_meta_verify_code'),
    path('sesiones/<int:sesion_id>/diagnostico/', meta_diagnostico, name='whatsapp_meta_diagnostico'),
    path('sesiones/<int:sesion_id>/suscribir-waba/', meta_suscribir_waba_action, name='whatsapp_meta_suscribir_waba'),
    path('sesiones/<int:sesion_id>/corregir-waba/', meta_corregir_waba_action, name='whatsapp_meta_corregir_waba'),
    path('sesiones/<int:sesion_id>/validar-conexion/', meta_validar_conexion_action, name='whatsapp_meta_validar_conexion'),
    path('sesiones/<int:sesion_id>/cambiar-nombre/', meta_cambiar_nombre_action, name='whatsapp_meta_cambiar_nombre'),
    path('sesiones/<int:sesion_id>/configurar-webhook/', meta_configurar_webhook_action, name='whatsapp_meta_configurar_webhook'),
    path('sesiones/<int:sesion_id>/webhook-log/', meta_webhook_log, name='whatsapp_meta_webhook_log'),
    path('sesiones/<int:sesion_id>/webhook-log/poll/', meta_webhook_log_poll, name='whatsapp_meta_webhook_log_poll'),
    path('sesiones/<int:sesion_id>/webhook-log/<int:evento_id>/', meta_webhook_log_detalle, name='whatsapp_meta_webhook_log_detalle'),
    path('meta/webhook-hits/', meta_webhook_hits, name='whatsapp_meta_webhook_hits'),
    path('meta/webhook-hits/poll/', meta_webhook_hits_poll, name='whatsapp_meta_webhook_hits_poll'),
    path('meta/webhook-hits/<int:hit_id>/', meta_webhook_hit_detalle, name='whatsapp_meta_webhook_hit_detalle'),
    path('sesiones/<int:sesion_id>/profile-picture/', meta_actualizar_foto_perfil, name='whatsapp_meta_foto_perfil'),
    path('instagram_webhook/', instagram_webhook, name='whatsapp_instagram_webhook'),
    path('messenger_webhook/', messenger_webhook, name='whatsapp_messenger_webhook'),
    path('tiktok_webhook/', tiktok_webhook, name='whatsapp_tiktok_webhook'),
    path('sesion-activa/', set_sesion_activa, name='whatsapp_set_sesion_activa'),
    path('sync-contacts/', sync_contacts_view, name='sync_contacts'),
    path('whatsapp/update-profile/', update_profile_view, name='update_profile'),

    # -------------------------------------------------------------------------
    # REST API v1 (X-API-Key header required)
    # -------------------------------------------------------------------------
    path('api/v1/contactos/',                      api_rest.contactos,              name='api_v1_contactos'),
    path('api/v1/contactos/<int:pk>/',             api_rest.contacto_detalle,       name='api_v1_contacto_detalle'),
    path('api/v1/conversaciones/',                 api_rest.conversaciones,         name='api_v1_conversaciones'),
    path('api/v1/conversaciones/<int:pk>/mensajes/', api_rest.conversacion_mensajes, name='api_v1_conv_mensajes'),
    path('api/v1/conversaciones/<int:pk>/asignar/',  api_rest.conversacion_asignar,  name='api_v1_conv_asignar'),
    path('api/v1/conversaciones/<int:pk>/etapa/',    api_rest.conversacion_etapa,    name='api_v1_conv_etapa'),
    path('api/v1/conversaciones/<int:pk>/enviar/',   api_rest.conversacion_enviar,   name='api_v1_conv_enviar'),
    path('api/v1/mensajes/enviar/',                api_rest.enviar_mensaje,         name='api_v1_enviar_mensaje'),
    path('api/v1/etiquetas/aplicar/',              api_rest.etiquetas_aplicar,      name='api_v1_etiquetas_aplicar'),
    path('api/v1/capi/evento/',                    api_rest.capi_evento,            name='api_v1_capi_evento'),
    path('api/v1/campanas/<int:pk>/stats/',        api_rest.campana_stats,          name='api_v1_campana_stats'),
]

for u in whatsapp_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
