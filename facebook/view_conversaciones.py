"""Conversaciones de Facebook Messenger: misma lógica de inbox que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotada al canal.
El branding por canal lo resuelve `BRANDING_INBOX_CANAL` en la vista compartida.
Finalizadas y pendientes de reconexión reutilizan las vistas compartidas de
`whatsapp/` con `canal_fijo='messenger'` para que las pestañas del inbox no
saquen al usuario del canal."""
from whatsapp.view_conversaciones import conversacionesView
from whatsapp.view_conversaciones_finalizadas import conversacionesFinalizadasView
from whatsapp.view_conversaciones_pendiente_reconexion import conversacionesPendienteReconexionView


def conversacionesFacebookView(request):
    return conversacionesView(request, canal_fijo='messenger')


def conversacionesFinalizadasFacebookView(request):
    return conversacionesFinalizadasView(request, canal_fijo='messenger')


def conversacionesPendienteReconexionFacebookView(request):
    return conversacionesPendienteReconexionView(request, canal_fijo='messenger')
