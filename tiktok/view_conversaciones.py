"""Conversaciones de TikTok: misma lógica de inbox que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotada al canal.
El branding por canal lo resuelve `BRANDING_INBOX_CANAL` en la vista compartida.
Se verá vacío hasta que TikTok apruebe la Business Messaging API.
Finalizadas reutiliza la vista compartida de `whatsapp/` con
`canal_fijo='tiktok'`. TikTok no tiene pestaña Pendientes
(`tiene_pendientes=False` en el branding): el asesor finaliza a mano y, si el
cliente vuelve a escribir, se reabre la misma conversación
(`ConversacionWhatsApp.obtener_o_crear_activa`)."""
from whatsapp.view_conversaciones import conversacionesView
from whatsapp.view_conversaciones_finalizadas import conversacionesFinalizadasView


def conversacionesTikTokView(request):
    return conversacionesView(request, canal_fijo='tiktok')


def conversacionesFinalizadasTikTokView(request):
    return conversacionesFinalizadasView(request, canal_fijo='tiktok')
