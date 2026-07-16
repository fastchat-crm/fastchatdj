from django.urls import re_path

from .view_centro import centroFacebookView
from .view_comentarios import comentariosFacebookView
from .view_reglas import reglasComentariosFacebookView
from .view_conversaciones import (
    conversacionesFacebookView,
    conversacionesFinalizadasFacebookView,
    conversacionesPendienteReconexionFacebookView,
)
from .view_cuentas import cuentasView
from .view_monitoreo import monitoreoFacebookView
from .view_posts import publicacionesView
from .webhook_view import messenger_webhook

facebook_urls = (
    {
        "nombre": "Centro Facebook",
        "url": 'centro/',
        "vista": centroFacebookView,
    },
    {
        "nombre": "Sesiones Facebook",
        "url": 'sesiones/',
        "vista": cuentasView,
    },
    {
        "nombre": "Conversaciones Facebook",
        "url": 'conversaciones/',
        "vista": conversacionesFacebookView,
    },
    {
        "nombre": "Conversaciones finalizadas Facebook",
        "url": 'conversaciones-finalizadas/',
        "vista": conversacionesFinalizadasFacebookView,
    },
    {
        "nombre": "Conversaciones pendiente reconexión Facebook",
        "url": 'conversaciones-pendiente-reconexion/',
        "vista": conversacionesPendienteReconexionFacebookView,
    },
    {
        "nombre": "Comentarios Facebook",
        "url": 'comentarios/',
        "vista": comentariosFacebookView,
    },
    {
        "nombre": "Reglas de comentarios Facebook",
        "url": 'reglas-comentarios/',
        "vista": reglasComentariosFacebookView,
    },
    {
        "nombre": "Publicaciones Facebook",
        "url": 'publicaciones/',
        "vista": publicacionesView,
    },
    {
        "nombre": "Monitoreo Facebook",
        "url": 'monitoreo/',
        "vista": monitoreoFacebookView,
    },
)

urlpatterns = [
    re_path(r'^webhook/$', messenger_webhook, name='messenger_webhook'),
]
for u in facebook_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
