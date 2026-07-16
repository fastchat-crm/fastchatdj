"""Páginas de Facebook conectadas: listado, conexión manual con autodetección
desde token, prueba de conexión y activación/desactivación."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, paginador, secure_module
from whatsapp.models import SesionWhatsApp

from .funciones_cuentas import autodetectar_desde_token, guardar_cuenta, probar_conexion


@login_required
@secure_module
def cuentasView(request):
    if request.method == 'POST':
        return _procesar_accion(request)

    data = {
        'titulo': 'Sesiones Facebook',
        'descripcion': 'Conecta páginas de Facebook y controla su estado',
        'ruta': request.path,
    }
    addData(request, data)

    qs = SesionWhatsApp.objects.filter(
        status=True, proveedor='messenger'
    ).select_related('config_messenger', 'usuario')
    if not request.user.is_superuser:
        qs = qs.filter(usuario=request.user)

    url_vars = ''
    criterio = (request.GET.get('criterio') or '').strip()
    if criterio:
        qs = qs.filter(
            Q(nombre__icontains=criterio)
            | Q(config_messenger__page_name__icontains=criterio)
        )
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'

    listado = qs.order_by('nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['webhook_url'] = request.build_absolute_uri('/whatsapp/messenger_webhook/')
    paginador(request, listado, 25, data, url_vars)
    return render(request, 'facebook/cuentas/listado.html', data)


def _sesion_del_usuario(request, pk):
    qs = SesionWhatsApp.objects.filter(pk=pk, status=True, proveedor='messenger')
    if not request.user.is_superuser:
        qs = qs.filter(usuario=request.user)
    return qs.select_related('config_messenger').first()


def _procesar_accion(request):
    action = request.POST.get('action')
    try:
        if action == 'autodetectar':
            token = (request.POST.get('access_token') or '').strip()
            if not token:
                return JsonResponse({'error': True, 'message': 'Pega primero el Access Token.'})
            res = autodetectar_desde_token(token)
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': res.get('error')})
            return JsonResponse({'error': False, 'candidatos': res.get('candidatos')})

        if action == 'add':
            res = guardar_cuenta(request)
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': res.get('error')})
            log('Página Facebook conectada', request, 'add', obj=res['sesion'].id)
            return JsonResponse({'error': False, 'message': 'Página conectada.', 'reload': True})

        if action == 'change':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Página no encontrada.'})
            res = guardar_cuenta(request, sesion)
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': res.get('error')})
            log('Página Facebook actualizada', request, 'change', obj=sesion.id)
            return JsonResponse({'error': False, 'message': 'Página actualizada.', 'reload': True})

        if action == 'probar':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Página no encontrada.'})
            res = probar_conexion(sesion)
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': f"Sin conexión: {res.get('error')}"})
            perfil = res.get('perfil') or {}
            return JsonResponse({
                'error': False, 'reload': True,
                'message': f"Conectado a la página {perfil.get('name', '')} · {perfil.get('fan_count', 0)} seguidores.",
            })

        if action == 'diagnostico':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Página no encontrada.'})
            from whatsapp.diagnostico_social import diagnosticar_conexion
            diag = diagnosticar_conexion(sesion)
            return JsonResponse({'error': False, 'diagnostico': diag})

        if action == 'toggle_activo':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Página no encontrada.'})
            sesion.activo = not sesion.activo
            sesion.save()
            estado = 'activada' if sesion.activo else 'suspendida'
            log(f'Página Facebook {estado}', request, 'change', obj=sesion.id)
            return JsonResponse({'error': False, 'message': f'Página {estado}.', 'reload': True})

        if action == 'delete':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Página no encontrada.'})
            sesion.status = False
            sesion.save()
            log('Página Facebook eliminada', request, 'delete', obj=sesion.id)
            return JsonResponse({'error': False, 'message': 'Página eliminada.'})

    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})
