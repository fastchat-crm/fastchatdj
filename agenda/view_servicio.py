from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, paginador, secure_module

from .models import GrupoAgenda, Recurso, Servicio


@login_required
@secure_module
def servicioView(request):
    data = {
        'titulo': 'Services',
        'descripcion': 'Bookable services with price and duration.',
        'ruta': request.path,
    }
    addData(request, data)

    grupos = GrupoAgenda.objects.filter(status=True).order_by('nombre')
    data['grupos'] = grupos

    grupo_id = request.GET.get('grupo') or request.POST.get('grupo_filtro')
    grupo_actual = None
    if grupo_id:
        try:
            grupo_actual = grupos.get(pk=int(grupo_id))
        except (GrupoAgenda.DoesNotExist, ValueError):
            grupo_actual = None
    data['grupo_actual'] = grupo_actual
    data['recursos_grupo'] = (
        Recurso.objects.filter(grupo_agenda=grupo_actual, status=True).order_by('orden', 'nombre')
        if grupo_actual else Recurso.objects.none()
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add':
                    grupo_pk = int(request.POST.get('grupo_agenda') or 0)
                    grupo = GrupoAgenda.objects.get(pk=grupo_pk, status=True)
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'Name is required.'})
                    descripcion = (request.POST.get('descripcion') or '').strip()
                    duracion = int(request.POST.get('duracion_min') or 30)
                    if duracion < 5:
                        return JsonResponse({'error': True, 'message': 'Duration must be at least 5 minutes.'})
                    try:
                        precio = Decimal(request.POST.get('precio') or '0')
                    except InvalidOperation:
                        return JsonResponse({'error': True, 'message': 'Invalid price.'})
                    if precio < 0:
                        return JsonResponse({'error': True, 'message': 'Price cannot be negative.'})
                    siguiente_orden = Servicio.objects.filter(grupo_agenda=grupo, status=True).count()
                    serv = Servicio(
                        grupo_agenda=grupo, nombre=nombre, descripcion=descripcion,
                        duracion_min=duracion, precio=precio, orden=siguiente_orden,
                    )
                    serv.save(request=request)
                    recursos_ids = request.POST.getlist('recursos[]') or request.POST.getlist('recursos')
                    if recursos_ids:
                        serv.recursos.set(
                            Recurso.objects.filter(pk__in=recursos_ids, grupo_agenda=grupo, status=True)
                        )
                    log(f'Service {serv.nombre} created', request, 'add', obj=serv.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    pk = int(request.POST['pk'])
                    serv = Servicio.objects.get(pk=pk, status=True)
                    serv.nombre = (request.POST.get('nombre') or serv.nombre).strip()
                    serv.descripcion = (request.POST.get('descripcion') or '').strip()
                    serv.duracion_min = int(request.POST.get('duracion_min') or serv.duracion_min)
                    try:
                        serv.precio = Decimal(request.POST.get('precio') or str(serv.precio))
                    except InvalidOperation:
                        return JsonResponse({'error': True, 'message': 'Invalid price.'})
                    serv.save(request=request)
                    recursos_ids = request.POST.getlist('recursos[]') or request.POST.getlist('recursos')
                    serv.recursos.set(
                        Recurso.objects.filter(pk__in=recursos_ids, grupo_agenda=serv.grupo_agenda, status=True)
                    )
                    log(f'Service {serv.nombre} updated', request, 'change', obj=serv.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    pk = int(request.POST['id'])
                    serv = Servicio.objects.get(pk=pk, status=True)
                    serv.status = False
                    serv.save(request=request)
                    log(f'Service {serv.nombre} deleted', request, 'del', obj=serv.id)
                    return JsonResponse({'error': False})

                if action == 'reorder':
                    ids = request.POST.getlist('ids[]') or request.POST.get('ids', '').split(',')
                    for pos, pk in enumerate(ids):
                        if not pk:
                            continue
                        Servicio.objects.filter(pk=int(pk), status=True).update(orden=pos)
                    return JsonResponse({'error': False})

                if action == 'recursos_grupo':
                    grupo_pk = int(request.POST.get('grupo_id') or 0)
                    items = list(
                        Recurso.objects.filter(grupo_agenda_id=grupo_pk, status=True)
                        .order_by('orden', 'nombre').values('id', 'nombre', 'color')
                    )
                    return JsonResponse({'error': False, 'items': items})

        except GrupoAgenda.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Agenda group not found.'})
        except Servicio.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Service not found.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    criterio = (request.GET.get('criterio') or '').strip()
    qs = Servicio.objects.filter(status=True).select_related('grupo_agenda').prefetch_related('recursos')
    url_vars = ''
    if grupo_actual:
        qs = qs.filter(grupo_agenda=grupo_actual)
        url_vars += f'&grupo={grupo_actual.id}'
    if criterio:
        qs = qs.filter(Q(nombre__icontains=criterio) | Q(descripcion__icontains=criterio))
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    listado = qs.order_by('grupo_agenda', 'orden', 'nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    paginador(request, listado, 100, data, url_vars)
    return render(request, 'agenda/servicio/listado.html', data)
