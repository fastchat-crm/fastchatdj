import json
import sys
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages

from core.funciones import addData, paginador, secure_module, redirectAfterPostGet, log
from core.funciones_adicionales import salva_logs
from .models import SesionWhatsApp
from .redis_publish import enviar_comando_start, enviar_comando_close
from core.custom_models import FormError

@login_required
@secure_module
def sesionesView(request):
    data = {
        'titulo': 'Sesiones WhatsApp',
        'modulo': 'Sesiones WhatsApp',
        'ruta': request.path
    }
    addData(request, data)
    model = SesionWhatsApp

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':
                    # Creamos la sesión en estado pendiente sin número
                    sesion = SesionWhatsApp.objects.create(estado='pendiente', usuario=request.user)
                    enviar_comando_start(sesion.id)  # Mandamos el ID como identificador de sesión al Node

                    log(f"Inicio de sesión WhatsApp pendiente (ID: {sesion.id})", request, "add", obj=sesion.id)
                    res_json = {'error': False, 'qr': '', 'session_id': sesion.id}
                    return JsonResponse(res_json, safe=False)
                elif action == 'refresh_qr':
                    try:
                        sesion_id = int(request.POST.get('session_id'))
                        sesion = get_object_or_404(SesionWhatsApp, id=sesion_id)
                        if sesion.estado in ['pendiente', 'desconectado']:
                            # Cambiamos estado a pendiente y limpiamos QR anterior
                            sesion.estado = 'pendiente'
                            sesion.qr_code = ''
                            sesion.save()
                            # Mandamos nuevamente el comando al Node.js
                            enviar_comando_start(sesion.id)
                            log(f"Regeneró QR para sesión WhatsApp (ID: {sesion.id})", request, "change", obj=sesion.id)
                            return JsonResponse({'error': False})
                        else:
                            return JsonResponse({'error': True,
                                                 'message': 'Solo se puede regenerar QR para sesiones pendientes o desconectadas.'})
                    except Exception as ex:
                        return JsonResponse({'error': True, 'message': 'Error al regenerar QR'})
                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    filtro.status = False
                    filtro.save(request)
                    enviar_comando_close(filtro.numero)
                    log(f"Eliminó sesión WhatsApp {filtro.numero}", request, "del", obj=filtro.id)
                    messages.success(request, "Sesión eliminada correctamente.")
                    return redirect(redirectAfterPostGet(request))

        except Exception as ex:
            res_json.append({'error': True, 'message': "Error, intente nuevamente."})
            return JsonResponse(res_json, safe=False)
    else:
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'get_qr':
                try:
                    sesion_id = request.GET.get('session_id')
                    if not sesion_id:
                        return JsonResponse({'error': True, 'message': 'ID de sesión no enviado'})

                    sesion = get_object_or_404(SesionWhatsApp, id=int(sesion_id))
                    return JsonResponse({'error': False, 'qr': sesion.qr_code if sesion.qr_code else ''})
                except SesionWhatsApp.DoesNotExist:
                    return JsonResponse({'error': True, 'message': 'Sesión no encontrada'})
                except Exception as ex:
                    return JsonResponse({'error': True, 'message': f'Error al obtener QR: {str(ex)}'})
            elif action == 'check_status':
                try:
                    sesion_id = request.GET.get('session_id')
                    sesion = get_object_or_404(SesionWhatsApp, id=int(sesion_id))

                    return JsonResponse({
                        'error': False,
                        'estado': sesion.estado,
                        'numero': sesion.numero,
                    })
                except Exception as ex:
                    return JsonResponse({'error': True, 'message': 'Error al consultar estado'})

    # ====================== LISTADO SESIONES =========================
    criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True), ''
    if criterio:
        filtros = filtros & (Q(numero__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio

    listado = model.objects.filter(filtros)
    data["list_count"] = listado.count()
    data["url_vars"] = url_vars
    paginador(request, listado.order_by('numero'), 10, data, url_vars)
    return render(request, 'whatsapp/sesiones/listado.html', data)