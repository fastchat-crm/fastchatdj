from django.urls import path, re_path

from .view_actividad_economica import actividadEconomicaView
from .view_industria import industriaView
from .view_mientrenamiento import entrenamiento_ia_view

crm_urls = (
    {
        "nombre": "Entrenaramiento IA",
        "url": 'entrenamiento/',
        "vista": entrenamiento_ia_view,
    },
    {
        "nombre": "Industria",
        "url": 'industria/',
        "vista": industriaView,
    },
    {
        "nombre": "Actividad Economica",
        "url": 'actividad_economica/',
        "vista": actividadEconomicaView,
    },
)

urlpatterns = [
]


for u in crm_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))