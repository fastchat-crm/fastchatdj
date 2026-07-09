"""Conversaciones de Instagram: misma lógica de inbox que WhatsApp
(`whatsapp.view_conversaciones.conversacionesView`) acotada al canal,
con template propio `instagram/conversaciones/listado.html`."""
from whatsapp.view_conversaciones import conversacionesView


def conversacionesInstagramView(request):
    return conversacionesView(
        request,
        canal_fijo='instagram',
        template='instagram/conversaciones/listado.html',
    )
