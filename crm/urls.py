from django.urls import path, re_path

from .view_actividad_economica import actividadEconomicaView
from .view_chat_agente import chat_agente_view
from .view_industria import industriaView
from .view_mientrenamiento import entrenamiento_ia_view
from .view_departamento_chatbot import departamentoChatbotsView
from .view_perfilempresa import perfil_empresa

crm_urls = (
    {
        "nombre": "Entrenamiento IA",
        "url": 'entrenamiento/',
        "vista": entrenamiento_ia_view,
    },
    {
        "nombre": "Perfil Empresa",
        "url": 'perfil_empresa/',
        "vista": perfil_empresa,
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

urlpatterns = []

for u in crm_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))

# Chat de prueba para un agente IA (ID encriptado en la URL)
urlpatterns.append(
    path('entrenamiento/chat/<str:agente_enc_id>/', chat_agente_view, name='chat_agente')
)