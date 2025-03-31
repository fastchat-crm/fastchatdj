from django.urls import re_path, path
from .sesiones_view import sesionesView
from .conversaciones_view import conversacionesView
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
)

urlpatterns = [
    path('webhook_handler/', webhook_handler, name='whatsapp_webhook_handler')
]

for u in whatsapp_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
