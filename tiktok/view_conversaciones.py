"""Conversaciones de TikTok: misma lógica de inbox que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotada al canal.
El branding por canal lo resuelve `BRANDING_INBOX_CANAL` en la vista compartida.
Se verá vacío hasta que TikTok apruebe la Business Messaging API."""
from whatsapp.view_conversaciones import conversacionesView


def conversacionesTikTokView(request):
    return conversacionesView(request, canal_fijo='tiktok')
