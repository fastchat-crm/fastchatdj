from django.urls import path, re_path

from .view_actividad_economica import actividadEconomicaView
from .view_industria import industriaView
from .view_mientrenamiento import entrenamiento_ia_view
from .view_departamento_chatbot import departamentoChatbotsView

crm_urls = (
    {
        "nombre": "Entrenamiento IA",
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
    {
        "nombre": "Departamentos & Chatbots",
        "url": 'departamentos_chatbots/',
        "vista": departamentoChatbotsView,
    },
)

urlpatterns = [
]


for u in crm_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))