"""Publicaciones de Facebook — wrapper de la vista genérica por canal
(`whatsapp.view_publicaciones_social.publicacionesSocialView`)."""
from whatsapp.view_publicaciones_social import publicacionesSocialView


def publicacionesView(request):
    return publicacionesSocialView(request, canal='facebook')
