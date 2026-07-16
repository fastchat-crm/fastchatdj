"""Cuentas TikTok: pre-registro y control mientras se aprueba el acceso a la
Business Messaging API (beta). Al llegar la aprobación, el canal se activa
sin re-registrar nada."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, paginador, secure_module
from whatsapp.models import SesionWhatsApp

from .funciones_cuentas import guardar_cuenta


@login_required
@secure_module
def cuentasView(request):
    if request.method == 'POST':
        return _procesar_accion(request)

    data = {
        'titulo': 'Sesiones TikTok',
        'descripcion': 'Pre-registra sesiones TikTok Business para activarlas al aprobar la API',
        'ruta': request.path,
    }
    addData(request, data)

    qs = SesionWhatsApp.objects.filter(
        status=True, proveedor='tiktok'
    ).select_related('config_tiktok', 'usuario')
    if not request.user.is_superuser:
        qs = qs.filter(usuario=request.user)

    url_vars = ''
    criterio = (request.GET.get('criterio') or '').strip()
    if criterio:
        qs = qs.filter(
            Q(nombre__icontains=criterio)
            | Q(config_tiktok__username__icontains=criterio)
        )
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'

    listado = qs.order_by('nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['webhook_url'] = request.build_absolute_uri('/whatsapp/tiktok_webhook/')
    paginador(request, listado, 25, data, url_vars)
    return render(request, 'tiktok/cuentas/listado.html', data)


def _sesion_del_usuario(request, pk):
    qs = SesionWhatsApp.objects.filter(pk=pk, status=True, proveedor='tiktok')
    if not request.user.is_superuser:
        qs = qs.filter(usuario=request.user)
    return qs.select_related('config_tiktok').first()


def _procesar_accion(request):
    action = request.POST.get('action')
    try:
        if action == 'add':
            res = guardar_cuenta(request)
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': res.get('error')})
            log('Cuenta TikTok registrada', request, 'add', obj=res['sesion'].id)
            return JsonResponse({'error': False, 'message': 'Cuenta registrada.', 'reload': True})

        if action == 'change':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Cuenta no encontrada.'})
            res = guardar_cuenta(request, sesion)
            if not res.get('success'):
                return JsonResponse({'error': True, 'message': res.get('error')})
            log('Cuenta TikTok actualizada', request, 'change', obj=sesion.id)
            return JsonResponse({'error': False, 'message': 'Cuenta actualizada.', 'reload': True})

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
            log(f'Cuenta TikTok {estado}', request, 'change', obj=sesion.id)
            return JsonResponse({'error': False, 'message': f'Cuenta {estado}.', 'reload': True})

        if action == 'delete':
            sesion = _sesion_del_usuario(request, int(request.POST.get('pk', 0)))
            if not sesion:
                return JsonResponse({'error': True, 'message': 'Cuenta no encontrada.'})
            sesion.status = False
            sesion.save()
            log('Cuenta TikTok eliminada', request, 'delete', obj=sesion.id)
            return JsonResponse({'error': False, 'message': 'Cuenta eliminada.'})

    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})
