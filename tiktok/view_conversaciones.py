"""Conversaciones de TikTok: mismo inbox/chat que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotado al canal.
Se verá vacío hasta que TikTok apruebe la Business Messaging API."""
from whatsapp.view_conversaciones import conversacionesView


def conversacionesTikTokView(request):
    return conversacionesView(request, canal_fijo='tiktok')
