import json
import sys
from datetime import datetime

import pytz
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
from .services import WhatsAppService

whatsapp_service = WhatsAppService()

@login_required
@secure_module
def sesionesView(request):
    data = {
        'titulo': 'Sesiones WhatsApp',
        'descripcion': 'Control de números de teléfono para sesiones de WhatsApp',
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
                    name = request.user.get_full_name() or request.user.username
                    result = whatsapp_service.create_session(name)
                    sesion = SesionWhatsApp.objects.create(
                        estado='pendiente', usuario=request.user, session_id=result['sessionId'], qr_code=''
                    )

                    log(f"Inicio de sesión WhatsApp pendiente (ID: {sesion.id})", request, "add", obj=sesion.id)
                    res_json = {'error': False, 'qr': '', 'session_id': sesion.id}
                    return JsonResponse(res_json, safe=False)
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
                    qr_code = whatsapp_service.get_qr_code(sesion.session_id)
                    return JsonResponse({'error': False, 'qr': qr_code})
                except SesionWhatsApp.DoesNotExist:
                    return JsonResponse({'error': True, 'message': 'Sesión no encontrada'})
                except Exception as ex:
                    return JsonResponse({'error': True, 'message': f'Error al obtener QR: {str(ex)}'})
            elif action == 'check_status':
                try:
                    sessions_id = json.loads(request.GET['sessions'])
                    sessions = SesionWhatsApp.objects.filter(id__in=sessions_id)
                    response = {}
                    is_authenticated = False
                    for s in sessions:
                        session_status = whatsapp_service.check_session_status(s.session_id)
                        if not is_authenticated:
                            is_authenticated = session_status.get('isReady', False)
                            if is_authenticated:
                                s.numero = session_status['info']['phone']
                                s.estado = 'conectado'
                                dt = datetime.strptime(session_status['lastActivity'], '%Y-%m-%dT%H:%M:%S.%fZ')
                                dt_utc = dt.replace(tzinfo=pytz.UTC)
                                s.ultima_conexion = dt_utc
                                s.save()
                                response = {
                                    'error': False,
                                    'estado': s.estado,
                                    'numero': s.numero,
                                    'is_authenticated': is_authenticated,
                                    'session_id': s.id
                                }

                    if is_authenticated:
                        SesionWhatsApp.objects.filter(id__in=sessions_id).exclude(id=response['session_id']).delete()

                    return JsonResponse(response)
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