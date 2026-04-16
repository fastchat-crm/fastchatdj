from django.urls import re_path, path

from .conversaciones_finalizadas_view import conversacionesFinalizadasView
from .sesiones_view import sesionesView
from .conversaciones_view import conversacionesView
from .sync_contacts import sync_contacts_view
from .update_profile_view import update_profile_view
from .view_contacto import contactoView
from .trazas_view import trazasView
from .view_webhook_handler import webhook_handler
from .webhook_batch_view import webhook_handler_batch
from .heartbeat_view import heartbeat_receiver
from .trace_receiver_view import trace_receiver

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
)

urlpatterns = [
    path('webhook_handler/', webhook_handler, name='whatsapp_webhook_handler'),
    path('webhook_handler/batch/', webhook_handler_batch, name='whatsapp_webhook_handler_batch'),
    path('heartbeat/', heartbeat_receiver, name='whatsapp_heartbeat'),
    path('trace/', trace_receiver, name='whatsapp_trace_receiver'),
    path('sync-contacts/', sync_contacts_view, name='sync_contacts'),
    path('whatsapp/update-profile/', update_profile_view, name='update_profile'),
]

for u in whatsapp_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
