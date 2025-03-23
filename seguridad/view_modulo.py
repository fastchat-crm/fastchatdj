import sys
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect

from core.custom_models import FormError
from core.funciones import addData, paginador, salva_auditoria, secure_module, redirectAfterPostGet, log
from core.funciones_adicionales import ordenar_modulos_url, salva_logs
from seguridad.forms import ModuloForm
from seguridad.models import Modulo, ModuloGrupo
from django.contrib import messages


@login_required
@secure_module
def modulo(request):
    data = {
        'titulo': 'Url',
        'modulo': 'Url',
        'ruta': request.path,
        'fecha': str(date.today())
    }
    addData(request, data)
    model = Modulo
    Formulario = ModuloForm

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':

                    form = Formulario(request.POST, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Agrego modulo {form.instance.__str__()}", request, "add", obj=form.instance.id)

                        res_json.append({'error': False,
                                         "to": redirectAfterPostGet(request)
                                         })
                    else:
                        raise FormError(form)

                elif action == 'change':

                    modulo = model.objects.get(pk=int(request.POST['pk']))

                    form = Formulario(request.POST, instance=modulo, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Modifico modulo {form.instance.__str__()}", request, "change", obj=form.instance.id)

                        res_json.append({'error': False,
                                         "to": redirectAfterPostGet(request)
                                         })
                    else:
                        raise FormError(form)

                elif action == 'delete':

                    modulo = model.objects.get(pk=int(request.POST['id']))

                    modulo.status = False
                    modulo.save(request)
                    log(f"Elimino modulo {modulo.__str__()}", request, "del")

                    return redirect(redirectAfterPostGet(request))
        except ValueError as ex:
            res_json.append({'error': True,
                             "message": str(ex)
                             })
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            salva_logs(request, __file__, request.method,
                       action, type(ex).__name__,
                       'Error on line {}'.format(sys.exc_info()[-1].tb_lineno), ex)
            res_json.append({'error': True,
                             "message": "Intente Nuevamente"
                             })
        return JsonResponse(res_json, safe=False)
    elif request.method == 'GET':
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'add':

                data["form"] = Formulario()
                return render(request, 'seguridad/modulo/form.html', data)

            elif action == 'change':

                pk = int(request.GET['pk'])
                modulo = model.objects.get(pk=pk)
                data["pk"] = pk
                data["form"] = Formulario(instance=modulo)
                return render(request, 'seguridad/modulo/form.html', data)

            elif action == 'ver':

                pk = int(request.GET['pk'])
                modulo = model.objects.get(pk=pk)
                data["pk"] = pk
                data["form"] = Formulario(instance=modulo, ver=True)
                return render(request, 'seguridad/modulo/form.html', data)

        modulo_grupo, criterio, filtros, url_vars = [int(x) for x in
                                                     request.GET.getlist('modulo_grupo', [])], request.GET.get(
            'criterio', '').strip(), Q(status=True), ''
        if criterio:
            filtros = filtros & Q(nombre__icontains=criterio)
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio
        if modulo_grupo:
            filtros = filtros & Q(id__in=list(
                ModuloGrupo.objects.filter(pk__in=modulo_grupo, status=True).values_list('modulos__id',
                                                                                         flat=True).distinct()))
            data["modulo_grupo"] = modulo_grupo
            url_vars += '&' + '&'.join(["modulo_grupo=" + str(x) for x in modulo_grupo])
        modulos = model.objects.filter(filtros)
        data["list_modulo_grupo"] = list_modulo_grupo = ModuloGrupo.objects.filter(status=True)
        data["url_vars"] = url_vars
        ordenar_modulos_url(data, modulos)
        return render(request, 'seguridad/modulo/listado.html', data)
