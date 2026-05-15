from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_datetime

from core.funciones import addData, log, paginador, secure_module

from .models import (
    ACTIVE_STATUSES,
    APPOINTMENT_STATUS_CHOICES,
    GrupoAgenda,
    Recurso,
    Servicio,
    Turno,
)


STATUS_COLORS = {
    'pending': '#ffc107',
    'confirmed': '#0d6efd',
    'cancelled': '#6c757d',
    'rescheduled': '#fd7e14',
    'fulfilled': '#198754',
    'no_show': '#dc3545',
}

SECCIONES_CITAS = ('listado', 'calendario')
POST_ACTIONS = ('events', 'reschedule', 'create', 'mark_status', 'delete', 'cancel')


@login_required
@secure_module
def citasView(request):
    grupos = GrupoAgenda.objects.filter(status=True).order_by('nombre')

    grupo_id = request.GET.get('grupo') or request.POST.get('grupo_id')
    grupo_actual = None
    if grupo_id:
        try:
            grupo_actual = grupos.get(pk=int(grupo_id))
        except (GrupoAgenda.DoesNotExist, ValueError):
            grupo_actual = None

    recursos = (Recurso.objects.filter(grupo_agenda=grupo_actual, status=True).order_by('orden', 'nombre')
                if grupo_actual else Recurso.objects.none())
    servicios = (Servicio.objects.filter(grupo_agenda=grupo_actual, status=True).prefetch_related('recursos').order_by('orden', 'nombre')
                 if grupo_actual else Servicio.objects.none())

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
        'titulo': 'Citas',
        'modulo': 'Agenda',
        'ruta': request.path,
        'fecha': str(date.today()),
        'agenda_grupos': grupos,
        'grupo_actual': grupo_actual,
        'recursos': recursos,
        'recurso_actual': recurso_actual,
        'servicios': servicios,
        'estado_filtro': estado_filtro,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'status_choices': APPOINTMENT_STATUS_CHOICES,
    }
    addData(request, data)

    if request.method == 'POST':
        res_json = []
        action = request.POST.get('action', '')
        try:
            with transaction.atomic():
                if action == 'events':
                    desde = parse_datetime(request.POST.get('start') or '')
                    hasta = parse_datetime(request.POST.get('end') or '')
                    qs = Turno.objects.filter(status=True)
                    if grupo_actual:
                        qs = qs.filter(recurso__grupo_agenda=grupo_actual)
                    if recurso_actual:
                        qs = qs.filter(recurso=recurso_actual)
                    if desde and hasta:
                        qs = qs.filter(inicio__lt=hasta, fin__gt=desde)
                    items = []
                    for t in qs.select_related('recurso', 'servicio', 'contacto').order_by('inicio'):
                        contacto_name = t.contacto.contacto_nombre or t.contacto.contacto_numero
                        items.append({
                            'id': t.id,
                            'title': f'{contacto_name} · {t.servicio.nombre}',
                            'start': t.inicio.isoformat(),
                            'end': t.fin.isoformat(),
                            'backgroundColor': STATUS_COLORS.get(t.estado, '#0d6efd'),
                            'borderColor': t.recurso.color,
                            'extendedProps': {
                                'estado': t.estado,
                                'estado_label': t.get_estado_display(),
                                'servicio': t.servicio.nombre,
                                'recurso': t.recurso.nombre,
                                'contacto': contacto_name,
                                'precio': str(t.precio_cobrado),
                                'moneda': t.recurso.grupo_agenda.moneda,
                                'notas': t.notas or '',
                            },
                        })
                    return JsonResponse({'error': False, 'items': items})

                if action == 'reschedule':
                    pk = int(request.POST['pk'])
                    nuevo_inicio = parse_datetime(request.POST.get('inicio') or '')
                    nuevo_fin = parse_datetime(request.POST.get('fin') or '')
                    if not nuevo_inicio or not nuevo_fin:
                        return JsonResponse({'error': True, 'message': 'Rango de fecha inválido.'})
                    turno = Turno.objects.get(pk=pk, status=True)
                    if turno.estado not in ACTIVE_STATUSES:
                        return JsonResponse({'error': True, 'message': 'Solo se pueden reagendar turnos activos.'})
                    nuevo = Turno(
                        recurso=turno.recurso, servicio=turno.servicio, contacto=turno.contacto,
                        inicio=nuevo_inicio, fin=nuevo_fin,
                        precio_cobrado=turno.precio_cobrado,
                        estado='pending', origen='manual',
                        conversacion=turno.conversacion, notas=turno.notas,
                        turno_anterior=turno,
                    )
                    if nuevo.overlaps_existing():
                        return JsonResponse({'error': True, 'message': 'El nuevo horario se superpone con otro turno.'})
                    nuevo.save(request=request)
                    turno.estado = 'rescheduled'
                    turno.save(request=request)
                    log(f'Turno {turno.id} reagendado a {nuevo.id}', request, 'change', obj=nuevo.id)
                    return JsonResponse({'error': False, 'new_id': nuevo.id})

                if action == 'create':
                    rec_pk = int(request.POST['recurso'])
                    serv_pk = int(request.POST['servicio'])
                    contacto_pk = int(request.POST['contacto'])
                    inicio = parse_datetime(request.POST['inicio'])
                    rec = Recurso.objects.get(pk=rec_pk, status=True)
                    serv = Servicio.objects.get(pk=serv_pk, status=True)
                    if rec not in serv.recursos.all():
                        return JsonResponse({'error': True, 'message': 'El recurso no puede ofrecer este servicio.'})
                    fin = inicio + timedelta(minutes=serv.duracion_min)
                    turno = Turno(
                        recurso=rec, servicio=serv, contacto_id=contacto_pk,
                        inicio=inicio, fin=fin,
                        precio_cobrado=serv.precio,
                        estado='confirmed', origen='manual',
                        notas=(request.POST.get('notas') or '').strip(),
                    )
                    if turno.overlaps_existing():
                        return JsonResponse({'error': True, 'message': 'Ese horario ya está ocupado.'})
                    turno.save(request=request)
                    log(f'Turno {turno.id} creado (manual)', request, 'add', obj=turno.id)
                    return JsonResponse({'error': False, 'id': turno.id})

                if action == 'mark_status':
                    pk = int(request.POST['pk'])
                    nuevo = request.POST.get('estado')
                    if nuevo not in dict(APPOINTMENT_STATUS_CHOICES):
                        return JsonResponse({'error': True, 'message': 'Estado inválido.'})
                    t = Turno.objects.get(pk=pk, status=True)
                    t.estado = nuevo
                    t.save(request=request)
                    log(f'Turno {t.id} marcado como {nuevo}', request, 'change', obj=t.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    pk = int(request.POST['id'])
                    t = Turno.objects.get(pk=pk, status=True)
                    t.status = False
                    t.save(request=request)
                    log(f'Turno {t.id} eliminado', request, 'del', obj=t.id)
                    return JsonResponse({'error': False, 'reload': True})

                res_json.append({'error': True, 'message': 'Acción no reconocida.'})
        except (Recurso.DoesNotExist, Servicio.DoesNotExist):
            res_json.append({'error': True, 'message': 'Recurso o servicio no encontrado.'})
        except Turno.DoesNotExist:
            res_json.append({'error': True, 'message': 'Turno no encontrado.'})
        except Exception as ex:
            res_json.append({'error': True, 'message': f'Intente nuevamente: {ex}'})
        return JsonResponse(res_json, safe=False)

    action_param = (request.GET.get('action') or '').strip()
    seccion = action_param if action_param in SECCIONES_CITAS else 'listado'
    data['seccion'] = seccion

    qs_base = Turno.objects.filter(status=True).select_related(
        'recurso', 'recurso__grupo_agenda', 'servicio', 'contacto'
    )
    url_vars = f'&action={seccion}'
    if grupo_actual:
        qs_base = qs_base.filter(recurso__grupo_agenda=grupo_actual)
        url_vars += f'&grupo={grupo_actual.id}'
    if recurso_actual:
        qs_base = qs_base.filter(recurso=recurso_actual)
        url_vars += f'&recurso={recurso_actual.id}'
    if estado_filtro:
        qs_base = qs_base.filter(estado=estado_filtro)
        url_vars += f'&estado={estado_filtro}'
    if fecha_desde:
        try:
            d = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            qs_base = qs_base.filter(inicio__date__gte=d)
            url_vars += f'&desde={fecha_desde}'
        except ValueError:
            pass
    if fecha_hasta:
        try:
            d = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            qs_base = qs_base.filter(inicio__date__lte=d)
            url_vars += f'&hasta={fecha_hasta}'
        except ValueError:
            pass

    data['url_vars'] = url_vars
    data['count_total'] = qs_base.count()

    if seccion == 'listado':
        listado = qs_base.order_by('-inicio')
        data['list_count'] = listado.count()
        paginador(request, listado, 50, data, url_vars)

    return render(request, 'agenda/citas/listado.html', data)
