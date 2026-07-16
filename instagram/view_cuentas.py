"""Cuentas Instagram conectadas: listado, conexión manual con autodetección
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
        'titulo': 'Sesiones Instagram',
        'descripcion': 'Conecta sesiones Instagram Business y controla su estado',
        'ruta': request.path,
    }
    addData(request, data)

    qs = SesionWhatsApp.objects.filter(
        status=True, proveedor='instagram'
    ).select_related('config_instagram', 'usuario')
    if not request.user.is_superuser:
        qs = qs.filter(usuario=request.user)

    url_vars = ''
    criterio = (request.GET.get('criterio') or '').strip()
    if criterio:
        qs = qs.filter(
            Q(nombre__icontains=criterio)
            | Q(config_instagram__username__icontains=criterio)
        )
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'

    listado = qs.order_by('nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['webhook_url'] = request.build_absolute_uri('/whatsapp/instagram_webhook/')
    paginador(request, listado, 25, data, url_vars)
    return render(request, 'instagram/cuentas/listado.html', data)


def _sesion_del_usuario(request, pk):
    qs = SesionWhatsApp.objects.filter(pk=pk, status=True, proveedor='instagram')
    if not request.user.is_superuser:
        qs = qs.filter(usuario=request.user)
    return qs.select_related('config_instagram').first()


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
            log('Cuenta Instagram conectada', request, 'add', obj=res['sesion'].id)
            return JsonResponse({'error': False, 'message': 'Cuenta conectada.', 'reload': True})

        if action == 'change':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Cuenta no encontrada.'})
            res = guardar_cuenta(request, sesion)
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': res.get('error')})
            log('Cuenta Instagram actualizada', request, 'change', obj=sesion.id)
            return JsonResponse({'error': False, 'message': 'Cuenta actualizada.', 'reload': True})

        if action == 'probar':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Cuenta no encontrada.'})
            res = probar_conexion(sesion)
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': f"Sin conexión: {res.get('error')}"})
            perfil = res.get('perfil') or {}
            return JsonResponse({
                'error': False, 'reload': True,
                'message': f"Conectado como @{perfil.get('username', '')} · {perfil.get('followers_count', 0)} seguidores.",
            })

        if action == 'diagnostico':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Cuenta no encontrada.'})
            from whatsapp.diagnostico_social import diagnosticar_conexion
            diag = diagnosticar_conexion(sesion)
            return JsonResponse({'error': False, 'diagnostico': diag})

        if action == 'toggle_activo':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Cuenta no encontrada.'})
            sesion.activo = not sesion.activo
            sesion.save()
            estado = 'activada' if sesion.activo else 'suspendida'
            log(f'Cuenta Instagram {estado}', request, 'change', obj=sesion.id)
            return JsonResponse({'error': False, 'message': f'Cuenta {estado}.', 'reload': True})

        if action == 'delete':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Cuenta no encontrada.'})
            sesion.status = False
            sesion.save()
            log('Cuenta Instagram eliminada', request, 'delete', obj=sesion.id)
            return JsonResponse({'error': False, 'message': 'Cuenta eliminada.'})

    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})
