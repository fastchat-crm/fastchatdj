from django.urls import path, re_path

from public.view_login import login_tienda
from .views import equipoView, procesoView, ticketView, ticketAdminView

ticket_urls = (
    {
        "nombre": "Equipos",
        "url": 'equipos/',
        "vista": equipoView,
    },
    {
        "nombre": "Procesos",
        "url": 'procesos/',
        "vista": procesoView,
    },
    {
        "nombre": "Tickets",
        "url": 'cliente/',
        "vista": ticketView,
    },
    {
        "nombre": "Tickets",
        "url": 'gestor/',
        "vista": ticketAdminView,
    },
)

urlpatterns = []

for u in ticket_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))