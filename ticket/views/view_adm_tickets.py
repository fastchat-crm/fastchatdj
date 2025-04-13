
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
from core.funciones import addData, paginador,log
from django.contrib import messages

from seguridad.templatetags.templatefunctions import encrypt
from ..forms import TicketForm, AsignarTicketForm, CambiarEstadoTicketForm
from ..models import Ticket, Proceso


@login_required
# @secure_module
def ticketAdminView(request):
    data = {
        'titulo': 'Gestionar Tickets de requerimientos',
        'descripcion': 'Asignar, editar y finalizar tickets de requerimientos',
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

                elif action == 'asignarticket':
                    pk=int(encrypt(request.POST['pk']))
                    ticket = Ticket.objects.get(id=pk)
                    form = AsignarTicketForm(request.POST, request.FILES,instance=ticket)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save(request=request)
                    log('Ticket modificado correctamente', request, 'edit')
                    res_json.append({'error': False,
                                     'message': 'Ticket creado correctamente',
                                     'reload': True
                                     })

                elif action == 'cambiarestado':
                    pk=int(encrypt(request.POST['pk']))
                    ticket = Ticket.objects.get(id=pk)
                    form = CambiarEstadoTicketForm(request.POST, request.FILES, instance=ticket)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save(request=request)
                    log('Cambio de estado correctamente', request, 'edit')
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

            elif action == 'asignarticket':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    data['ticket'] = ticket = Ticket.objects.get(id=pk)
                    form = AsignarTicketForm(initial=model_to_dict(ticket))
                    usuarios_id = ticket.proceso.ids_integrantes()
                    comentario = ticket.get_comentario_asignacion()
                    form.fields['mensaje'].initial = comentario.mensaje if comentario else 'Se asigna el ticket para su atención'
                    form.fields['proceso'].queryset = Proceso.objects.filter(empresa=ticket.empresa, status=True)
                    form.fields['asignadoa'].queryset = Usuario.objects.filter(id__in=usuarios_id)
                    data['form'] = form
                    data['seccionado'] = True

                    titulo = f'Asignar Ticket | {ticket.codigo}'
                    template = get_template('ticket/forms/form_asignar_ticket.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'detalleticket':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    data['ticket'] = ticket = Ticket.objects.get(id=pk)
                    titulo = f'Ticket | {ticket.codigo}'
                    template = get_template('ticket/forms/detalle_ticket.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'cambiarestado':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    data['ticket'] = ticket = Ticket.objects.get(id=pk)
                    titulo = f'Ticket | {ticket.codigo}'
                    form = CambiarEstadoTicketForm(initial=model_to_dict(ticket))
                    data['form'] = form
                    template = get_template('ajaxformmodal.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'comentarios':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    data['ticket'] = ticket = Ticket.objects.get(id=pk)
                    data['comentarios'] = ticket.comentarios().order_by('-fecha_registro')
                    titulo = f'Comentarios de ticket | {ticket.codigo}'
                    template = get_template('ticket/forms/comments.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

        criterio, filtros, url_vars, documento = request.GET.get('criterio', ''), Q(status=True), '', request.GET.get('documento', '')

        if documento:
            data['documento'] = documento
            url_vars += f'&documento={documento}'
            filtros = filtros & Q(usuario__documento=documento)
        if criterio:
            data['criterio'] = criterio
            url_vars += f'&criterio={criterio}'
            palabras = criterio.strip().split()
            q_obj = Q()

            if len(palabras) == 1:
                palabra = palabras[0]
                q_obj |= Q(usuario__first_name__icontains=palabra)
                q_obj |= Q(usuario__last_name__icontains=palabra)
                q_obj |= Q(usuario__username__icontains=palabra)
            elif 2 <= len(palabras) <= 4:
                # Generar todas las combinaciones posibles de los términos
                from itertools import permutations

                for combo in permutations(palabras, len(palabras)):
                    # Vamos alternando los campos entre first_name y last_name
                    sub_q = Q()
                    for i, palabra in enumerate(combo):
                        if i % 2 == 0:
                            sub_q &= Q(usuario__first_name__icontains=palabra)
                        else:
                            sub_q &= Q(usuario__last_name__icontains=palabra)
                    q_obj |= sub_q

            else:
                # Fallback: solo usar las 3 primeras para evitar combinaciones excesivas
                q_obj &= (Q(usuario__first_name__icontains=palabras[0]) &
                          Q(usuario__last_name__icontains=palabras[1]) &
                          Q(usuario__last_name__icontains=palabras[2]))
            palabras = criterio.strip()
            filtros &= q_obj | Q(codigo__icontains=palabras) | Q(numero_ticket__icontains=palabras) | Q(titulo__icontains=palabras)
        listado = model.objects.filter(filtros).order_by('-codigo').distinct()
        data["url_vars"] = url_vars
        data["list_count"] = listado.count()
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'ticket/view_admin_tickets.html', data)
