import json
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.forms import model_to_dict
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import get_template


from core.custom_models import FormError
from core.funciones import addData, paginador, log, secure_module, generar_nombre
from django.contrib import messages

from seguridad.models import Empresa
from seguridad.templatetags.templatefunctions import encrypt
from ..forms import TicketForm
from ..models import TicketAtencion, ProcesoAtencion, DetalleArchivoTicketAtencion


@login_required
# @secure_module
def ticketView(request):
    data = {
        'titulo': 'Administración de requerimientos',
        'descripcion': 'Crear, Editar y Eliminar tickets de requerimientos',
        'modulo': 'Tickets',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    model = TicketAtencion
    Formulario = TicketForm
    empresa = request.user.mi_empresa()
    data['PUEDE_VER'] = True
    if not request.user.is_superuser and not empresa:
        # messages.error(request, "No se encuentra registrado en ninguna empresa")
        # return HttpResponseRedirect('/panel/')
        data['PUEDE_VER'] = False
        return render(request, 'ticket/view_tickets.html', data)
    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'addticket':
                    form = Formulario(request.POST, request.FILES)
                    if not form.is_valid():
                        raise FormError(form)

                    ticket = form.save(request=request)

                    documentos = request.FILES.getlist('archivo')
                    lista_items1 = json.loads(request.POST['lista_items1'])
                    for d in documentos:
                        items = [item for item in lista_items1 if item.get('archivo') == d._name]

                        if not items:
                            raise ValueError(f"No se encontró metadata para el archivo: {d._name}")

                        # Accede al nombre usando .get() para manejar casos donde la clave no existe
                        nombre_archivo = items[0].get('nombre', 'sin_nombre')  # Valor por defecto si 'nombre' no existe

                        if d.size > 4194304:
                            raise NameError(f"El archivo es mayor a 4 Mb. Nombre: {nombre_archivo}")

                        d._name = generar_nombre(f"file_{nombre_archivo}_", d._name)
                        doc = DetalleArchivoTicketAtencion(ticket=ticket, archivo=d)
                        doc.save(request)

                    log('Ticket creado correctamente', request, 'add')
                    res_json.append({'error': False, 'message': 'Ticket creado correctamente', 'reload': True})

                elif action == 'editticket':
                    pk=int(encrypt(request.POST['pk']))
                    ticket = TicketAtencion.objects.get(id=pk)
                    form = Formulario(request.POST, request.FILES,data, instance=ticket)
                    if not form.is_valid():
                        raise FormError(form)

                    documentos = request.FILES.getlist('archivo')
                    lista_items1 = json.loads(request.POST.get('lista_items1', '[]'))

                    # Diccionario para búsqueda rápida
                    items_by_archivo = {item['archivo']: item for item in lista_items1 if 'archivo' in item}

                    # Identificar archivos a mantener (actualizar o conservar)
                    ids_to_keep = [int(item['id_archivo']) for item in lista_items1
                                   if 'id_archivo' in item and item['id_archivo'] and item['id_archivo'].isdigit()]

                    # Marcar como inactivos los archivos no incluidos
                    DetalleArchivoTicketAtencion.objects.filter(ticket=ticket).exclude(
                        id__in=ids_to_keep
                    ).update(status=False)

                    # Procesar archivos nuevos y actualizaciones
                    for d in documentos:
                        item = items_by_archivo.get(d._name)

                        if not item:
                            raise ValueError(f"No se encontraron metadatos para: {d._name}")

                        nombre_archivo = 'evidencia'

                        if d.size > 4194304:
                            raise ValueError(f"Archivo '{nombre_archivo}' excede 4MB")

                        d._name = generar_nombre(f"file_{nombre_archivo}_", d._name)

                        if 'id_archivo' in item and item['id_archivo']:
                            # Actualizar archivo existente
                            DetalleArchivoTicketAtencion.objects.filter(
                                id=item['id_archivo'],
                                ticket=ticket
                            ).update(
                                archivo=d,
                                status=True
                            )
                        else:
                            # Crear nuevo registro
                            DetalleArchivoTicketAtencion.objects.create(
                                ticket=ticket,
                                archivo=d,
                            )

                    # Actualizar descripciones de archivos existentes (sin cambiar el archivo)
                    for item in lista_items1:
                        if item.get('id_archivo') and not item.get('archivo'):
                            DetalleArchivoTicketAtencion.objects.filter(
                                id=item['id_archivo'],
                                ticket=ticket
                            ).update(
                                status=True
                            )

                    form.save(request=request)
                    log('Ticket modificado correctamente', request, ticket)
                    res_json.append({'error': False,
                                     'message': 'Ticket creado correctamente',
                                     'reload': True
                                     })

                elif action == 'delticket':
                    pk=int(request.POST['id'])
                    equipo = TicketAtencion.objects.get(id=pk)
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
                    form.fields['proceso'].queryset = ProcesoAtencion.objects.none()
                    if not request.user.is_superuser :
                        form.fields['empresa'].queryset = Empresa.objects.filter(id=empresa.id)
                        form.fields['empresa'].initial = empresa
                        form.fields['empresa'].disabled = True
                        form.fields['proceso'].queryset = ProcesoAtencion.objects.filter(empresa=empresa, status=True, activo=True)

                    data['form'] = form
                    titulo = 'Crear Ticket'
                    template = get_template('ticket/forms/form_add.html')
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    messages.error(request, f'Error: {ex}')

            elif action == 'editticket':
                try:
                    data['pk'] = pk = int(request.GET['pk'])
                    data['filtro'] = ticket = TicketAtencion.objects.get(id=pk)
                    form = Formulario(initial=model_to_dict(ticket))
                    if not request.user.is_superuser:
                        form.fields['empresa'].queryset = Empresa.objects.filter(id=empresa.id)
                        form.fields['empresa'].initial = empresa
                        form.fields['empresa'].disabled = True
                    form.fields['proceso'].queryset = ProcesoAtencion.objects.filter(empresa=ticket.empresa, status=True, activo=True)
                    data['archivos_precargar'] = list(ticket.detallearchivoticketatencion_set.all())
                    data['form'] = form
                    titulo = f'Editar {ticket.titulo}'
                    template = get_template('ticket/forms/form_add.html')
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

            elif action == 'loadprocesos':
                try:
                    empresa = Empresa.objects.get(id=int(request.GET['id']))
                    lista = []
                    for p in ProcesoAtencion.objects.filter(empresa=empresa, status=True, activo=True):
                        lista.append({'value': p.id, 'text': p.descripcion})
                    return JsonResponse({'result': True, 'data': lista})
                except Exception as ex:
                    pass

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
