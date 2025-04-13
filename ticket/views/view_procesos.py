
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.forms import model_to_dict
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template


from core.custom_models import FormError
from core.funciones import addData, paginador,log
from django.contrib import messages

from seguridad.templatetags.templatefunctions import encrypt
from ..forms import ProcesoForm
from ..models import Proceso


@login_required
# @secure_module
def procesoView(request):
    data = {
        'titulo': 'Gestión de Procesos de Desarrollo',
        'descripcion': 'Crear, Editar y Eliminar procesos de desarrollo',
        'modulo': 'Procesos',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    model = Proceso
    Formulario = ProcesoForm

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'addproceso':
                    form = Formulario(request.POST)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save()
                    log('Proceso creado correctamente', request, 'add')
                    res_json.append({'error': False,
                                     'message': 'Equipo creado correctamente',
                                     'reload': True
                                     })

                elif action == 'editproceso':
                    pk=int(encrypt(request.POST['pk']))
                    equipo = Proceso.objects.get(id=pk)
                    form = Formulario(request.POST, instance=equipo)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save()
                    log('Proceso modificado correctamente', request, equipo)
                    res_json.append({'error': False,
                                     'message': 'Equipo creado correctamente',
                                     'reload': True
                                     })

                elif action == 'delproceso':
                    pk=int(request.POST['id'])
                    equipo = Proceso.objects.get(id=pk)
                    equipo.status=False
                    equipo.save(request)
                    log('Proceso eliminado correctamente', request,  equipo)
                    return JsonResponse({'error': False})
                else:
                    res_json.append({'error': True, "message": 'Acción no encontrada',})
        except ValueError as ex:
            res_json.append({'error': True,
                             "message": str(ex)
                             })
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            res_json.append({'error': True,
                             "message": f"Intente Nuevamente {ex}"
                             })
        return JsonResponse(res_json, safe=False)
    elif request.method == 'GET':
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'addproceso':
                try:
                    form = Formulario()
                    data['form'] = form
                    titulo = 'Crear Proceso'
                    template = get_template('ajaxformmodal.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'editproceso':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    proceso = Proceso.objects.get(id=pk)
                    form = Formulario(initial=model_to_dict(proceso))
                    data['form'] = form
                    titulo = f'Editar {proceso.descripcion}'
                    template = get_template('ajaxformmodal.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')


        criterio, filtros, url_vars, documento = request.GET.get('criterio', ''), Q(status=True), '', request.GET.get('documento', '')

        if documento:
            data['documento'] = documento
            url_vars += f'&documento={documento}'
            filtros = filtros & Q(equipos__lider__documento=documento) | Q(equipos__integrantes__documento=documento)
        if criterio:
            data['criterio'] = criterio
            url_vars += f'&criterio={criterio}'
            palabras = criterio.strip().split()
            q_obj = Q()

            if len(palabras) == 1:
                palabra = palabras[0]
                q_obj |= Q(equipos__lider__first_name__icontains=palabra)
                q_obj |= Q(equipos__lider__last_name__icontains=palabra)
                q_obj |= Q(equipos__lider__username__icontains=palabra)
                q_obj |= Q(equipos__integrantes__first_name__icontains=palabra)
                q_obj |= Q(equipos__integrantes__last_name__icontains=palabra)
                q_obj |= Q(equipos__integrantes__username__icontains=palabra)
            elif 2 <= len(palabras) <= 4:
                # Generar todas las combinaciones posibles de los términos
                from itertools import permutations

                for combo in permutations(palabras, len(palabras)):
                    # Vamos alternando los campos entre first_name y last_name
                    sub_q = Q()
                    for i, palabra in enumerate(combo):
                        if i % 2 == 0:
                            sub_q &= Q(equipos__lider__first_name__icontains=palabra) | Q(
                                equipos__integrantes__first_name__icontains=palabra)
                        else:
                            sub_q &= Q(equipos__lider__last_name__icontains=palabra) | Q(
                                equipos__integrantes__last_name__icontains=palabra)
                    q_obj |= sub_q

            else:
                # Fallback: solo usar las 3 primeras para evitar combinaciones excesivas
                q_obj &= (Q(equipos__lider__first_name__icontains=palabras[0]) &
                          Q(equipos__lider__last_name__icontains=palabras[1]) &
                          Q(equipos__lider__last_name__icontains=palabras[2])) | \
                         (Q(equipos__integrantes__first_name__icontains=palabras[0]) &
                          Q(equipos__integrantes__last_name__icontains=palabras[1]) &
                          Q(equipos__integrantes__last_name__icontains=palabras[2]))
            filtros &= q_obj | Q(descripcion__icontains=criterio) | Q(empresa__nombre__icontains=criterio)
        listado = model.objects.filter(filtros).order_by('id').distinct()
        data["url_vars"] = url_vars
        data["list_count"] = listado.count()
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'ticket/view_procesos.html', data)
