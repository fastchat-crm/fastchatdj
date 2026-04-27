"""CRUD de Endpoints API del chatbot tradicional.

Los nodos `http` del flujo apuntan a un `EndpointApiChatbot` que define el
host base, headers por defecto y la credencial de autenticación. Esta vista
permite mantener esos endpoints desde la UI del CRM (sin necesidad de admin).

Las credenciales (`CredencialApiChatbot`) se mantienen también acá, en la
misma vista, vía sub-acción `?action=credencial_*`. Permite crear una
credencial sin salir del flujo de creación de endpoint.
"""
import json
import sys
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template
from django.contrib import messages

from core.custom_models import FormError
from core.funciones import addData, paginador, secure_module, log

from .forms import EndpointApiChatbotForm, CredencialApiChatbotForm
from .models import EndpointApiChatbot, CredencialApiChatbot


@login_required
@secure_module
def endpoint_api_view(request):
    data = {
        'titulo': 'Endpoints API',
        'modulo': 'CRM',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    model = EndpointApiChatbot
    Formulario = EndpointApiChatbotForm

    if request.method == 'POST':
        res_json = []
        action = request.POST.get('action', '')
        try:
            with transaction.atomic():
                if action == 'add':
                    form = Formulario(request.POST, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Creó endpoint API {form.instance}", request, "add",
                            obj=form.instance.id)
                        res_json.append({'error': False, 'reload': True})
                    else:
                        raise FormError(form)

                elif action == 'change':
                    filtro = model.objects.get(pk=int(request.POST['pk']))
                    form = Formulario(request.POST, instance=filtro, request=request)
                    if form.is_valid() and filtro:
                        form.save()
                        log(f"Editó endpoint API {form.instance}", request, "change",
                            obj=form.instance.id)
                        res_json.append({'error': False, 'reload': True})
                    else:
                        raise FormError(form)

                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    # Soft-delete; los nodos http que lo usan quedan apuntando
                    # al endpoint inactivo y fallarán al ejecutar — lo cual es
                    # mejor que romper la FK con on_delete=PROTECT.
                    if filtro.nodos.filter(status=True).exists():
                        n = filtro.nodos.filter(status=True).count()
                        res_json = [{
                            'error': True,
                            'message': f'No se puede eliminar: {n} nodo(s) http del flujo aún apuntan a este endpoint.',
                        }]
                    else:
                        filtro.status = False
                        filtro.save(request)
                        log(f"Eliminó endpoint API {filtro}", request, "del", obj=filtro.id)
                        messages.success(request, 'Endpoint eliminado')
                        res_json = {'error': False}

                elif action == 'credencial_add':
                    form = CredencialApiChatbotForm(request.POST, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Creó credencial API {form.instance}", request, "add",
                            obj=form.instance.id)
                        res_json.append({'error': False, 'reload': True})
                    else:
                        raise FormError(form)

                elif action == 'credencial_change':
                    cred = CredencialApiChatbot.objects.get(pk=int(request.POST['pk']))
                    form = CredencialApiChatbotForm(request.POST, instance=cred,
                                                    request=request)
                    if form.is_valid() and cred:
                        form.save()
                        log(f"Editó credencial API {form.instance}", request, "change",
                            obj=form.instance.id)
                        res_json.append({'error': False, 'reload': True})
                    else:
                        raise FormError(form)

                elif action == 'credencial_delete':
                    cred = CredencialApiChatbot.objects.get(pk=int(request.POST['id']))
                    if cred.endpoints.filter(status=True).exists():
                        n = cred.endpoints.filter(status=True).count()
                        res_json = [{
                            'error': True,
                            'message': f'No se puede eliminar: {n} endpoint(s) la usan.',
                        }]
                    else:
                        cred.status = False
                        cred.save(request)
                        log(f"Eliminó credencial API {cred}", request, "del", obj=cred.id)
                        res_json = {'error': False}

        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            line = sys.exc_info()[-1].tb_lineno
            res_json.append({'error': True, 'message': f'{ex} - Line {line}'})
        return JsonResponse(res_json, safe=False)

    # ── GET ──────────────────────────────────────────────────────
    addData(request, data)
    if 'action' in request.GET:
        action = request.GET['action']
        data['action'] = action

        if action == 'add':
            try:
                data['form'] = Formulario()
                template = get_template('crm/endpoints_api/form.html')
                return JsonResponse({'result': True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({'result': False, 'message': str(ex)})

        elif action == 'change':
            try:
                pk = int(request.GET['id'])
                filtro = model.objects.get(pk=pk)
                data['filtro'] = filtro
                data['form'] = Formulario(instance=filtro)
                template = get_template('crm/endpoints_api/form.html')
                return JsonResponse({'result': True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({'result': False, 'message': str(ex)})

        elif action == 'credencial_add':
            try:
                data['form'] = CredencialApiChatbotForm()
                data['action'] = 'credencial_add'
                template = get_template('crm/endpoints_api/form_credencial.html')
                return JsonResponse({'result': True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({'result': False, 'message': str(ex)})

        elif action == 'credencial_change':
            try:
                pk = int(request.GET['id'])
                cred = CredencialApiChatbot.objects.get(pk=pk)
                data['filtro'] = cred
                data['form'] = CredencialApiChatbotForm(instance=cred)
                data['action'] = 'credencial_change'
                template = get_template('crm/endpoints_api/form_credencial.html')
                return JsonResponse({'result': True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({'result': False, 'message': str(ex)})

    # Listado principal
    criterio = request.GET.get('criterio', '').strip()
    filtros, url_vars = Q(status=True), ''
    if criterio:
        filtros = filtros & (
            Q(nombre__icontains=criterio) | Q(base_url__icontains=criterio)
        )
        data['criterio'] = criterio
        url_vars += '&criterio=' + criterio

    listado = model.objects.filter(filtros).select_related('credencial').order_by('nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['credenciales'] = CredencialApiChatbot.objects.filter(status=True).order_by('nombre')
    paginador(request, listado, 20, data, url_vars)
    return render(request, 'crm/endpoints_api/listado.html', data)
