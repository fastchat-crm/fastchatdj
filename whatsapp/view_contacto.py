import json
import sys
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from core.custom_models import FormError
from core.funciones import addData, paginador, secure_module, log
from seguridad.templatetags.templatefunctions import encrypt
from .forms import ContactoForm
from .models import Contacto
from django.contrib import messages


@login_required
@secure_module
def contactoView(request):
    data = {'titulo': 'Contacto',
            'modulo': 'Whatsapp',
            'ruta': request.path,
            'fecha': str(date.today())
            }
    model = Contacto
    Formulario = ContactoForm

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':
                    form = Formulario(request.POST, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Registro un contacto {form.instance.__str__()}", request, "add", obj=form.instance.id)
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise FormError(form)

                elif action == 'change':
                    filtro = model.objects.get(pk=int(encrypt(request.POST['pk'])))
                    form = Formulario(request.POST, instance=filtro, request=request)
                    if form.is_valid() and filtro:
                        form.save()
                        log(f"Edito un contacto  {form.instance.__str__()}", request, "change", obj=form.instance.id)
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise FormError(form)

                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    filtro.status = False
                    filtro.save(request)
                    log(f"Elimino un contacto {filtro.__str__()}", request, "del", obj=filtro.id)
                    messages.success(request, f"Registro Eliminado")
                    res_json={"error":False}

        except ValueError as ex:
            res_json.append({'error': True, "message": str(ex)})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            line = sys.exc_info()[-1].tb_lineno
            res_json.append({'error': True, "message": f"{ex} - Line {line}"})
        return JsonResponse(res_json, safe=False)

    elif request.method == 'GET':
        addData(request, data)
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'add':
                try:
                    data["form"] = Formulario()
                    template = get_template("whatsapp/contacto/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

            elif action == 'change':
                try:
                    pk = int(request.GET['id'])
                    filtro = model.objects.get(pk=pk)
                    data["filtro"] = filtro
                    data["pk"] = pk
                    data["form"] = Formulario(instance=filtro)
                    template = get_template("whatsapp/contacto/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

            elif action == 'ver':
                pk = int(request.GET['id'])
                filtro = model.objects.get(pk=pk)
                data["pk"] = pk
                data["form"] = Formulario(instance=filtro, ver=True)
                return render(request, 'whatsapp/contacto/form.html', data)


        criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True), ''
        id = request.GET.get('id', '')
        if criterio:
            filtros = filtros & (Q(contacto_nombre__icontains=criterio))
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio
        if id:
            filtros = filtros & (Q(id=id))
            data["id"] = id
            url_vars += '&id=' + id
        listado = model.objects.filter(filtros)
        data["list_count"] = listado.count()
        data["url_vars"] = url_vars
        paginador(request, listado.order_by('contacto_nombre'), 20, data, url_vars)
        return render(request, 'whatsapp/contacto/listado.html', data)
