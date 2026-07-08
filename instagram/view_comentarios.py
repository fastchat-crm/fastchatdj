"""Comentarios de Instagram: reusa el inbox compartido fijando el canal."""
from whatsapp.view_comentarios import comentariosView


def comentariosInstagramView(request):
    return comentariosView(request, canal_fijo='instagram')
