"""Comentarios de la página de Facebook: reusa el inbox compartido fijando el canal."""
from whatsapp.view_comentarios import comentariosView


def comentariosFacebookView(request):
    return comentariosView(request, canal_fijo='facebook')
