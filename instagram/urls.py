from django.urls import re_path

from .view_centro import centroInstagramView
from .view_comentarios import comentariosInstagramView
from .view_reglas import reglasComentariosInstagramView
from .view_conversaciones import conversacionesInstagramView
from .view_cuentas import cuentasView
from .view_posts import publicacionesView

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
)

urlpatterns = []
for u in instagram_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
