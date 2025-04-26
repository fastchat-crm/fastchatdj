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
from core.funciones import addData, paginador, log
from django.contrib import messages

from seguridad.models import Empresa
from seguridad.templatetags.templatefunctions import encrypt
from ..forms import TicketForm, AsignarTicketForm, CambiarEstadoTicketForm
from ..funciones import es_lider_equipo, load_teams, load_ids_empresas, load_integrantes
from ..models import TicketAtencion, ProcesoAtencion


@login_required
# @secure_module
def ticketIntegranteView(request):
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

                if action == 'iniciarticket':
                    pk = int(request.POST['id'])
                    ticket = TicketAtencion.objects.get(id=pk)
                    ticket.finicioactividad = datetime.now()
                    ticket.estado = 3
                    ticket.save(request)
                    messages.info(request, f'Se inicio correctamente el ticket: f{ticket.codigo}')
                    log('Ticket eliminado correctamente', request, ticket)
                    return JsonResponse({'error': False})

                elif action == 'finalizarticket':
                    pk = int(request.POST['id'])
                    ticket = TicketAtencion.objects.get(id=pk)
                    ticket.ffinactividad = datetime.now()
                    ticket.estado = 4
                    ticket.save(request)
                    messages.success(request, f'Se finalizo correctamente el ticket: f{ticket.codigo}')
                    log('Ticket eliminado correctamente', request, ticket)
                    return JsonResponse({'error': False})

                if action == 'do':
                    try:
                        idactividad = request.POST['idactividad']
                        actividad = TicketAtencion.objects.get(pk=idactividad)
                        actividad.estado = 2
                        actividad.ffinactividad = None
                        actividad.save(request)
                        log(u'Puso en pendiente una actividad: %s' % actividad, request, "edit")
                        qsincidencia = TicketAtencion.objects.values('id').filter(status=True, asignadoa=request.user)
                        res_json = {"resp": True, 'totdo': len(qsincidencia.filter(estado=2)),
                                    'totprogress': len(qsincidencia.filter(estado=3)),
                                    'totdone': len(qsincidencia.filter(estado=4)[:10])}
                    except Exception as ex:
                        res_json = {'resp': False, "message": "Error: {}".format(ex)}
                    return JsonResponse(res_json, safe=False)

                if action == 'progress':
                    try:
                        idactividad = request.POST['idactividad']
                        actividad = TicketAtencion.objects.get(pk=idactividad)
                        actividad.estado = 3
                        actividad.ffinactividad = None
                        actividad.save(request)
                        log(u'Puso en marcha una incidencia: %s' % actividad, request, "change")
                        qsincidencia = TicketAtencion.objects.values('id').filter(status=True, asignadoa=request.user)
                        res_json = {"resp": True, 'totdo': len(qsincidencia.filter(estado=2)),
                                    'totprogress': len(qsincidencia.filter(estado=3)),
                                    'totdone': len(qsincidencia.filter(estado=4)[:10])}
                    except Exception as ex:
                        res_json = {'resp': False, "message": "Error: {}".format(ex)}
                    return JsonResponse(res_json, safe=False)

                if action == 'done':
                    try:
                        idactividad = request.POST['idactividad']
                        actividad = TicketAtencion.objects.get(pk=idactividad)
                        actividad.estado = 4
                        actividad.ffinactividad = datetime.now()
                        actividad.save(request)

                        log(u'Finalizo un ticket: %s' % actividad, request, "edit")
                        qsincidencia = TicketAtencion.objects.values('id').filter(status=True, asignadoa=request.user)
                        res_json = {"resp": True, 'totdo': len(qsincidencia.filter(estado=2)),
                                    'totprogress': len(qsincidencia.filter(estado=3)),
                                    'totdone': len(qsincidencia.filter(estado=4)[:10])}
                    except Exception as ex:
                        res_json = {'resp': False, "message": "Error: {}".format(ex)}
                    return JsonResponse(res_json, safe=False)

                else:
                    res_json.append({'error': True, "message": 'Acción no encontrada', })
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
            if action == 'detalleticket':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    data['ticket'] = ticket = TicketAtencion.objects.get(id=pk)
                    titulo = f'Ticket | {ticket.codigo}'
                    template = get_template('ticket/forms/detalle_ticket.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')
        criterio, filtros, url_vars, documento = request.GET.get('s', ''), Q(status=True, asignadoa=request.user), '', request.GET.get(
            'documento', '')
        estado = request.GET.get('estado', '')

        if estado:
            data['estado'] = int(estado)
            url_vars += f'&estado={estado}'
            filtros &= Q(estado=estado)
        if documento:
            data['documento'] = documento
            url_vars += f'&documento={documento}'
            filtros = filtros & Q(usuario__documento=documento)
        if criterio:
            data['s'] = criterio
            url_vars += f'&s={criterio}'
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
            filtros &= q_obj | Q(codigo__icontains=palabras) | Q(numero_ticket__icontains=palabras) | Q(
                titulo__icontains=palabras)
        listado = model.objects.filter(filtros).order_by('-codigo').distinct()
        data['tickets_pendientes'] = listado.filter(estado=2)
        data['tickets_enproceso'] = listado.filter(estado=3)
        data['tickets_finalizadas'] = listado.filter(estado=4)
        data["url_vars"] = url_vars
        data["list_count"] = len(listado)
        data['estados'] = model.ESTADO_TICKET
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'ticket/view_mis_tickets.html', data)
