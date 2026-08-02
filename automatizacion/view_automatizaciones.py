"""Automatizaciones — `/automatizacion/`."""
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.funciones import addData, log, secure_module

from .models import (
    ACCION_CHOICES,
    ACCION_ESPERAR,
    ESTADO_CANCELADA,
    EVENTO_CHOICES,
    OPERADOR_CHOICES,
    UNIDAD_CHOICES,
    AccionAutomatizacion,
    Automatizacion,
    EjecucionAutomatizacion,
)


def automatizaciones_visibles(request):
    qs = Automatizacion.objects.filter(status=True)
    if not request.user.is_superuser:
        qs = qs.filter(usuario=request.user)
    return qs


def _automatizacion(request, pk):
    return automatizaciones_visibles(request).filter(pk=pk).first()


@login_required
@secure_module
def automatizacionesView(request):
    if request.method == 'POST':
        return _procesar_accion(request)

    data = {
        'titulo': 'Automatizaciones',
        'descripcion': 'Cuando pasa algo, hacé que el sistema reaccione solo',
        'ruta': request.path,
    }
    addData(request, data)

    automatizaciones = list(
        automatizaciones_visibles(request).prefetch_related('acciones').order_by('-activo', 'nombre')
    )
    for a in automatizaciones:
        a.pendientes = a.ejecuciones.filter(estado__in=['pendiente', 'esperando'], status=True).count()

    data['automatizaciones'] = automatizaciones
    data['eventos'] = EVENTO_CHOICES
    data['tipos_accion'] = ACCION_CHOICES
    data['unidades'] = UNIDAD_CHOICES
    data['operadores'] = OPERADOR_CHOICES
    data['ejecuciones'] = (
        EjecucionAutomatizacion.objects
        .filter(automatizacion__in=automatizaciones_visibles(request), status=True)
        .select_related('automatizacion').order_by('-id')[:25]
    )
    return render(request, 'automatizacion/listado.html', data)


def _procesar_accion(request):
    action = request.POST.get('action')
    try:
        with transaction.atomic():
            if action == 'add':
                return _guardar(request)
            if action == 'change':
                return _guardar(request, editar=True)
            if action == 'delete':
                return _borrar(request)
            if action == 'toggle':
                return _toggle(request)
            if action == 'listar_acciones':
                return _listar_acciones(request)
            if action == 'add_accion':
                return _guardar_accion(request)
            if action == 'delete_accion':
                return _borrar_accion(request)
            if action == 'cancelar_ejecucion':
                return _cancelar_ejecucion(request)
    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error al procesar la solicitud: {ex}'})

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})


def _leer_condiciones(request):
    crudo = (request.POST.get('condiciones') or '').strip()
    if not crudo:
        return None
    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError:
        return None
    return [c for c in datos if c.get('campo')] or None


def _guardar(request, editar=False):
    nombre = (request.POST.get('nombre') or '').strip()
    evento = (request.POST.get('evento') or '').strip()
    descripcion = (request.POST.get('descripcion') or '').strip()

    if not nombre:
        return JsonResponse({'error': True, 'message': 'El nombre es obligatorio.'})
    if evento not in dict(EVENTO_CHOICES):
        return JsonResponse({'error': True, 'message': 'Elegí un disparador válido.'})

    if editar:
        automatizacion = _automatizacion(request, int(request.POST.get('pk') or 0))
        if not automatizacion:
            return JsonResponse({'error': True, 'message': 'No se encontró la automatización.'})
    else:
        automatizacion = Automatizacion(usuario=request.user)

    automatizacion.nombre = nombre
    automatizacion.evento = evento
    automatizacion.descripcion = descripcion
    automatizacion.condiciones = _leer_condiciones(request)
    automatizacion.save(request)

    log(f'Automatización {"actualizada" if editar else "creada"}: {nombre}',
        request, 'change' if editar else 'add', obj=automatizacion.id)
    return JsonResponse({
        'error': False,
        'message': 'Automatización guardada. Agregale acciones para que haga algo.',
        'automatizacion_id': automatizacion.id,
        'reload': True,
    })


