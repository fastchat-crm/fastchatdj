import json
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template

from core.custom_models import FormError
from core.funciones import addData, paginador, salva_auditoria, secure_module, redirectAfterPostGet, log
from django.contrib import messages
from .forms import ParroquiaForm
from .models import Parroquia
from core.funciones_adicionales import salva_logs, customgetattr
import sys


@login_required
@secure_module
def parroquiaView(request):
    data = {'titulo': 'Parroquia',
            'modulo': 'Área Geográfica',
            'ruta': request.path,
            'fecha': str(date.today())
            }
    addData(request, data)
    model = Parroquia
    Formulario = ParroquiaForm
    nombre_para_audit = '__str__'
    titulo = data["titulo"]
    data["datos_popup"] = datos_popup = "datos_popup_id_parroquia"

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':

                        form = Formulario(request.POST,request=request)
                        if form.is_valid():
                            form.save()
                            log(f"Registro una nueva parroquia {form.instance.__str__()}", request, "add", obj=form.instance.id)
                            messages.success(request,
                                             "Registro Agreado")
                            res_json.append({'error': False,
                                             "to": redirectAfterPostGet(request)
                                             })
                        else:
                            raise FormError(form)

                elif action == 'change':

                        filtro = model.objects.get(pk=int(request.POST['pk']))

                        form = Formulario(request.POST, instance=filtro, request=request)
                        if form.is_valid() and filtro:
                            form.save()
                            log(f"Edito una parroquia {filtro.__str__()}", request, "change", obj=filtro.id)
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
                        log(f"Elimino una parroquia {filtro.__str__()}", request, "del", obj=filtro.id)
                        messages.success(request, f"Registro Eliminado")


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
                    return render(request, 'area_geografica/parroquia/form.html', data)

            elif action == 'change':

                    pk = int(request.GET['pk'])
                    instancia = model.objects.get(pk=pk)
                    data["pk"] = pk
                    data["form"] = Formulario(instance=instancia)
                    return render(request, 'area_geografica/parroquia/form.html', data)

            elif action == 'ver':

                    pk = int(request.GET['pk'])
                    instancia = model.objects.get(pk=pk)
                    data["pk"] = pk
                    data["form"] = Formulario(instance=instancia, ver=True)
                    return render(request, 'area_geografica/parroquia/form.html', data)

            elif action == datos_popup:
                ids = json.loads(request.GET['ids'])
                data["listado"] = listado = model.objects.filter(status=True).values('id', 'nombre')
                if listado.exclude(id__in=ids).exists():
                    data["ids"] = list(listado.exclude(id__in=ids).values_list('id', flat=True))
                    template = get_template(
                        "area_geografica/parroquia/select_option_parroquia.html")
                    json_content = template.render(data)
                    return JsonResponse({"result": True, 'data': json_content, 'nuevo_registro': True})
                else:
                    return JsonResponse({"result": True, 'nuevo_registro': False})

        criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True), ''
        if criterio:
            filtros = filtros & (Q(nombre__icontains=criterio) | Q(ciudad__nombre__icontains=criterio))
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio
        listado = model.objects.filter(filtros).filter(ciudad__provincia__pais__status=True)
        data["list_count"] = listado.count()
        data["url_vars"] = url_vars
        paginador(request, listado.order_by('nombre'), 10, data, url_vars)
        return render(request, 'area_geografica/parroquia/listado.html', data)
