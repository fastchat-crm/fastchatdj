from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.forms import model_to_dict
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from autenticacion.models import Usuario
from core.custom_models import FormError
from core.funciones import addData, paginador,  log
from django.contrib import messages

from seguridad.templatetags.templatefunctions import encrypt
from ..forms import EquipoForm
from ..models import EquipoAtencion


@login_required
# @secure_module
def equipoView(request):
    data = {
        'titulo': 'Gestión de equipos de desarrollo',
        'descripcion': 'Crear, Editar y Eliminar Equipos de desarrollo',
        'modulo': 'Equipos',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    model = EquipoAtencion

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'addequipo':
                    form = EquipoForm(request.POST)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save()
                    log('Equipo creado correctamente', request, 'add')
                    res_json.append({'error': False,
                                     'message': 'Equipo creado correctamente',
                                     'reload': True
                                     })

                elif action == 'editequipo':
                    pk=int(encrypt(request.POST['pk']))
                    equipo = EquipoAtencion.objects.get(id=pk)
                    form = EquipoForm(request.POST, instance=equipo)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save()
                    log('Equipo modificado correctamente', request, equipo)
                    res_json.append({'error': False,
                                     'message': 'Equipo creado correctamente',
                                     'reload': True
                                     })

                elif action == 'delequipo':
                    pk=int(request.POST['id'])
                    equipo = EquipoAtencion.objects.get(id=pk)
                    equipo.status=False
                    equipo.save(request)
                    log('Equipo eliminado correctamente', request,  equipo)
                    return JsonResponse({'error': False})
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
            if action == 'addequipo':
                try:
                    form = EquipoForm()
                    form.fields['lider'].queryset = Usuario.objects.none()
                    form.fields['integrantes'].queryset = Usuario.objects.none()
                    data['form'] = form
                    titulo = 'Crear Equipo'
                    template = get_template('ticket/forms/form_equipo.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'editequipo':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    equipo = EquipoAtencion.objects.get(id=pk)
                    form = EquipoForm(initial=model_to_dict(equipo))
                    form.fields['lider'].queryset = Usuario.objects.filter(id=equipo.lider.id)
                    form.fields['integrantes'].queryset = Usuario.objects.filter(id__in=equipo.integrantes.all().values_list('id', flat=True))
                    data['form'] = form
                    titulo = f'Editar {equipo.nombre}'
                    template = get_template('ticket/forms/form_equipo.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')


        criterio, filtros, url_vars, documento = request.GET.get('criterio', ''), Q(status=True), '', request.GET.get('documento', '')

        if documento:
            data['documento'] = documento
            url_vars += f'&documento={documento}'
            filtros = filtros & Q(lider__documento=documento) | Q(integrantes__documento=documento)
        # Filtro por criterio (nombre, apellido, username)
        if criterio:
            data['criterio'] = criterio
            url_vars += f'&criterio={criterio}'
            palabras = criterio.strip().split()
            q_obj = Q()

            if len(palabras) == 1:
                palabra = palabras[0]
                q_obj |= Q(lider__first_name__icontains=palabra)
                q_obj |= Q(lider__last_name__icontains=palabra)
                q_obj |= Q(lider__username__icontains=palabra)
                q_obj |= Q(integrantes__first_name__icontains=palabra)
                q_obj |= Q(integrantes__last_name__icontains=palabra)
                q_obj |= Q(integrantes__username__icontains=palabra)
            elif 2 <= len(palabras) <= 4:
                # Generar todas las combinaciones posibles de los términos
                from itertools import permutations

                for combo in permutations(palabras, len(palabras)):
                    # Vamos alternando los campos entre first_name y last_name
                    sub_q = Q()
                    for i, palabra in enumerate(combo):
                        if i % 2 == 0:
                            sub_q &= Q(lider__first_name__icontains=palabra) | Q(integrantes__first_name__icontains=palabra)
                        else:
                            sub_q &= Q(lider__last_name__icontains=palabra) | Q(integrantes__last_name__icontains=palabra)
                    q_obj |= sub_q

            else:
                # Fallback: solo usar las 3 primeras para evitar combinaciones excesivas
                q_obj &= (Q(lider__first_name__icontains=palabras[0]) &
                          Q(lider__last_name__icontains=palabras[1]) &
                          Q(lider__last_name__icontains=palabras[2])) | \
                            (Q(integrantes__first_name__icontains=palabras[0]) &
                            Q(integrantes__last_name__icontains=palabras[1]) &
                            Q(integrantes__last_name__icontains=palabras[2]))

            filtros &= q_obj | Q(nombre__icontains=criterio)
        listado = model.objects.filter(filtros).order_by('id').distinct()
        data["url_vars"] = url_vars
        data["list_count"] = listado.count()
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'ticket/view_equipo.html', data)
