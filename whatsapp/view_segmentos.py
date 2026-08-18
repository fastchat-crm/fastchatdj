"""Segmentos guardados — CRUD del filtro reutilizable de contactos + preview."""
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, paginador, secure_module, log
from .funciones_segmentos import queryset_segmento, validar_condiciones
from .models import CampoPersonalizadoContacto, EtiquetaContacto, SegmentoContacto


def _leer_condiciones(request):
    try:
        cond = json.loads(request.POST.get('condiciones_json') or '{}')
    except ValueError:
        raise ValueError('Formato de condiciones inválido.')
    ok, msg = validar_condiciones(cond)
    if not ok:
        raise ValueError(msg)
    return cond


@login_required
@secure_module
def segmentosView(request):
    data = {
        'titulo': 'Segmentos',
        'descripcion': 'Filtros guardados de contactos para campañas y secuencias',
        'ruta': request.path,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add':
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'Nombre obligatorio.'})
                    segmento = SegmentoContacto.objects.create(
                        nombre=nombre,
                        descripcion=(request.POST.get('descripcion') or '').strip(),
                        condiciones=_leer_condiciones(request),
                    )
                    log(f'Segmento {segmento.nombre} creado', request, 'add', obj=segmento.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    segmento = SegmentoContacto.objects.get(pk=int(request.POST['pk']), status=True)
                    segmento.nombre = (request.POST.get('nombre') or segmento.nombre).strip()
                    segmento.descripcion = (request.POST.get('descripcion') or '').strip()
                    segmento.condiciones = _leer_condiciones(request)
                    segmento.save()
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    segmento = SegmentoContacto.objects.get(pk=int(request.POST['id']), status=True)
                    segmento.status = False
                    segmento.save()
                    return JsonResponse({'error': False})

                if action == 'preview':
                    cond = _leer_condiciones(request)
                    temporal = SegmentoContacto(condiciones=cond)
                    qs = queryset_segmento(temporal)
                    muestra = [{
                        'nombre': c.contacto_nombre or '(sin nombre)',
                        'numero': c.contacto_numero,
                    } for c in qs.select_related('sesion')[:10]]
                    return JsonResponse({'error': False, 'total': qs.count(), 'muestra': muestra})

        except SegmentoContacto.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Segmento no encontrado.'})
        except ValueError as ex:
            return JsonResponse({'error': True, 'message': str(ex)})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    if request.GET.get('action') == 'condiciones':
        segmento = SegmentoContacto.objects.get(pk=int(request.GET['id']), status=True)
        return JsonResponse({'error': False, 'condiciones': segmento.condiciones or {}})

    criterio = (request.GET.get('criterio') or '').strip()
    qs = SegmentoContacto.objects.filter(status=True)
    url_vars = ''
    if criterio:
        qs = qs.filter(Q(nombre__icontains=criterio) | Q(descripcion__icontains=criterio))
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    listado = list(qs.order_by('nombre'))
    for s in listado:
        try:
            s.total_contactos = queryset_segmento(s).count()
        except Exception:
            s.total_contactos = '—'
    data['list_count'] = len(listado)
    data['url_vars'] = url_vars
    data['etiquetas_disponibles'] = EtiquetaContacto.objects.filter(
        status=True, usuario_creacion=request.user,
    ).order_by('nombre')
    data['campos_disponibles'] = CampoPersonalizadoContacto.objects.filter(
        status=True,
    ).order_by('orden', 'nombre')
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'whatsapp/segmentos/listado.html', data)
