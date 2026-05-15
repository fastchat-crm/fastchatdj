from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, paginador, secure_module

from .models import CURRENCY_CHOICES, GrupoAgenda


@login_required
@secure_module
def grupoAgendaView(request):
    data = {
        'titulo': 'Agenda groups',
        'descripcion': 'Top-level container that bundles resources, services and schedules.',
        'ruta': request.path,
        'currency_choices': CURRENCY_CHOICES,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add':
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'Name is required.'})
                    moneda = (request.POST.get('moneda') or 'USD').strip()
                    descripcion = (request.POST.get('descripcion') or '').strip()
                    zona = (request.POST.get('zona_horaria') or 'America/Guayaquil').strip()
                    horas = int(request.POST.get('recordatorio_horas_antes') or 24)
                    if GrupoAgenda.objects.filter(nombre__iexact=nombre, status=True).exists():
                        return JsonResponse({'error': True, 'message': 'A group with that name already exists.'})
                    grupo = GrupoAgenda(
                        nombre=nombre, moneda=moneda, descripcion=descripcion,
                        zona_horaria=zona, recordatorio_horas_antes=horas,
                    )
                    grupo.save(request=request)
                    log(f'Agenda group {grupo.nombre} created', request, 'add', obj=grupo.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    pk = int(request.POST['pk'])
                    grupo = GrupoAgenda.objects.get(pk=pk, status=True)
                    grupo.nombre = (request.POST.get('nombre') or grupo.nombre).strip()
                    grupo.moneda = (request.POST.get('moneda') or grupo.moneda).strip()
                    grupo.descripcion = (request.POST.get('descripcion') or '').strip()
                    grupo.zona_horaria = (request.POST.get('zona_horaria') or grupo.zona_horaria).strip()
                    grupo.recordatorio_horas_antes = int(
                        request.POST.get('recordatorio_horas_antes') or grupo.recordatorio_horas_antes
                    )
                    grupo.save(request=request)
                    log(f'Agenda group {grupo.nombre} updated', request, 'change', obj=grupo.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    pk = int(request.POST['id'])
                    grupo = GrupoAgenda.objects.get(pk=pk, status=True)
                    grupo.status = False
                    grupo.save(request=request)
                    log(f'Agenda group {grupo.nombre} deleted', request, 'del', obj=grupo.id)
                    return JsonResponse({'error': False})

        except GrupoAgenda.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Agenda group not found.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    criterio = (request.GET.get('criterio') or '').strip()
    qs = GrupoAgenda.objects.filter(status=True)
    url_vars = ''
    if criterio:
        qs = qs.filter(Q(nombre__icontains=criterio) | Q(descripcion__icontains=criterio))
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    listado = qs.annotate(
        recursos_count=models_count('recursos'),
        servicios_count=models_count('servicios'),
    ).order_by('nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'agenda/grupo/listado.html', data)


def models_count(rel):
    from django.db.models import Count, Q as _Q
    return Count(rel, filter=_Q(**{f'{rel}__status': True}))
