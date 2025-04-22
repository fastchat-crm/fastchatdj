from django.urls import path, re_path

from public.view_login import login_tienda
from .views import equipoView, procesoView, ticketView, ticketAdminView, ticketIntegranteView


ticket_urls = (
    {
        "nombre": "Equipos de Atención",
        "url": 'equipos/',
        "vista": equipoView,
    },
    {
        "nombre": "Procesos de Atención",
        "url": 'procesos/',
        "vista": procesoView,
    },
    {
        "nombre": "Generación de Tickets",
        "url": 'cliente/',
        "vista": ticketView,
    },
    {
        "nombre": "Administración de Tickets",
        "url": 'gestor/',
        "vista": ticketAdminView,
    },
{
        "nombre": "Gestion de Tickets",
        "url": 'mis_tickets/',
        "vista": ticketIntegranteView,
    },
)

urlpatterns = []

for u in ticket_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))