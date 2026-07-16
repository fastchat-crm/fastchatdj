from django.urls import re_path

from .view_centro import centroInstagramView
from .view_comentarios import comentariosInstagramView
from .view_reglas import reglasComentariosInstagramView
from .view_conversaciones import (
    conversacionesInstagramView,
    conversacionesFinalizadasInstagramView,
    conversacionesPendienteReconexionInstagramView,
)
from .view_cuentas import cuentasView
from .view_monitoreo import monitoreoInstagramView
from .view_posts import publicacionesView
from .webhook_view import instagram_webhook

instagram_urls = (
    {
        "nombre": "Centro Instagram",
        "url": 'centro/',
        "vista": centroInstagramView,
    },
    {
        "nombre": "Sesiones Instagram",
        "url": 'sesiones/',
        "vista": cuentasView,
    },
    {
        "nombre": "Conversaciones Instagram",
        "url": 'conversaciones/',
        "vista": conversacionesInstagramView,
    },
    {
        "nombre": "Conversaciones finalizadas Instagram",
        "url": 'conversaciones-finalizadas/',
        "vista": conversacionesFinalizadasInstagramView,
    },
    {
        "nombre": "Conversaciones pendiente reconexión Instagram",
        "url": 'conversaciones-pendiente-reconexion/',
        "vista": conversacionesPendienteReconexionInstagramView,
    },
    {
        "nombre": "Comentarios Instagram",
        "url": 'comentarios/',
        "vista": comentariosInstagramView,
    },
    {
        "nombre": "Reglas de comentarios Instagram",
        "url": 'reglas-comentarios/',
        "vista": reglasComentariosInstagramView,
    },
    {
        "nombre": "Publicaciones Instagram",
        "url": 'publicaciones/',
        "vista": publicacionesView,
    },
    {
        "nombre": "Monitoreo Instagram",
        "url": 'monitoreo/',
        "vista": monitoreoInstagramView,
    },
)

urlpatterns = [
    re_path(r'^webhook/$', instagram_webhook, name='instagram_webhook'),
]
for u in instagram_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