def _borrar(request):
    automatizacion = _automatizacion(request, int(request.POST.get('pk') or 0))
    if not automatizacion:
        return JsonResponse({'error': True, 'message': 'No se encontró la automatización.'})
    automatizacion.status = False
    automatizacion.save(request)
    return JsonResponse({'error': False, 'message': 'Automatización eliminada.', 'reload': True})


def _toggle(request):
    automatizacion = _automatizacion(request, int(request.POST.get('pk') or 0))
    if not automatizacion:
        return JsonResponse({'error': True, 'message': 'No se encontró la automatización.'})
    automatizacion.activo = not automatizacion.activo
    automatizacion.save(request)
    estado = 'activada' if automatizacion.activo else 'pausada'
    return JsonResponse({'error': False, 'message': f'Automatización {estado}.', 'reload': True})


def _serializar_accion(accion):
    return {
        'id': accion.id,
        'tipo': accion.tipo,
        'tipo_label': accion.get_tipo_display(),
        'resumen': accion.resumen(),
        'parametros': accion.parametros or {},
        'orden': accion.orden,
    }


def _listar_acciones(request):
    automatizacion = _automatizacion(request, int(request.POST.get('pk') or 0))
    if not automatizacion:
        return JsonResponse({'error': True, 'message': 'No se encontró la automatización.'})
    return JsonResponse({
        'error': False,
        'nombre': automatizacion.nombre,
        'acciones': [_serializar_accion(a) for a in automatizacion.acciones_activas()],
    })


def _guardar_accion(request):
    automatizacion = _automatizacion(request, int(request.POST.get('automatizacion_id') or 0))
    if not automatizacion:
        return JsonResponse({'error': True, 'message': 'No se encontró la automatización.'})

    tipo = (request.POST.get('tipo') or '').strip()
    if tipo not in dict(ACCION_CHOICES):
        return JsonResponse({'error': True, 'message': 'Elegí un tipo de acción válido.'})

    try:
        parametros = json.loads(request.POST.get('parametros') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': True, 'message': 'No se pudieron leer los parámetros de la acción.'})

    if tipo == ACCION_ESPERAR:
        try:
            cantidad = int(parametros.get('cantidad') or 0)
        except (TypeError, ValueError):
            cantidad = 0
        if cantidad <= 0:
            return JsonResponse({'error': True, 'message': 'La espera tiene que ser mayor a cero.'})

    ultima = automatizacion.acciones_activas().order_by('-orden').first()
    accion = AccionAutomatizacion(
        automatizacion=automatizacion,
        tipo=tipo,
        parametros=parametros,
        orden=(ultima.orden + 1) if ultima else 0,
    )
    accion.save(request)
    return JsonResponse({'error': False, 'message': 'Acción agregada.'})


def _borrar_accion(request):
    accion = AccionAutomatizacion.objects.filter(
        pk=int(request.POST.get('pk') or 0), status=True,
        automatizacion__in=automatizaciones_visibles(request),
    ).first()
    if not accion:
        return JsonResponse({'error': True, 'message': 'No se encontró la acción.'})
    accion.status = False
    accion.save(request)
    return JsonResponse({'error': False, 'message': 'Acción eliminada.'})


def _cancelar_ejecucion(request):
    ejecucion = EjecucionAutomatizacion.objects.filter(
        pk=int(request.POST.get('pk') or 0), status=True,
        automatizacion__in=automatizaciones_visibles(request),
    ).first()
    if not ejecucion:
        return JsonResponse({'error': True, 'message': 'No se encontró la ejecución.'})
    ejecucion.estado = ESTADO_CANCELADA
    ejecucion.save(request)
    return JsonResponse({'error': False, 'message': 'Ejecución cancelada.', 'reload': True})
