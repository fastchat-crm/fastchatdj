
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
from ..forms import TicketForm
from ..models import Ticket


@login_required
# @secure_module
def ticketView(request):
    data = {
        'titulo': 'Tickets de requerimientos',
        'descripcion': 'Crear, Editar y Eliminar tickets de requerimientos',
        'modulo': 'Tickets',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    model = Ticket
    Formulario = TicketForm

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'addticket':
                    form = Formulario(request.POST, request.FILES, data)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save(request=request)
                    log('Ticket creado correctamente', request, 'add')
                    res_json.append({'error': False,
                                     'message': 'Ticket creado correctamente',
                                     'reload': True
                                     })

                elif action == 'editticket':
                    pk=int(encrypt(request.POST['pk']))
                    equipo = Ticket.objects.get(id=pk)
                    form = Formulario(request.POST, request.FILES,data, instance=equipo)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save(request=request)
                    log('Ticket modificado correctamente', request, equipo)
                    res_json.append({'error': False,
                                     'message': 'Ticket creado correctamente',
                                     'reload': True
                                     })

                elif action == 'delticket':
                    pk=int(request.POST['id'])
                    equipo = Ticket.objects.get(id=pk)
                    equipo.status=False
                    equipo.save(request)
                    log('Ticket eliminado correctamente', request,  equipo)
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
            if action == 'addticket':
                try:
                    form = Formulario()
                    data['form'] = form
                    titulo = 'Crear Ticket'
                    template = get_template('ticket/forms/form_ticket.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'editticket':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    ticket = Ticket.objects.get(id=pk)
                    form = Formulario(initial=model_to_dict(ticket))
                    data['form'] = form
                    titulo = f'Editar {ticket.titulo}'
                    template = get_template('ticket/forms/form_ticket.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')


        criterio, filtros, url_vars, documento = request.GET.get('criterio', ''), Q(status=True, usuario=request.user), '', request.GET.get('documento', '')

        if documento:
            data['documento'] = documento
            url_vars += f'&documento={documento}'
            filtros = filtros & Q(usuario__documento=documento)
        if criterio:
            data['criterio'] = criterio
            url_vars += f'&criterio={criterio}'
            # palabras = criterio.strip().split()
            # q_obj = Q()
            #
            # if len(palabras) == 1:
            #     palabra = palabras[0]
            #     q_obj |= Q(usuario__first_name__icontains=palabra)
            #     q_obj |= Q(usuario__last_name__icontains=palabra)
            #     q_obj |= Q(usuario__username__icontains=palabra)
            # elif 2 <= len(palabras) <= 4:
            #     # Generar todas las combinaciones posibles de los términos
            #     from itertools import permutations
            #
            #     for combo in permutations(palabras, len(palabras)):
            #         # Vamos alternando los campos entre first_name y last_name
            #         sub_q = Q()
            #         for i, palabra in enumerate(combo):
            #             if i % 2 == 0:
            #                 sub_q &= Q(usuario__first_name__icontains=palabra)
            #             else:
            #                 sub_q &= Q(usuario__last_name__icontains=palabra)
            #         q_obj |= sub_q
            #
            # else:
            #     # Fallback: solo usar las 3 primeras para evitar combinaciones excesivas
            #     q_obj &= (Q(usuario__first_name__icontains=palabras[0]) &
            #               Q(usuario__last_name__icontains=palabras[1]) &
            #               Q(usuario__last_name__icontains=palabras[2]))
            palabras = criterio.strip()
            filtros &= Q(codigo__icontains=palabras) | Q(numero_ticket__icontains=palabras) | Q(titulo__icontains=palabras)
        listado = model.objects.filter(filtros).order_by('-codigo').distinct()
        data["url_vars"] = url_vars
        data["list_count"] = listado.count()
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'ticket/view_tickets.html', data)
