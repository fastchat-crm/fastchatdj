import sys
from datetime import date

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render

from autenticacion.models import Usuario
from core.funciones import addData, paginador, secure_module, log
from core.funciones_adicionales import salva_logs


@login_required
@secure_module
def webpush_broadcast(request):
    data = {
        'titulo': 'Push broadcast',
        'modulo': 'Push broadcast',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)

    try:
        from webpush.models import PushInformation
        total_subs = PushInformation.objects.count()
        users_con_push = (
            Usuario.objects.filter(webpush_info__isnull=False).distinct().count()
        )
    except Exception:
        total_subs = 0
        users_con_push = 0
    data['total_subs'] = total_subs
    data['users_con_push'] = users_con_push

    if request.method == 'POST':
        res_json = []
        action = request.POST.get('action', '')
        try:
            with transaction.atomic():
                if action == 'enviar_prueba':
                    ids = [int(x) for x in (request.POST.get('ids') or '').split(',') if x.strip().isdigit()]
                    titulo = (request.POST.get('titulo') or 'Test notification').strip()[:120]
                    cuerpo = (request.POST.get('cuerpo') or 'This is a test push from Push broadcast.').strip()[:300]
                    url_destino = (request.POST.get('url') or '/perfilpanel/').strip() or '/perfilpanel/'
                    if not ids:
                        return JsonResponse([{'error': True, 'message': 'No users selected.'}], safe=False)
                    enviados = 0
                    fallaron = 0
                    try:
                        from pwa.notificaciones import enviar_push_usuario
                    except Exception:
                        return JsonResponse([{'error': True, 'message': 'PWA push module unavailable.'}], safe=False)
                    usuarios = Usuario.objects.filter(id__in=ids)
                    for u in usuarios:
                        ok = enviar_push_usuario(
                            u,
                            head=titulo,
                            body=cuerpo,
                            url=url_destino,
                            tag=f'broadcast-{request.user.id}',
                            extra={'tipo': 'broadcast.prueba', 'from': request.user.id},
                        )
                        if ok:
                            enviados += 1
                        else:
                            fallaron += 1
                    log(f'Push broadcast prueba: {enviados} ok / {fallaron} fail (ids={ids})', request, 'add')
                    return JsonResponse([{
                        'error': False,
                        'enviados': enviados,
                        'fallaron': fallaron,
                        'message': f'{enviados} sent · {fallaron} failed.',
                    }], safe=False)

                if action == 'enviar_a_todos_con_push':
                    titulo = (request.POST.get('titulo') or 'Test notification').strip()[:120]
                    cuerpo = (request.POST.get('cuerpo') or 'Broadcast to every subscribed device.').strip()[:300]
                    url_destino = (request.POST.get('url') or '/perfilpanel/').strip() or '/perfilpanel/'
                    try:
                        from pwa.notificaciones import enviar_push_usuario
                    except Exception:
                        return JsonResponse([{'error': True, 'message': 'PWA push module unavailable.'}], safe=False)
                    usuarios = (
                        Usuario.objects.filter(webpush_info__isnull=False, is_active=True)
                        .distinct()
                    )
                    enviados = 0
                    fallaron = 0
                    for u in usuarios:
                        ok = enviar_push_usuario(
                            u,
                            head=titulo,
                            body=cuerpo,
                            url=url_destino,
                            tag=f'broadcast-all-{request.user.id}',
                            extra={'tipo': 'broadcast.todos', 'from': request.user.id},
                        )
                        if ok:
                            enviados += 1
                        else:
                            fallaron += 1
                    log(f'Push broadcast a todos: {enviados} ok / {fallaron} fail', request, 'add')
                    return JsonResponse([{
                        'error': False,
                        'enviados': enviados,
                        'fallaron': fallaron,
                        'message': f'{enviados} sent · {fallaron} failed.',
                    }], safe=False)
        except Exception as ex:
            salva_logs(request, __file__, request.method, action, type(ex).__name__,
                       'Error on line {}'.format(sys.exc_info()[-1].tb_lineno), ex)
            res_json.append({'error': True, 'message': 'Try again.'})
        return JsonResponse(res_json, safe=False)

    criterio = (request.GET.get('criterio') or '').strip()
    grupoid = [int(x) for x in request.GET.getlist('grupoid', []) if str(x).isdigit()]
    sesion_id = request.GET.get('sesion_id') or ''
    solo_con_push = request.GET.get('solo_con_push') or ''
    url_vars = ''

    filtros = Q(is_active=True)
    if criterio:
        url_vars += f'&criterio={criterio}'
        data['criterio'] = criterio
        filtros &= (
            Q(first_name__icontains=criterio)
            | Q(last_name__icontains=criterio)
            | Q(documento__icontains=criterio)
            | Q(username__icontains=criterio)
            | Q(email__icontains=criterio)
        )
    if grupoid:
        data['grupoid'] = grupoid
        for g in grupoid:
            url_vars += f'&grupoid={g}'
        filtros &= Q(groups__in=grupoid)
    if sesion_id and sesion_id.isdigit():
        data['sesion_id'] = sesion_id
        url_vars += f'&sesion_id={sesion_id}'
        filtros &= (
            Q(sesionwhatsapp__id=int(sesion_id))
            | Q(perfilsesionwhatsapp__sesion_id=int(sesion_id), perfilsesionwhatsapp__status=True)
        )
    if solo_con_push == '1':
        data['solo_con_push'] = '1'
        url_vars += '&solo_con_push=1'
        filtros &= Q(webpush_info__isnull=False)

    usuarios = (
        Usuario.objects.filter(filtros)
        .annotate(
            n_devices=Count('webpush_info', distinct=True),
            n_sesiones_responsable=Count('sesionwhatsapp', filter=Q(sesionwhatsapp__status=True), distinct=True),
            n_sesiones_miembro=Count(
                'perfilsesionwhatsapp',
                filter=Q(perfilsesionwhatsapp__status=True),
                distinct=True,
            ),
        )
        .order_by('last_name', 'first_name')
        .distinct()
    )
    data['url_vars'] = url_vars
    data['gruposrol'] = Group.objects.all().order_by('name')

    try:
        from whatsapp.models import SesionWhatsApp
        data['sesiones_disponibles'] = (
            SesionWhatsApp.objects.filter(status=True)
            .order_by('nombre', 'numero')
        )
    except Exception:
        data['sesiones_disponibles'] = []

    paginador(request, usuarios, 25, data, url_vars)
    return render(request, 'seguridad/webpush_broadcast/listado.html', data)
