from django.urls import re_path, path
from .sesiones_view import sesionesView
from .conversaciones_view import conversacionesView
from .sync_contacts import sync_contacts_view
from .update_profile_view import update_profile_view
from .view_contacto import contactoView
from .view_webhook_handler import webhook_handler

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
        "nombre": "Contactos",
        "url": 'contacto/',
        "vista": contactoView,
    },
)

urlpatterns = [
    path('webhook_handler/', webhook_handler, name='whatsapp_webhook_handler'),
    path('sync-contacts/', sync_contacts_view, name='sync_contacts'),
    path('whatsapp/update-profile/', update_profile_view, name='update_profile'),
]

for u in whatsapp_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
