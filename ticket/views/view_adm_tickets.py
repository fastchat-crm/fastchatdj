
from datetime import date, datetime
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
from ..funciones import es_lider_equipo, load_teams, load_ids_empresas, load_integrantes
from ..models import TicketAtencion, ProcesoAtencion


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
    model = TicketAtencion
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
                    equipo = TicketAtencion.objects.get(id=pk)
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
                    ticket = TicketAtencion.objects.get(id=pk)
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
                    ticket = TicketAtencion.objects.get(id=pk)
                    form = CambiarEstadoTicketForm(request.POST, request.FILES, instance=ticket)
                    if not form.is_valid():
                        raise FormError(form)
                    form.save(request=request)
                    log('Cambio de estado correctamente', request, 'edit')
                    res_json.append({'error': False,
                                     'message': 'Ticket creado correctamente',
                                     'reload': True
                                     })

                elif action == 'iniciarticket':
                    pk=int(request.POST['id'])
                    ticket = TicketAtencion.objects.get(id=pk)
                    ticket.finicioactividad=datetime.now()
                    ticket.estado=3
                    ticket.save(request)
                    messages.info(request, f'Se inicio correctamente el ticket: f{ticket.codigo}')
                    log('Ticket eliminado correctamente', request,  ticket)
                    return JsonResponse({'error': False})

                elif action == 'finalizarticket':
                    pk=int(request.POST['id'])
                    ticket = TicketAtencion.objects.get(id=pk)
                    ticket.ffinactividad=datetime.now()
                    ticket.estado=4
                    ticket.save(request)
                    messages.success(request, f'Se finalizo correctamente el ticket: f{ticket.codigo}')
                    log('Ticket eliminado correctamente', request,  ticket)
                    return JsonResponse({'error': False})

                elif action == 'delticket':
                    pk=int(request.POST['id'])
                    ticket = TicketAtencion.objects.get(id=pk)
                    ticket.status=False
                    ticket.save(request)
                    log('Ticket eliminado correctamente', request,  ticket)
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
                    ticket = TicketAtencion.objects.get(id=pk)
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
                    data['ticket'] = ticket = TicketAtencion.objects.get(id=pk)
                    form = AsignarTicketForm(initial=model_to_dict(ticket))
                    comentario = ticket.get_comentario_asignacion()
                    form.fields['mensaje'].initial = comentario.mensaje if comentario else 'Se asigna el ticket para su atención'
                    form.fields['proceso'].queryset = ProcesoAtencion.objects.filter(empresa=ticket.empresa, status=True)
                    if ticket.proceso:
                        usuarios_id = ticket.proceso.ids_integrantes()
                        form.fields['asignadoa'].queryset = Usuario.objects.filter(id__in=usuarios_id)
                    else:
                        form.fields['asignadoa'].queryset = Usuario.objects.none()
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
                    data['ticket'] = ticket = TicketAtencion.objects.get(id=pk)
                    titulo = f'Ticket | {ticket.codigo}'
                    template = get_template('ticket/forms/detalle_ticket.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'cambiarestado':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    data['ticket'] = ticket = TicketAtencion.objects.get(id=pk)
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
                    data['ticket'] = ticket = TicketAtencion.objects.get(id=pk)
                    data['comentarios'] = ticket.comentarios().order_by('-fecha_registro')
                    titulo = f'Comentarios de ticket | {ticket.codigo}'
                    template = get_template('ticket/forms/comments.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'loadusers':
                try:
                    proceso = ProcesoAtencion.objects.get(id=int(request.GET['id']))
                    return JsonResponse({'result': True, 'data': proceso.lista_integrantes()})
                except Exception as ex:
                    pass

        criterio, filtros, url_vars, documento = request.GET.get('criterio', ''), Q(status=True), '', request.GET.get('documento', '')
        estado = request.GET.get('estado', '')
        data['es_lider']= es_lider = es_lider_equipo(request.user)
        if es_lider:
            # equipos = load_teams(request.user).values_list('id', flat=True)
            empresas_id = load_ids_empresas(request.user)
            filtros &= Q(empresa_id__in=empresas_id)
            data['integrantes'] = load_integrantes(request.user)
            integrante = request.GET.get('integrante', '')
            if integrante:
                data['integrante'] = int(integrante)
                url_vars += f'&integrante={integrante}'
                filtros &= Q(asignadoa=integrante)
        else:
            filtros &= Q(asignadoa=request.user)

        if estado:
            data['estado'] = int(estado)
            url_vars += f'&estado={estado}'
            filtros &= Q(estado=estado)
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
        data['estados'] = model.ESTADO_TICKET
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'ticket/view_admin_tickets.html', data)
