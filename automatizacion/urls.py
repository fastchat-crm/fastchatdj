from django.urls import re_path

from .view_automatizaciones import automatizacionesView

automatizacion_urls = (
    {
        "nombre": "Automatizaciones",
        "url": '',
        "vista": automatizacionesView,
    },
)

urlpatterns = [re_path(r'^$', automatizacionesView)]
