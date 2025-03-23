from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.forms import model_to_dict
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template

from area_geografica.models import Provincia, Ciudad, REGION_CHOICES
from core.custom_models import FormError
from core.funciones import addData, paginador, secure_module, log, generar_nombre, remover_caracteres_especiales_unicode
from seguridad.templatetags.templatefunctions import encrypt
from django.contrib import messages
from seguridad.models import Empresa
from seguridad.forms import EmpresaForm

@login_required
@secure_module
def empresaView(request):
    data = {
        'titulo': 'Empresa',
        'modulo': 'Seguridad',
        'ruta': request.path,
        'fecha': str(date.today())
    }
    addData(request, data)
    model = Empresa
    Formulario = EmpresaForm
    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':
                    form = Formulario(request.POST, request.FILES, request=request)
                    if form.is_valid():
                        if 'logo' in request.FILES:
                            file = request.FILES['logo']
                            nombredocumento = remover_caracteres_especiales_unicode(file._name)
                            file._name = generar_nombre(nombredocumento, file._name)
                            form.instance.logo = file
                        form.save()
                        log(f"Registro una empresa {form.instance.__str__()}", request, "add")
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise FormError(form)
                elif action == 'change':
                    filtro = model.objects.get(pk=int(request.POST['pk']))
                    form = Formulario(request.POST, request.FILES, request=request, instance=filtro)
                    if form.is_valid() and filtro:
                        if 'logo' in request.FILES:
                            file = request.FILES['logo']
                            nombredocumento = remover_caracteres_especiales_unicode(file._name)
                            file._name = generar_nombre(nombredocumento, file._name)
                            form.instance.logo = file
                        form.save()
                        log(f"Edito una empresa {form.instance.__str__()}", request, "change")
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise FormError(form)
                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    filtro.status = False
                    filtro.save(request)
                    log(f"Elimino una empresa {filtro.__str__()}", request, "delete")
                    messages.success(request, f"Registro Eliminado")
                    res_json = {"error": False}

        except ValueError as ex:
            res_json.append({'error': True, "message": str(ex)})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            res_json.append({'error': True, "message": f"Intente Nuevamente: {ex}"})
        return JsonResponse(res_json, safe=False)
    elif request.method == 'GET':
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'add':
                try:
                    form = Formulario()
                    data['form'] = form
                    template = get_template("seguridad/empresa/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    pass
            elif action == 'change':
                try:
                    data['id'] = id = int(request.GET['id'])
                    data['filtro'] = filtro = model.objects.get(pk=id)
                    form = Formulario(instance=filtro)
                    data['form'] = form
                    template = get_template("seguridad/empresa/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    pass
        id, criterio, filtros, url_vars = request.GET.get('id', '').strip(), request.GET.get('criterio', '').strip(), Q(
            status=True), ''
        if id:
            filtros = filtros & (Q(id=id))
            data["id"] = id
            url_vars += '&id=' + id
        if criterio:
            filtros = filtros & (Q(nombre__icontains=criterio))
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio

        listado = model.objects.filter(filtros)
        data["list_count"] = listado.count()
        data["url_vars"] = url_vars
        paginador(request, listado.order_by('-id'), 20, data, url_vars)
        return render(request, 'seguridad/empresa/listado.html', data)
