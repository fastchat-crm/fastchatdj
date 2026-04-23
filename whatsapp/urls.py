from django.urls import re_path, path

from .conversaciones_finalizadas_view import conversacionesFinalizadasView
from .sesiones_view import sesionesView
from .docs_view import docs_conectar_whatsapp_business
from .meta_oauth_view import meta_oauth_start, meta_oauth_callback
from .conversaciones_view import conversacionesView
from .sync_contacts import sync_contacts_view
from .update_profile_view import update_profile_view
from .view_contacto import contactoView
from .trazas_view import trazasView
from .view_webhook_handler import webhook_handler
from .webhook_batch_view import webhook_handler_batch
from .heartbeat_view import heartbeat_receiver
from .trace_receiver_view import trace_receiver
from .meta_webhook_view import meta_webhook
from .meta_social_webhook_view import instagram_webhook, messenger_webhook
from .plantillas_view import plantillasView
from .etiquetas_view import etiquetasView
from .pipeline_view import pipelineView
from .campanas_view import campanasView
from .horarios_view import horariosView
from .analytics_view import analyticsView
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
        "nombre": "Contactos",
        "url": 'contacto/',
        "vista": contactoView,
    },
    {
        "nombre": "Trazas IA",
        "url": 'trazas/',
        "vista": trazasView,
    },
    {
        "nombre": "Plantillas WhatsApp",
        "url": 'plantillas/',
        "vista": plantillasView,
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
        "nombre": "Docs — Conectar WhatsApp Business",
        "url": 'docs/conectar-whatsapp-business/',
        "vista": docs_conectar_whatsapp_business,
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
    path('instagram_webhook/', instagram_webhook, name='whatsapp_instagram_webhook'),
    path('messenger_webhook/', messenger_webhook, name='whatsapp_messenger_webhook'),
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
    path('api/v1/mensajes/enviar/',                api_rest.enviar_mensaje,         name='api_v1_enviar_mensaje'),
    path('api/v1/etiquetas/aplicar/',              api_rest.etiquetas_aplicar,      name='api_v1_etiquetas_aplicar'),
    path('api/v1/capi/evento/',                    api_rest.capi_evento,            name='api_v1_capi_evento'),
    path('api/v1/campanas/<int:pk>/stats/',        api_rest.campana_stats,          name='api_v1_campana_stats'),
]

for u in whatsapp_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
