from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from autenticacion.models import Usuario
from core.funciones import addData, log, paginador, secure_module

from .models import GrupoAgenda, Recurso


@login_required
@secure_module
def recursoView(request):
    data = {
        'titulo': 'Resources',
        'descripcion': 'People, rooms or assets that can host appointments.',
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
    data['usuarios'] = Usuario.objects.filter(is_active=True).order_by('first_name', 'last_name')[:500]

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
                    color = (request.POST.get('color') or '#0d6efd').strip()
                    descripcion = (request.POST.get('descripcion') or '').strip()
                    usuario_id = request.POST.get('usuario') or None
                    siguiente_orden = Recurso.objects.filter(grupo_agenda=grupo, status=True).count()
                    rec = Recurso(
                        grupo_agenda=grupo, nombre=nombre, color=color,
                        descripcion=descripcion, orden=siguiente_orden,
                    )
                    if usuario_id:
                        rec.usuario_id = int(usuario_id)
                    rec.save(request=request)
                    log(f'Resource {rec.nombre} created', request, 'add', obj=rec.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    pk = int(request.POST['pk'])
                    rec = Recurso.objects.get(pk=pk, status=True)
                    rec.nombre = (request.POST.get('nombre') or rec.nombre).strip()
                    rec.color = (request.POST.get('color') or rec.color).strip()
                    rec.descripcion = (request.POST.get('descripcion') or '').strip()
                    usuario_id = request.POST.get('usuario') or None
                    rec.usuario_id = int(usuario_id) if usuario_id else None
                    rec.save(request=request)
                    log(f'Resource {rec.nombre} updated', request, 'change', obj=rec.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    pk = int(request.POST['id'])
                    rec = Recurso.objects.get(pk=pk, status=True)
                    rec.status = False
                    rec.save(request=request)
                    log(f'Resource {rec.nombre} deleted', request, 'del', obj=rec.id)
                    return JsonResponse({'error': False})

                if action == 'reorder':
                    ids = request.POST.getlist('ids[]') or request.POST.get('ids', '').split(',')
                    for pos, pk in enumerate(ids):
                        if not pk:
                            continue
                        Recurso.objects.filter(pk=int(pk), status=True).update(orden=pos)
                    return JsonResponse({'error': False})

        except GrupoAgenda.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Agenda group not found.'})
        except Recurso.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Resource not found.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    criterio = (request.GET.get('criterio') or '').strip()
    qs = Recurso.objects.filter(status=True).select_related('grupo_agenda', 'usuario')
    url_vars = ''
    if grupo_actual:
        qs = qs.filter(grupo_agenda=grupo_actual)
        url_vars += f'&grupo={grupo_actual.id}'
    if criterio:
        qs = qs.filter(Q(nombre__icontains=criterio) | Q(descripcion__icontains=criterio))
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    listado = qs.order_by('orden', 'nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    paginador(request, listado, 100, data, url_vars)
    return render(request, 'agenda/recurso/listado.html', data)
