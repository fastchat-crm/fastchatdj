from django.urls import path, re_path

from . import api_captura_local
from .view_actividad_economica import actividadEconomicaView
from .view_agente_wizard import agente_wizard_view
from .view_chat_agente import chat_agente_view
from .view_cliente import clienteView
from .view_endpoint_api import endpoint_api_view
from .view_industria import industriaView
from .view_mientrenamiento import entrenamiento_ia_view
from .view_departamento_chatbot import departamentoChatbotsView
from .view_perfilempresa import perfil_empresa
from .view_prueba_chatbot import probar_chatbot_view

crm_urls = (
    {
        "nombre": "Mensajeria Instantanea",
        "url": 'departamentos_chatbots/',
        "vista": departamentoChatbotsView,
    },
    {
        "nombre": "Clientes",
        "url": 'cliente/',
        "vista": clienteView,
    },
    {
        "nombre": "Endpoints API",
        "url": 'endpoints_api/',
        "vista": endpoint_api_view,
    },
    {
        "nombre": "Crear Agente Rápido",
        "url": 'entrenamiento/wizard/',
        "vista": agente_wizard_view,
    },
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
)

urlpatterns = []

for u in crm_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))

# Chat de prueba para un agente IA (ID encriptado en la URL)
urlpatterns.append(
    path('entrenamiento/chat/<str:agente_enc_id>/', chat_agente_view, name='chat_agente')
)

# Chat de prueba (dry-run) del flujo tradicional de una sesión WhatsApp
urlpatterns.append(
    path('departamentos_chatbots/prueba/<str:sesion_enc_id>/',
         probar_chatbot_view, name='probar_chatbot')
)

# Endpoint stub para tools de captura del agente IA (ver migrar_nodos_a_tools).
# El LLM hace POST acá con el dato capturado y este endpoint le hace echo
# para cerrar el ciclo de function-calling.
urlpatterns.append(
    path('api/captura_local/', api_captura_local.captura_local,
         name='crm_api_captura_local')
)