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
                if action == 'eliminar_dispositivo':
                    try:
                        from webpush.models import PushInformation
                        pid = int(request.POST.get('id') or 0)
                        pi = PushInformation.objects.filter(pk=pid).select_related('subscription', 'user').first()
                        if not pi:
                            return JsonResponse([{'error': True, 'message': 'Dispositivo no encontrado.'}], safe=False)
                        sub = pi.subscription
                        uid = pi.user_id
                        pi.delete()
                        try:
                            if sub and not sub.webpush_info.exists():
                                sub.delete()
                        except Exception:
                            pass
                        log(f'Dispositivo push {pid} eliminado (usuario {uid})', request, 'del')
                        return JsonResponse([{'error': False, 'message': 'Dispositivo eliminado.'}], safe=False)
                    except Exception as ex:
                        return JsonResponse([{'error': True, 'message': str(ex)}], safe=False)

                if action == 'enviar_a_dispositivo':
                    try:
                        from webpush.models import PushInformation
                        from pwa.notificaciones import _payload
                        from webpush import utils as _wpu
                        import json as _json
                        pid = int(request.POST.get('id') or 0)
                        pi = PushInformation.objects.filter(pk=pid).select_related('subscription', 'user').first()
                        if not pi:
                            return JsonResponse([{'error': True, 'message': 'Dispositivo no encontrado.'}], safe=False)
                        titulo = (request.POST.get('titulo') or 'Notificación de prueba').strip()[:120]
                        cuerpo = (request.POST.get('cuerpo') or 'Esta es una notificación de prueba.').strip()[:300]
                        url_destino = (request.POST.get('url') or '/perfilpanel/').strip() or '/perfilpanel/'
                        payload = _payload(titulo, cuerpo, url=url_destino,
                                           tag=f'broadcast-dev-{pid}',
                                           extra={'tipo': 'broadcast.dispositivo', 'from': request.user.id})
                        try:
                            _wpu._send_notification(pi.subscription, _json.dumps(payload), 60)
                            log(f'Push de prueba a dispositivo {pid} ok', request, 'add')
                            return JsonResponse([{'error': False, 'message': 'Enviado al dispositivo.'}], safe=False)
                        except Exception as ex:
                            return JsonResponse([{'error': True, 'message': f'Falló envío: {ex}'}], safe=False)
                    except Exception as ex:
                        return JsonResponse([{'error': True, 'message': str(ex)}], safe=False)

                if action == 'enviar_prueba':
                    ids = [int(x) for x in (request.POST.get('ids') or '').split(',') if x.strip().isdigit()]
                    titulo = (request.POST.get('titulo') or '🔔 Notificación de prueba').strip()[:120]
                    cuerpo = (request.POST.get('cuerpo') or '✅ Hola, esta es una notificación de prueba desde el panel de difusión push.').strip()[:300]
                    url_destino = (request.POST.get('url') or '/perfilpanel/').strip() or '/perfilpanel/'
                    if not ids:
                        return JsonResponse([{'error': True, 'message': 'No seleccionaste ningún usuario.'}], safe=False)
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
                    titulo = (request.POST.get('titulo') or '📣 Aviso para todos').strip()[:120]
                    cuerpo = (request.POST.get('cuerpo') or '🚀 Mensaje masivo enviado a todos los dispositivos suscriptos.').strip()[:300]
                    url_destino = (request.POST.get('url') or '/perfilpanel/').strip() or '/perfilpanel/'
                    try:
                        from pwa.notificaciones import enviar_push_usuario
                    except Exception:
                        return JsonResponse([{'error': True, 'message': 'Módulo de notificaciones PWA no disponible.'}], safe=False)
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

    from django.db.models import Prefetch
    try:
        from whatsapp.models import PerfilSesionWhatsApp as _PSW
        prefetch_psw = Prefetch(
            'perfilsesionwhatsapp_set',
            queryset=_PSW.objects.filter(status=True).select_related('sesion'),
        )
    except Exception:
        prefetch_psw = None
    try:
        from whatsapp.models import SesionWhatsApp as _SW
        prefetch_sw = Prefetch(
            'sesionwhatsapp_set',
            queryset=_SW.objects.filter(status=True),
        )
    except Exception:
        prefetch_sw = None
    try:
        from webpush.models import PushInformation as _PI
        prefetch_pi = Prefetch(
            'webpush_info',
            queryset=_PI.objects.select_related('subscription'),
        )
    except Exception:
        prefetch_pi = None

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
    prefetches = [p for p in (prefetch_psw, prefetch_sw, prefetch_pi) if p is not None]
    if prefetches:
        usuarios = usuarios.prefetch_related(*prefetches)
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

    dispositivos = []
    try:
        from urllib.parse import urlparse
        from webpush.models import PushInformation
        dev_user_filter = request.GET.get('dev_user') or ''
        dev_qs = (
            PushInformation.objects
            .select_related('subscription', 'user')
            .order_by('-id')
        )
        if dev_user_filter and dev_user_filter.isdigit():
            dev_qs = dev_qs.filter(user_id=int(dev_user_filter))
            data['dev_user'] = dev_user_filter
        for d in dev_qs[:500]:
            sub = d.subscription
            endpoint = (sub.endpoint or '') if sub else ''
            host = ''
            if endpoint:
                try:
                    host = urlparse(endpoint).netloc
                except Exception:
                    host = endpoint[:40]
            usuario_nombre = ''
            usuario_username = ''
            if d.user_id:
                usuario_nombre = (d.user.get_full_name() or '').strip() or d.user.username
                usuario_username = d.user.username
            dispositivos.append({
                'id': d.id,
                'user_id': d.user_id,
                'usuario_nombre': usuario_nombre,
                'usuario_username': usuario_username,
                'browser': (sub.browser if sub else '') or 'Desconocido',
                'host': host,
                'endpoint_preview': (endpoint[:60] + '…') if len(endpoint) > 60 else endpoint,
            })
    except Exception:
        pass
    data['dispositivos'] = dispositivos

    paginador(request, usuarios, 25, data, url_vars)
    return render(request, 'seguridad/webpush_broadcast/listado.html', data)
