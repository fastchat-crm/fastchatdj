"""Conversaciones de Instagram: mismo inbox/chat que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotado al canal."""
from whatsapp.view_conversaciones import conversacionesView


def conversacionesInstagramView(request):
    return conversacionesView(request, canal_fijo='instagram')
