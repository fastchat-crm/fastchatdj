import uuid
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib import messages
from django.template.loader import get_template
from django.urls import reverse

from core.custom_forms import FormError
from core.funciones import addData, paginador, secure_module, log, redirectAfterPostGet
from crm.models import AgentesIA, PerfilNegocioIA
from .forms import SesionWhatsAppForm
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
    perfil, creado = PerfilNegocioIA.objects.get_or_create(usuario=request.user)
    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':
                    last_session_id = request.POST.get('last_session_id') or 0
                    last_session = SesionWhatsApp.objects.filter(id=last_session_id).first()

                    session = last_session or SesionWhatsApp.objects.create(
                        estado='pendiente', usuario=request.user, session_id=str(uuid.uuid4()), qr_code='',
                        whatsapp_id=''
                    )

                    session.qr_code = ''

                    log(f"Inicio de sesión WhatsApp pendiente (ID: {session.id})", request, "add", obj=session.id)
                    res_json = {'error': False, 'qr': session.qr_code, 'session_id': session.id}
                    return JsonResponse(res_json, safe=False)
                elif action == 'create_session':
                    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
                    session_id = request.POST['session_id']
                    session = SesionWhatsApp.objects.get(id=session_id)
                    result = whatsapp_service.create_session(session, webhook_url)
                    session.qr_code = result.get('qr_code')
                    session.save()
                    log(f"Crear sesión WhatsApp pendiente (ID: {session.id})", request, "create_session", obj=session.id)
                    res_json = {'error': False, 'qr': session.qr_code, 'session_id': session.id}
                    return JsonResponse(res_json, safe=False)
                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    result = whatsapp_service.close_session(filtro.session_id)
                    log(f"Sesión de WhatsApp {filtro.numero} desconectada", request, "del", obj=filtro.id)
                    messages.success(request, "Sesión desconectada correctamente.")
                    return JsonResponse({"error": False})
                elif action == 'change':
                    instance = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    form = SesionWhatsAppForm(request.POST, request.FILES, instance=instance)

                    if not form.is_valid():
                        raise FormError(form)

                    obj = form.save()

                    res_json.append({'error': False, 'to': redirectAfterPostGet(request)})
                    return JsonResponse(res_json, safe=False)
                elif action == 'change_modal':
                    instance = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    form = SesionWhatsAppForm(request.POST, request.FILES, instance=instance)

                    if not form.is_valid():
                        raise FormError(form)

                    obj = form.save()
                    res_json.append({'error': False, 'reload': True})
                    return JsonResponse(res_json, safe=False)

                elif action == 'delete_force':
                    session_id = request.POST.get('id')
                    session = SesionWhatsApp.objects.filter(id=session_id).first()
                    if session:
                        from django.utils import timezone
                        tiempo_sin_numero = timezone.now() - session.fecha_registro
                        if tiempo_sin_numero.total_seconds() > 600:  # 10 minutos
                            session.delete()
                            log(f"Sesión eliminada forzadamente por inactividad sin número (ID: {session_id})", request,
                                "delete_force", obj=session_id)
                            return JsonResponse({'error': False, 'message': 'Sesión eliminada forzadamente.'})
                        else:
                            return JsonResponse(
                                {'error': True, 'message': 'La sesión no supera los 10 minutos sin número.'})
                    else:
                        return JsonResponse({'error': True, 'message': 'Sesión no encontrada o ya tiene número.'})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            res_json.append({'error': True, 'message': "Error, intente nuevamente."})
            return JsonResponse(res_json, safe=False)
    # ====================== LISTADO SESIONES =========================
    data['action'] = action = request.GET.get('action')
    if action == 'change':
        data['instance'] = instance = SesionWhatsApp.objects.get(id=request.GET['pk'])
        data['form'] = form = SesionWhatsAppForm(instance=instance)
        form.fields['agente_ia'].queryset = AgentesIA.objects.filter(perfil=perfil, status=True)
        return render(request, 'whatsapp/sesiones/form.html', data)
    if action == 'change_modal':
        try:
            data['instance'] = instance = SesionWhatsApp.objects.get(id=request.GET['pk'])
            data['form'] = form = SesionWhatsAppForm(instance=instance)
            form.fields['agente_ia'].queryset = AgentesIA.objects.filter(perfil=perfil, status=True)
            template = get_template("whatsapp/sesiones/form_modal.html")
            return JsonResponse({"result": True, 'data': template.render(data)})
        except Exception as ex:
            return JsonResponse({"result": False, 'message': str(ex)})
    if action == 'historial_de_sesiones':
        data['instance'] = instance = SesionWhatsApp.objects.get(id=request.GET['pk'])
        data['listado'] = instance.get_log_entries().filter(change_message__istartswith='HS: ')
        return render(request, 'whatsapp/sesiones/historial_de_sesiones.html', data)
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