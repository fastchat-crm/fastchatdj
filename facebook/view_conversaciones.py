"""Conversaciones de Facebook Messenger: misma lógica de inbox que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotada al canal.
El branding por canal lo resuelve `BRANDING_INBOX_CANAL` en la vista compartida."""
from whatsapp.view_conversaciones import conversacionesView


def conversacionesFacebookView(request):
    return conversacionesView(request, canal_fijo='messenger')
