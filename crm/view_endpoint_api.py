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
from .models import EndpointApiChatbot, CredencialApiChatbot, OpcionDepartamentoChatBot


def _fusionar_duplicados(request):
    """Agrupa credenciales por (nombre, tipo, secretos) y endpoints por
    (nombre, base_url, credencial_id). En cada grupo deja el de menor pk como
    canónico, repunta hijos al canónico y soft-deletea el resto.

    Returns: (credenciales_fusionadas, endpoints_fusionados).
    """
    cred_dups = 0
    ep_dups = 0

    # ── Credenciales ─────────────────────────────────────────────
    grupos_cred = {}
    for c in CredencialApiChatbot.objects.filter(status=True).order_by('id'):
        key = (c.nombre.strip().lower(), c.tipo, json.dumps(c.secretos, sort_keys=True))
        grupos_cred.setdefault(key, []).append(c)

    for grupo in grupos_cred.values():
        if len(grupo) <= 1:
            continue
        canon = grupo[0]
        for dup in grupo[1:]:
            EndpointApiChatbot.objects.filter(credencial=dup, status=True).update(credencial=canon)
            dup.status = False
            dup.save(request)
            cred_dups += 1

    # ── Endpoints ────────────────────────────────────────────────
    grupos_ep = {}
    for e in EndpointApiChatbot.objects.filter(status=True).order_by('id'):
        key = (
            e.nombre.strip().lower(),
            e.base_url.rstrip('/').lower(),
            e.credencial_id or 0,
        )
        grupos_ep.setdefault(key, []).append(e)

    for grupo in grupos_ep.values():
        if len(grupo) <= 1:
            continue
        canon = grupo[0]
        for dup in grupo[1:]:
            dup.nodos.filter(status=True).update(endpoint=canon)
            dup.status = False
            dup.save(request)
            ep_dups += 1

    return cred_dups, ep_dups


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
                    force = request.POST.get('force') == '1'
                    n = filtro.nodos.filter(status=True).count()
                    if n and not force:
                        res_json = [{
                            'error': True,
                            'confirm': True,
                            'count': n,
                            'message': f'{n} nodo(s) http del flujo aún apuntan a este endpoint. ¿Eliminar de todas formas? Los nodos quedarán apuntando al endpoint inactivo y fallarán al ejecutarse.',
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
                    force = request.POST.get('force') == '1'
                    n = cred.endpoints.filter(status=True).count()
                    if n and not force:
                        res_json = [{
                            'error': True,
                            'confirm': True,
                            'count': n,
                            'message': f'{n} endpoint(s) usan esta credencial. ¿Eliminar de todas formas? Los endpoints quedarán sin auth y fallarán al llamar a la API.',
                        }]
                    else:
                        cred.status = False
                        cred.save(request)
                        log(f"Eliminó credencial API {cred}", request, "del", obj=cred.id)
                        res_json = {'error': False}

                elif action == 'fusionar_duplicados':
                    cred_fusionadas, ep_fusionados = _fusionar_duplicados(request)
                    log(
                        f"Fusionó duplicados: {cred_fusionadas} credenciales, {ep_fusionados} endpoints",
                        request, "change", obj=0,
                    )
                    messages.success(
                        request,
                        f'Duplicados fusionados: {cred_fusionadas} credencial(es) + {ep_fusionados} endpoint(s).',
                    )
                    res_json = {
                        'error': False,
                        'reload': True,
                        'cred_fusionadas': cred_fusionadas,
                        'ep_fusionados': ep_fusionados,
                    }

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

        elif action == 'nodos':
            try:
                pk = int(request.GET['id'])
                ep = model.objects.get(pk=pk)
                tipos = dict(OpcionDepartamentoChatBot.TIPOS_NODO)
                nodos = ep.nodos.filter(status=True).select_related('departamento').order_by(
                    'departamento__nombre', 'orden', 'id'
                )
                data_nodos = [{
                    'id': n.id,
                    'nombre': n.nombre,
                    'tipo': tipos.get(n.tipo_nodo, n.tipo_nodo),
                    'departamento': n.departamento.nombre if n.departamento_id else '—',
                    'departamento_id': n.departamento_id,
                } for n in nodos]
                return JsonResponse({
                    'result': True,
                    'endpoint': ep.nombre,
                    'nodos': data_nodos,
                })
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
