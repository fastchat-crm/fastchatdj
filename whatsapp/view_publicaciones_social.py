"""Grilla de publicaciones sociales por canal (Instagram/Facebook): posts en vivo
desde Graph API con métricas + modal de moderación de comentarios por publicación.
Los wrappers por canal viven en `instagram/view_posts.py` y `facebook/view_posts.py`."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from core.funciones import addData, secure_module

from .funciones_comentarios import service_por_canal
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
        from .view_comentarios import _procesar_accion
        return _procesar_accion(request, sesiones_vista_completa(request.user))

    if request.GET.get('action') == 'comentarios_post':
        media_id = (request.GET.get('media_id') or '').strip()
        if not media_id:
            return JsonResponse({'result': False, 'message': 'Publicación no indicada.'})
        comentarios = list(
            ComentarioSocial.objects.filter(
                status=True, media_id=media_id, sesion__in=cuentas
            ).select_related('respondido_por', 'conversacion')
            .order_by('-fecha_comentario', '-id')[:100]
        )
        data['comentarios_post'] = comentarios
        data['media_id'] = media_id
        template = get_template(conf['partial'])
        return JsonResponse({'result': True, 'data': template.render(data), 'total': len(comentarios)})

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
