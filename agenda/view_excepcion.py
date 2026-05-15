from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, paginador, secure_module

from .models import EXCEPTION_TYPE_CHOICES, ExcepcionAgenda, GrupoAgenda, Recurso


@login_required
@secure_module
def excepcionView(request):
    data = {
        'titulo': 'Schedule exceptions',
        'descripcion': 'Block days, block hour ranges or add extra hours for a resource.',
        'ruta': request.path,
        'tipos_excepcion': EXCEPTION_TYPE_CHOICES,
    }
    addData(request, data)

    grupos = GrupoAgenda.objects.filter(status=True).order_by('nombre')
    data['grupos'] = grupos

    recurso_id = request.GET.get('recurso') or request.POST.get('recurso_filtro')
    recurso_actual = None
    if recurso_id:
        try:
            recurso_actual = Recurso.objects.select_related('grupo_agenda').get(pk=int(recurso_id), status=True)
        except (Recurso.DoesNotExist, ValueError):
            recurso_actual = None
    data['recurso_actual'] = recurso_actual

    grupo_id = request.GET.get('grupo')
    grupo_actual = None
    if grupo_id:
        try:
            grupo_actual = grupos.get(pk=int(grupo_id))
        except (GrupoAgenda.DoesNotExist, ValueError):
            grupo_actual = None
    if recurso_actual:
        grupo_actual = recurso_actual.grupo_agenda
    data['grupo_actual'] = grupo_actual

    if grupo_actual:
        data['recursos_grupo'] = Recurso.objects.filter(grupo_agenda=grupo_actual, status=True).order_by('orden', 'nombre')
    else:
        data['recursos_grupo'] = Recurso.objects.filter(status=True).select_related('grupo_agenda').order_by('grupo_agenda', 'nombre')

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add':
                    rec_pk = int(request.POST.get('recurso') or 0)
                    rec = Recurso.objects.get(pk=rec_pk, status=True)
                    fecha = datetime.strptime(request.POST['fecha'], '%Y-%m-%d').date()
                    tipo = request.POST.get('tipo')
                    if tipo not in dict(EXCEPTION_TYPE_CHOICES):
                        return JsonResponse({'error': True, 'message': 'Invalid exception type.'})
                    hora_inicio = request.POST.get('hora_inicio') or None
                    hora_fin = request.POST.get('hora_fin') or None
                    if tipo in ('block_range', 'add_range'):
                        if not hora_inicio or not hora_fin:
                            return JsonResponse({'error': True, 'message': 'Hour range requires start and end.'})
                        if hora_inicio >= hora_fin:
                            return JsonResponse({'error': True, 'message': 'Start must be before end.'})
                    motivo = (request.POST.get('motivo') or '').strip()
                    ex = ExcepcionAgenda(
                        recurso=rec, fecha=fecha, tipo=tipo,
                        hora_inicio=hora_inicio if tipo != 'block_day' else None,
                        hora_fin=hora_fin if tipo != 'block_day' else None,
                        motivo=motivo,
                    )
                    ex.save(request=request)
                    log(f'Schedule exception {ex.id} created', request, 'add', obj=ex.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    pk = int(request.POST['pk'])
                    ex = ExcepcionAgenda.objects.get(pk=pk, status=True)
                    ex.fecha = datetime.strptime(request.POST['fecha'], '%Y-%m-%d').date()
                    ex.tipo = request.POST.get('tipo')
                    hora_inicio = request.POST.get('hora_inicio') or None
                    hora_fin = request.POST.get('hora_fin') or None
                    if ex.tipo in ('block_range', 'add_range'):
                        if not hora_inicio or not hora_fin:
                            return JsonResponse({'error': True, 'message': 'Hour range requires start and end.'})
                        if hora_inicio >= hora_fin:
                            return JsonResponse({'error': True, 'message': 'Start must be before end.'})
                    ex.hora_inicio = hora_inicio if ex.tipo != 'block_day' else None
                    ex.hora_fin = hora_fin if ex.tipo != 'block_day' else None
                    ex.motivo = (request.POST.get('motivo') or '').strip()
                    ex.save(request=request)
                    log(f'Schedule exception {ex.id} updated', request, 'change', obj=ex.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    pk = int(request.POST['id'])
                    ex = ExcepcionAgenda.objects.get(pk=pk, status=True)
                    ex.status = False
                    ex.save(request=request)
                    log(f'Schedule exception {ex.id} deleted', request, 'del', obj=ex.id)
                    return JsonResponse({'error': False})

        except Recurso.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Resource not found.'})
        except ExcepcionAgenda.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Exception not found.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    qs = ExcepcionAgenda.objects.filter(status=True).select_related('recurso', 'recurso__grupo_agenda')
    url_vars = ''
    if recurso_actual:
        qs = qs.filter(recurso=recurso_actual)
        url_vars += f'&recurso={recurso_actual.id}'
    elif grupo_actual:
        qs = qs.filter(recurso__grupo_agenda=grupo_actual)
        url_vars += f'&grupo={grupo_actual.id}'
    listado = qs.order_by('-fecha', 'recurso__nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    paginador(request, listado, 100, data, url_vars)
    return render(request, 'agenda/excepcion/listado.html', data)
