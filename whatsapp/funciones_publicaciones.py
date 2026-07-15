"""Helpers de la grilla de publicaciones sociales (`view_publicaciones_social`)."""
from .models import ComentarioSocial


def anotar_comentarios_crm(publicaciones, cuenta):
    """Cruza las publicaciones en vivo con los comentarios guardados en el CRM:
    agrega a cada post `comentarios_crm`, `comentarios_nuevos` y `caption_corto`."""
    media_ids = [p.get('id') for p in publicaciones if p.get('id')]
    comentarios = ComentarioSocial.objects.filter(
        status=True, sesion=cuenta, media_id__in=media_ids
    )
    recibidos = {}
    nuevos = {}
    for c in comentarios:
        recibidos[c.media_id] = recibidos.get(c.media_id, 0) + 1
        if c.estado == 'nuevo':
            nuevos[c.media_id] = nuevos.get(c.media_id, 0) + 1
    for p in publicaciones:
        p['comentarios_crm'] = recibidos.get(p.get('id'), 0)
        p['comentarios_nuevos'] = nuevos.get(p.get('id'), 0)
        p['caption_corto'] = (p.get('caption') or '')[:120]
