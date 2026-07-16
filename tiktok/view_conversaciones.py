"""Conversaciones de TikTok: misma lógica de inbox que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotada al canal.
El branding por canal lo resuelve `BRANDING_INBOX_CANAL` en la vista compartida.
Se verá vacío hasta que TikTok apruebe la Business Messaging API.
Finalizadas y pendientes de reconexión reutilizan las vistas compartidas de
`whatsapp/` con `canal_fijo='tiktok'` para que las pestañas del inbox no
saquen al usuario del canal."""
from whatsapp.view_conversaciones import conversacionesView
from whatsapp.view_conversaciones_finalizadas import conversacionesFinalizadasView
from whatsapp.view_conversaciones_pendiente_reconexion import conversacionesPendienteReconexionView


def conversacionesTikTokView(request):
    return conversacionesView(request, canal_fijo='tiktok')


def conversacionesFinalizadasTikTokView(request):
    return conversacionesFinalizadasView(request, canal_fijo='tiktok')


def conversacionesPendienteReconexionTikTokView(request):
    return conversacionesPendienteReconexionView(request, canal_fijo='tiktok')
