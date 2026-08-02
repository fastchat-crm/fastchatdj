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
    CAMPOS_POR_EVENTO,
    ESTADO_CANCELADA,
    EVENTO_CHOICES,
    OPERADOR_CHOICES,
    UNIDAD_CHOICES,
    AccionAutomatizacion,
    Automatizacion,
    EjecucionAutomatizacion,
)

# Operadores que no llevan valor a comparar: preguntan por presencia.
OPERADORES_SIN_VALOR = ('existe', 'vacio')


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
    etiquetas_operador = dict(OPERADOR_CHOICES)
    for a in automatizaciones:
        a.pendientes = a.ejecuciones.filter(estado__in=['pendiente', 'esperando'], status=True).count()
        # Texto legible de las condiciones para mostrarlo en la tarjeta.
        a.condiciones_texto = [
            '{} {} {}'.format(
                c.get('campo', ''),
                etiquetas_operador.get(c.get('operador'), c.get('operador', '')),
                c.get('valor', ''),
            ).strip()
            for c in (a.condiciones or [])
        ]
        a.condiciones_json = json.dumps(a.condiciones or [])

    data['automatizaciones'] = automatizaciones
    data['eventos'] = EVENTO_CHOICES
    data['tipos_accion'] = ACCION_CHOICES
    data['unidades'] = UNIDAD_CHOICES
    data['operadores'] = OPERADOR_CHOICES
    data['operadores_sin_valor'] = list(OPERADORES_SIN_VALOR)
    data['campos_por_evento'] = json.dumps({
        evento: [{'campo': c, 'label': l} for c, l in campos]
        for evento, campos in CAMPOS_POR_EVENTO.items()
    })

    # Objetos personalizados con sus campos, para la acción «crear registro».
    from objetos.view_objetos import objetos_visibles
    data['objetos_custom'] = json.dumps([
        {
            'slug': o.slug,
            'nombre': o.nombre_singular,
            'campos': [
                {'nombre': c.nombre, 'etiqueta': c.etiqueta, 'requerido': c.requerido}
                for c in o.campos_activos()
            ],
        }
        for o in objetos_visibles(request).order_by('nombre_plural')
    ])
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
            if action == 'mover_accion':
                return _mover_accion(request)
            if action == 'cancelar_ejecucion':
                return _cancelar_ejecucion(request)
    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error al procesar la solicitud: {ex}'})

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})


def _leer_condiciones(request):
    """Normaliza las condiciones que manda el armador de la UI.

    Descarta las filas sin campo (el usuario agregó una y la dejó vacía) y las
    que necesitan un valor y no lo tienen — una condición `igual` sin valor
    compararía contra cadena vacía y filtraría todo en silencio.
    """
    crudo = (request.POST.get('condiciones') or '').strip()
    if not crudo:
        return None
    try:
        datos = json.loads(crudo)
    except json.JSONDecodeError:
        return None
    if not isinstance(datos, list):
        return None

    limpias = []
    for c in datos:
        if not isinstance(c, dict):
            continue
        campo = (c.get('campo') or '').strip()
        operador = (c.get('operador') or 'igual').strip()
        valor = c.get('valor')
        valor = '' if valor is None else str(valor).strip()
        if not campo:
            continue
        if operador not in dict(OPERADOR_CHOICES):
            continue
        if operador not in OPERADORES_SIN_VALOR and not valor:
            continue
        limpias.append({'campo': campo, 'operador': operador, 'valor': valor})
    return limpias or None


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


def _mover_accion(request):
    """Sube o baja un paso intercambiándolo con su vecino.

    Se reescriben los dos `orden` en vez de sumar o restar uno: los valores
    pueden tener huecos si se borraron pasos, y un `orden ± 1` los dejaría
    empatados o saltearía posiciones.
    """
    accion = AccionAutomatizacion.objects.filter(
        pk=int(request.POST.get('pk') or 0), status=True,
        automatizacion__in=automatizaciones_visibles(request),
    ).select_related('automatizacion').first()
    if not accion:
        return JsonResponse({'error': True, 'message': 'No se encontró la acción.'})

    direccion = (request.POST.get('direccion') or '').strip()
    if direccion not in ('subir', 'bajar'):
        return JsonResponse({'error': True, 'message': 'Dirección inválida.'})

    pasos = list(accion.automatizacion.acciones_activas())
    try:
        i = next(idx for idx, p in enumerate(pasos) if p.pk == accion.pk)
    except StopIteration:
        return JsonResponse({'error': True, 'message': 'No se encontró la acción en la lista.'})

    j = i - 1 if direccion == 'subir' else i + 1
    if j < 0 or j >= len(pasos):
        return JsonResponse({'error': False, 'message': 'La acción ya está en el extremo.'})

    pasos[i], pasos[j] = pasos[j], pasos[i]
    for posicion, paso in enumerate(pasos):
        if paso.orden != posicion:
            AccionAutomatizacion.objects.filter(pk=paso.pk).update(orden=posicion)

    return JsonResponse({'error': False, 'message': 'Orden actualizado.'})


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
