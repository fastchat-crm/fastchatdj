from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect

from core.custom_models import FormError
from core.funciones import addData, paginador, salva_auditoria, secure_module, redirectAfterPostGet, log
from .forms import PaisForm
from .models import Pais
from django.contrib import messages
from core.funciones_adicionales import salva_logs, customgetattr
import sys


@login_required
@secure_module
def paisView(request):
    data = {'titulo': 'Países',
            'modulo': 'Área Geográfica',
            'ruta': request.path,
            'fecha': str(date.today())
            }
    model = Pais
    Formulario = PaisForm

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':

                        form = Formulario(request.POST,request=request)
                        if form.is_valid():
                            form.save()
                            log(f"Registro un nuevo pais {form.instance.__str__()}", request, "add", obj=form.instance.id)
                            messages.success(request,
                                             "Registro Agreado")
                            res_json.append({'error': False,
                                             "to": redirectAfterPostGet(request)
                                             })
                        else:
                            raise FormError(form)

                elif action == 'change':

                        filtro = model.objects.get(pk=int(request.POST['pk']))
                        form = Formulario(request.POST, instance=filtro,request=request)
                        if form.is_valid() and filtro:
                            form.save()
                            log(f"Edito un pais {filtro.__str__()}", request, "change", obj=filtro.id)
                            messages.success(request,
                                             "Modificado con exito")
                            res_json.append({'error': False,
                                             "to": redirectAfterPostGet(request)
                                             })
                        else:
                            raise FormError(form)

                elif action == 'delete':

                        filtro = model.objects.get(pk=int(request.POST['id']))

                        filtro.status = False
                        filtro.save(request)
                        log(f"Elimino un pais {filtro.__str__()}", request, "del", obj=filtro.id)
                        messages.success(request, "Registro Eliminado")

                        res_json = {'error':False}
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
        addData(request, data)
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'add':

                    data["form"] = Formulario()
                    return render(request, 'area_geografica/pais/form.html', data)

            elif action == 'change':

                    pk = int(request.GET['pk'])
                    pais = model.objects.get(pk=pk)
                    data["pk"] = pk
                    data["form"] = Formulario(instance=pais)
                    return render(request, 'area_geografica/pais/form.html', data)

            elif action == 'ver':

                    pk = int(request.GET['pk'])
                    pais = model.objects.get(pk=pk)
                    data["pk"] = pk
                    data["form"] = Formulario(instance=pais, ver=True)
                    return render(request, 'area_geografica/pais/form.html', data)


        criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True), ''
        if criterio:
            filtros = filtros & Q(nombre__icontains=criterio)
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio
        listado = model.objects.filter(filtros)
        data["list_count"] = listado.count()
        data["url_vars"] = url_vars
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'area_geografica/pais/listado.html', data)
