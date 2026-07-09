"""Publicaciones de Instagram: grilla en vivo desde Graph API con métricas y
moderación de comentarios por post (modal tipo post, sin salir de la grilla)."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from core.funciones import addData, secure_module
from meta.instagram import InstagramService
from whatsapp.models import ComentarioSocial, SesionWhatsApp
from whatsapp.permisos_sesion import sesiones_vista_completa


@login_required
@secure_module
def publicacionesView(request):
    data = {
        'titulo': 'Publicaciones Instagram',
        'descripcion': 'Tus posts con sus métricas y comentarios recibidos',
        'ruta': request.path,
    }
    addData(request, data)

    cuentas = sesiones_vista_completa(request.user).filter(
        proveedor='instagram'
    ).order_by('nombre')
    data['cuentas'] = cuentas

    if request.method == 'POST':
        from whatsapp.view_comentarios import _procesar_accion
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
        template = get_template('instagram/publicaciones/_comentarios_post.html')
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
        res = InstagramService().listar_publicaciones(cuenta.session_id)
        if res.get('success'):
            publicaciones = res.get('publicaciones') or []
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
        else:
            error = res.get('error')

    data['publicaciones'] = publicaciones
    data['error_api'] = error
    data['list_count'] = len(publicaciones)
    return render(request, 'instagram/publicaciones/listado.html', data)
