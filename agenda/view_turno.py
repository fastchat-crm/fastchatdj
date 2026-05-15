from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, paginador, secure_module

from .models import APPOINTMENT_STATUS_CHOICES, GrupoAgenda, Recurso, Turno


@login_required
@secure_module
def turnoView(request):
    grupos = GrupoAgenda.objects.filter(status=True).order_by('nombre')
    grupo_id = request.GET.get('grupo')
    grupo_actual = None
    if grupo_id:
        try:
            grupo_actual = grupos.get(pk=int(grupo_id))
        except (GrupoAgenda.DoesNotExist, ValueError):
            grupo_actual = None
    recursos = (Recurso.objects.filter(grupo_agenda=grupo_actual, status=True).order_by('orden', 'nombre')
                if grupo_actual else Recurso.objects.none())
    recurso_id = request.GET.get('recurso')
    recurso_actual = None
    if recurso_id:
        try:
            recurso_actual = recursos.get(pk=int(recurso_id))
        except (Recurso.DoesNotExist, ValueError):
            recurso_actual = None

    estado_filtro = (request.GET.get('estado') or '').strip()
    fecha_desde = (request.GET.get('desde') or '').strip()
    fecha_hasta = (request.GET.get('hasta') or '').strip()

    data = {
        'titulo': 'Appointments',
        'descripcion': 'Filterable list of all bookings.',
        'ruta': request.path,
        'grupos': grupos,
        'recursos': recursos,
        'grupo_actual': grupo_actual,
        'recurso_actual': recurso_actual,
        'estado_filtro': estado_filtro,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'status_choices': APPOINTMENT_STATUS_CHOICES,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'mark_status':
                    pk = int(request.POST['pk'])
                    nuevo = request.POST.get('estado')
                    if nuevo not in dict(APPOINTMENT_STATUS_CHOICES):
                        return JsonResponse({'error': True, 'message': 'Invalid status.'})
                    t = Turno.objects.get(pk=pk, status=True)
                    t.estado = nuevo
                    t.save(request=request)
                    log(f'Appointment {t.id} marked {nuevo}', request, 'change', obj=t.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    pk = int(request.POST['id'])
                    t = Turno.objects.get(pk=pk, status=True)
                    t.status = False
                    t.save(request=request)
                    log(f'Appointment {t.id} removed', request, 'del', obj=t.id)
                    return JsonResponse({'error': False})
        except Turno.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Appointment not found.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    qs = Turno.objects.filter(status=True).select_related(
        'recurso', 'recurso__grupo_agenda', 'servicio', 'contacto'
    )
    url_vars = ''
    if grupo_actual:
        qs = qs.filter(recurso__grupo_agenda=grupo_actual)
        url_vars += f'&grupo={grupo_actual.id}'
    if recurso_actual:
        qs = qs.filter(recurso=recurso_actual)
        url_vars += f'&recurso={recurso_actual.id}'
    if estado_filtro:
        qs = qs.filter(estado=estado_filtro)
        url_vars += f'&estado={estado_filtro}'
    if fecha_desde:
        try:
            d = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            qs = qs.filter(inicio__date__gte=d)
            url_vars += f'&desde={fecha_desde}'
        except ValueError:
            pass
    if fecha_hasta:
        try:
            d = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            qs = qs.filter(inicio__date__lte=d)
            url_vars += f'&hasta={fecha_hasta}'
        except ValueError:
            pass

    listado = qs.order_by('-inicio')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'agenda/turno/listado.html', data)
