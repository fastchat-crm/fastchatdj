"""Grilla de publicaciones sociales por canal (Instagram/Facebook): posts en vivo
desde Graph API con métricas + modal de moderación de comentarios por publicación.
Los wrappers por canal viven en `instagram/view_posts.py` y `facebook/view_posts.py`."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from core.funciones import addData, log, secure_module

from .funciones_comentarios import service_por_canal, sincronizar_comentarios_publicacion
from .funciones_publicaciones import anotar_comentarios_crm
from .models import PROVEEDOR_POR_CANAL, ComentarioSocial
from .permisos_sesion import sesiones_vista_completa

CONFIG_PUBLICACIONES_CANAL = {
    'instagram': {
        'titulo': 'Publicaciones Instagram',
        'descripcion': 'Tus posts con sus métricas y comentarios recibidos',
        'template': 'instagram/publicaciones/listado.html',
        'partial': 'instagram/publicaciones/_comentarios_post.html',
    },
    'facebook': {
        'titulo': 'Publicaciones Facebook',
        'descripcion': 'Los posts de tu página con sus métricas y comentarios recibidos',
        'template': 'facebook/publicaciones/listado.html',
        'partial': 'facebook/publicaciones/_comentarios_post.html',
    },
}


@login_required
@secure_module
def publicacionesSocialView(request, canal):
    conf = CONFIG_PUBLICACIONES_CANAL[canal]
    data = {
        'titulo': conf['titulo'],
        'descripcion': conf['descripcion'],
        'ruta': request.path,
    }
    addData(request, data)

    cuentas = sesiones_vista_completa(request.user).filter(
        proveedor=PROVEEDOR_POR_CANAL[canal]
    ).order_by('nombre')
    data['cuentas'] = cuentas

    if request.method == 'POST':
        if request.POST.get('action') == 'publicar_post':
            cuenta_id = (request.POST.get('cuenta') or '').strip()
            cuenta = cuentas.filter(id=int(cuenta_id)).first() if cuenta_id.isdigit() else None
            if not cuenta:
                return JsonResponse({'error': True, 'message': 'Página/cuenta no válida.'})
            mensaje = (request.POST.get('mensaje') or '').strip()
            foto_url = (request.POST.get('foto_url') or '').strip()
            link = (request.POST.get('link') or '').strip()
            if not mensaje and not foto_url and not link:
                return JsonResponse({'error': True, 'message': 'Escribí un texto, un link o la URL de una imagen.'})
            res = service_por_canal(canal).publicar_post(
                cuenta.session_id, mensaje, foto_url=foto_url or None, link=link or None,
            )
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': f"Meta rechazó la publicación: {res.get('error')}"})
            log(f"Publicó un post en {canal} ({cuenta.nombre}): {mensaje[:80]}",
                request, "add", obj=cuenta.id)
            return JsonResponse({'error': False, 'message': 'Publicación creada correctamente.',
                                 'post_id': res.get('post_id') or ''})
        from .view_comentarios import _procesar_accion
        return _procesar_accion(request, sesiones_vista_completa(request.user))

    if request.GET.get('action') == 'comentarios_post':
        media_id = (request.GET.get('media_id') or '').strip()
        if not media_id:
            return JsonResponse({'result': False, 'message': 'Publicación no indicada.'})
        # Sync en vivo: los comentarios hechos antes de suscribir el webhook (o
        # cuyos eventos se rechazaron) no están en BD — sin esto el post decía
        # "1 comentario" (métrica de Meta) y el modal salía vacío.
        cuenta_id = (request.GET.get('cuenta') or '').strip()
        cuenta_sync = cuentas.filter(id=int(cuenta_id)).first() if cuenta_id.isdigit() else cuentas.first()
        sincronizados = 0
        if cuenta_sync:
            sincronizados = sincronizar_comentarios_publicacion(cuenta_sync, canal, media_id)
        comentarios = list(
            ComentarioSocial.objects.filter(
                status=True, media_id=media_id, sesion__in=cuentas
            ).select_related('respondido_por', 'conversacion')
            .order_by('-fecha_comentario', '-id')[:100]
        )
        data['comentarios_post'] = comentarios
        data['media_id'] = media_id
        template = get_template(conf['partial'])
        return JsonResponse({'result': True, 'data': template.render(data),
                             'total': len(comentarios), 'sincronizados': sincronizados})

    cuenta = None
    cuenta_id = (request.GET.get('cuenta') or '').strip()
    if cuenta_id.isdigit():
        cuenta = cuentas.filter(id=int(cuenta_id)).first()
    if cuenta is None:
        cuenta = cuentas.first()
    data['cuenta_seleccionada'] = cuenta

    publicaciones = []
    error = None
    if cuenta:
        res = service_por_canal(canal).listar_publicaciones(cuenta.session_id)
        if res.get('success'):
            publicaciones = res.get('publicaciones') or []
            anotar_comentarios_crm(publicaciones, cuenta)
        else:
            error = res.get('error')

    data['publicaciones'] = publicaciones
    data['error_api'] = error
    data['list_count'] = len(publicaciones)
    return render(request, conf['template'], data)
