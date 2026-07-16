"""Conversaciones de Instagram: misma lógica de inbox que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotada al canal.
El branding por canal lo resuelve `BRANDING_INBOX_CANAL` en la vista compartida.
Finalizadas y pendientes de reconexión reutilizan las vistas compartidas de
`whatsapp/` con `canal_fijo='instagram'` para que las pestañas del inbox no
saquen al usuario del canal."""
from whatsapp.view_conversaciones import conversacionesView
from whatsapp.view_conversaciones_finalizadas import conversacionesFinalizadasView
from whatsapp.view_conversaciones_pendiente_reconexion import conversacionesPendienteReconexionView


def conversacionesInstagramView(request):
    return conversacionesView(request, canal_fijo='instagram')


def conversacionesFinalizadasInstagramView(request):
    return conversacionesFinalizadasView(request, canal_fijo='instagram')


def conversacionesPendienteReconexionInstagramView(request):
    return conversacionesPendienteReconexionView(request, canal_fijo='instagram')
