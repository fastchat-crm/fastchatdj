"""Conversaciones de TikTok: misma lógica de inbox que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotada al canal,
con template propio `tiktok/conversaciones/listado.html`.
Se verá vacío hasta que TikTok apruebe la Business Messaging API."""
from whatsapp.view_conversaciones import conversacionesView


def conversacionesTikTokView(request):
    return conversacionesView(
        request,
        canal_fijo='tiktok',
        template='tiktok/conversaciones/listado.html',
    )
