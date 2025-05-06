import uuid
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib import messages
from django.urls import reverse
from core.funciones import addData, paginador, secure_module, log
from .models import SesionWhatsApp
from .services import WhatsAppService


@login_required
@secure_module
def sesionesView(request):
    whatsapp_service = WhatsAppService()
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
                    last_session_id = request.POST.get('last_session_id') or 0
                    last_session = SesionWhatsApp.objects.filter(id=last_session_id).first()

                    session = last_session or SesionWhatsApp.objects.create(
                        estado='pendiente', usuario=request.user, session_id=str(uuid.uuid4()), qr_code=''
                    )

                    session.qr_code = ''

                    log(f"Inicio de sesión WhatsApp pendiente (ID: {session.id})", request, "add", obj=session.id)
                    res_json = {'error': False, 'qr': session.qr_code, 'session_id': session.id}
                    return JsonResponse(res_json, safe=False)
                if action == 'create_session':
                    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
                    session_id = request.POST['session_id']
                    session = SesionWhatsApp.objects.get(id=session_id)
                    result = whatsapp_service.create_session(session, webhook_url)
                    session.qr_code = result.get('qr_code')
                    session.save()
                    log(f"Crear sesión WhatsApp pendiente (ID: {session.id})", request, "create_session", obj=session.id)
                    res_json = {'error': False, 'qr': session.qr_code, 'session_id': session.id}
                    return JsonResponse(res_json, safe=False)
                # elif action == 'delete':
                #     filtro = model.objects.get(pk=int(request.POST['id']))
                #     filtro.status = False
                #     filtro.save(request)
                #     result = whatsapp_service.close_session(filtro.session_id)
                #     log(f"Eliminó sesión WhatsApp {filtro.numero}", request, "del", obj=filtro.id)
                #     messages.success(request, "Sesión eliminada correctamente.")
                #     return JsonResponse({"error": False})

        except Exception as ex:
            res_json.append({'error': True, 'message': "Error, intente nuevamente."})
            return JsonResponse(res_json, safe=False)
    # ====================== LISTADO SESIONES =========================
    criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True, usuario_id=request.user.id), ''
    if criterio:
        filtros = filtros & (Q(numero__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio

    listado = model.objects.filter(filtros)
    data["list_count"] = listado.count()
    data["url_vars"] = url_vars
    paginador(request, listado.order_by('numero'), 10, data, url_vars)
    return render(request, 'whatsapp/sesiones/listado.html', data)