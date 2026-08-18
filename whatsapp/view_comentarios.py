"""Inbox de comentarios de redes sociales (Instagram; TikTok cuando se integre).

Moderación tipo lead: responder públicamente, ocultar o pasar al autor a DM
para convertirlo en conversación del pipeline normal.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, paginador, secure_module

from .funciones_comentarios import (
    enviar_dm_comentario,
    ocultar_comentario,
    responder_comentario,
)
from .models import (
    CANALES_COMENTARIO,
    CANALES_CON_ACCIONES,
    PROVEEDOR_POR_CANAL,
    ComentarioSocial,
)
from .permisos_sesion import sesiones_vista_completa


@login_required
@secure_module
def comentariosView(request, canal_fijo=None):
    sesiones = sesiones_vista_completa(request.user)

    if request.method == 'POST':
        return _procesar_accion(request, sesiones)

    nombre_canal = dict(CANALES_COMENTARIO).get(canal_fijo, 'redes sociales')
    data = {
        'titulo': f'Comentarios de {nombre_canal}',
        'descripcion': 'Comentarios de tus publicaciones: responde, oculta o lleva al autor a DM',
        'ruta': request.path,
        'canal_fijo': canal_fijo,
    }
    addData(request, data)

    qs = ComentarioSocial.objects.filter(
        status=True, sesion__in=sesiones
    ).select_related('sesion', 'respondido_por', 'conversacion')
    if canal_fijo:
        qs = qs.filter(canal=canal_fijo)
        sesiones = sesiones.filter(proveedor=PROVEEDOR_POR_CANAL.get(canal_fijo, canal_fijo))

    url_vars = ''
    criterio = (request.GET.get('criterio') or '').strip()
    if criterio:
        qs = qs.filter(
            Q(texto__icontains=criterio)
            | Q(autor_username__icontains=criterio)
            | Q(media_id__icontains=criterio)
        )
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'

    estado = (request.GET.get('estado') or '').strip()
    if estado:
        qs = qs.filter(estado=estado)
        data['estado'] = estado
        url_vars += f'&estado={estado}'

    sesion_id = (request.GET.get('sesion') or '').strip()
    if sesion_id.isdigit():
        qs = qs.filter(sesion_id=int(sesion_id))
        data['sesion_filtro'] = int(sesion_id)
        url_vars += f'&sesion={sesion_id}'

    listado = qs.order_by('-fecha_comentario', '-id')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['sesiones_sociales'] = sesiones.filter(
        proveedor__in=('instagram', 'messenger', 'tiktok')
    ).order_by('nombre')
    base_qs = ComentarioSocial.objects.filter(status=True, sesion__in=sesiones)
    data['total_nuevos'] = base_qs.filter(estado='nuevo').count()
    data['total_respondidos'] = base_qs.filter(estado='respondido').count()
    data['total_ocultos'] = base_qs.filter(estado='oculto').count()
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'whatsapp/comentarios/listado.html', data)


def _procesar_accion(request, sesiones):
    action = request.POST.get('action')
    try:
        comentario = ComentarioSocial.objects.get(
            pk=int(request.POST.get('pk', 0)), status=True, sesion__in=sesiones
        )
    except (ComentarioSocial.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'error': True, 'message': 'Comentario no encontrado.'})

    if comentario.canal not in CANALES_CON_ACCIONES:
        return JsonResponse({'error': True, 'message': 'Canal aún no soportado para esta acción.'})

    if action == 'responder':
        texto = (request.POST.get('texto') or '').strip()
        if not texto:
            return JsonResponse({'error': True, 'message': 'Escribe la respuesta.'})
        res = responder_comentario(comentario, texto, request.user)
        if not res.get('success'):
            return JsonResponse({'error': True, 'message': f"No se pudo responder: {res.get('error')}"})
        log(f'Comentario {comentario.comment_id} respondido', request, 'change', obj=comentario.id)
        return JsonResponse({'error': False, 'message': 'Respuesta publicada.', 'reload': True})

    if action == 'ocultar':
        res = ocultar_comentario(comentario, True)
        if not res.get('success'):
            return JsonResponse({'error': True, 'message': f"No se pudo ocultar: {res.get('error')}"})
        log(f'Comentario {comentario.comment_id} oculto', request, 'change', obj=comentario.id)
        return JsonResponse({'error': False, 'message': 'Comentario oculto.', 'reload': True})

    if action == 'mostrar':
        res = ocultar_comentario(comentario, False)
        if not res.get('success'):
            return JsonResponse({'error': True, 'message': f"No se pudo mostrar: {res.get('error')}"})
        log(f'Comentario {comentario.comment_id} visible', request, 'change', obj=comentario.id)
        return JsonResponse({'error': False, 'message': 'Comentario visible de nuevo.', 'reload': True})

    if action == 'enviar_dm':
        texto = (request.POST.get('texto') or '').strip()
        if not texto:
            return JsonResponse({'error': True, 'message': 'Escribe el mensaje directo.'})
        res = enviar_dm_comentario(comentario, texto, request.user)
        if not res.get('success'):
            return JsonResponse({'error': True, 'message': f"No se pudo enviar el DM: {res.get('error')}"})
        log(f'DM enviado desde comentario {comentario.comment_id}', request, 'change', obj=comentario.id)
        return JsonResponse({
            'error': False,
            'message': 'DM enviado. Cuando el autor responda, la conversación aparecerá en el inbox.',
            'reload': True,
        })

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})
