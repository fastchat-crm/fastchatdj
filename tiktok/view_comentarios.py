"""Comentarios de TikTok: reusa el inbox compartido fijando el canal."""
from whatsapp.view_comentarios import comentariosView


def comentariosTikTokView(request):
    return comentariosView(request, canal_fijo='tiktok')
