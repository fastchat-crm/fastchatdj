"""Helpers del inbox de comentarios sociales.

Usados por `view_comentarios.py` (acciones del usuario) y por
`meta_social_webhook_view.py` (ingreso de comentarios vía webhook).
"""
from django.utils import timezone

from meta.instagram import InstagramService

from .models import ComentarioSocial, Contacto


def guardar_comentario_instagram(sesion, config, value):
    """Persiste un comentario entrante del webhook de Instagram.

    `value` es el shape del campo `comments`:
    {id, text, parent_id, from:{id, username}, media:{id, media_product_type}}.
    Ignora ecos (comentarios hechos por la propia cuenta) y duplicados.
    """
    comment_id = value.get('id')
    if not comment_id:
        return None
    autor = value.get('from') or {}
    if str(autor.get('id') or '') == str(getattr(config, 'ig_user_id', '') or ''):
        return None
    if ComentarioSocial.objects.filter(comment_id=str(comment_id)).exists():
        return None
    media = value.get('media') or {}
    return ComentarioSocial.objects.create(
        sesion=sesion,
        canal='instagram',
        comment_id=str(comment_id),
        parent_id=str(value.get('parent_id') or ''),
        media_id=str(media.get('id') or ''),
        autor_external_id=str(autor.get('id') or ''),
        autor_username=autor.get('username') or '',
        texto=value.get('text') or '',
        fecha_comentario=timezone.now(),
        payload_json=value,
    )


def responder_comentario(comentario, texto, usuario):
    """Respuesta pública al comentario vía Graph API y actualiza estado local."""
    service = InstagramService()
    res = service.responder_comentario(
        comentario.sesion.session_id, comentario.comment_id, texto
    )
    if res.get('success'):
        comentario.respuesta_texto = texto
        comentario.estado = 'respondido'
        comentario.respondido_por = usuario
        comentario.respondido_en = timezone.now()
        comentario.save()
    return res


def ocultar_comentario(comentario, ocultar=True):
    """Oculta o vuelve a mostrar el comentario en la publicación."""
    service = InstagramService()
    res = service.ocultar_comentario(
        comentario.sesion.session_id, comentario.comment_id, ocultar
    )
    if res.get('success'):
        if ocultar:
            comentario.estado = 'oculto'
        else:
            comentario.estado = 'respondido' if comentario.respuesta_texto else 'nuevo'
        comentario.save()
    return res


def enviar_dm_comentario(comentario, texto, usuario):
    """Private reply: envía un DM al autor del comentario (ventana Meta de 7 días).

    Cuando el autor responda el DM, el webhook de Instagram crea el
    Contacto/Conversación por el pipeline normal; aquí solo se marca el envío
    y se intenta vincular la conversación si el contacto ya existe.
    """
    service = InstagramService()
    res = service.enviar_dm_desde_comentario(
        comentario.sesion.session_id, comentario.comment_id, texto
    )
    if res.get('success'):
        comentario.dm_enviado = True
        comentario.save()
        _vincular_conversacion(comentario, res.get('recipient_id'))
    return res


def _vincular_conversacion(comentario, recipient_id):
    if not recipient_id:
        return
    contacto = Contacto.objects.filter(
        sesion=comentario.sesion, external_id=str(recipient_id), status=True
    ).first()
    if not contacto:
        return
    conversacion = contacto.conversaciones.filter(status=True).order_by('-id').first()
    if conversacion:
        comentario.conversacion = conversacion
        comentario.save()
