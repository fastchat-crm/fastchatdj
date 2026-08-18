"""CRUD genérico de registros — `/objetos/<slug>/`.

Una sola vista atiende todos los objetos personalizados: lee la metadata del
`ObjetoPersonalizado` y arma listado, formulario y detalle sobre la marcha. No
hay una vista por entidad, y por eso agregar un objeto nuevo no requiere código.
"""
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, paginador, secure_module

from .models import (
    TIPO_BOOLEANO,
    AsociacionRegistro,
    ObjetoPersonalizado,
    RegistroPersonalizado,
)
from .view_objetos import objetos_visibles


def _objeto_por_slug(request, slug):
    objeto = objetos_visibles(request).filter(slug=slug).first()
    if not objeto:
        raise Http404('El objeto no existe o no tenés acceso.')
    return objeto


def _registro(request, objeto, pk):
    return RegistroPersonalizado.objects.filter(pk=pk, objeto=objeto, status=True).first()


def _leer_datos_del_post(request, objeto):
    """Arma el dict de valores crudos leyendo un input por campo.

    Un checkbox ausente significa False y los de selección múltiple se leen con
    getlist; por eso no sirve un `request.POST.dict()` pelado.

    Solo se leen los campos que el formulario declaró en `__campos`. Sin ese
    marcador no se puede distinguir "el usuario vació el campo" de "el
    formulario no incluía el campo", y una edición parcial (por API, o un form
    recortado) borraba en silencio todo lo que no venía en el POST. Si el
    marcador no llega se asume el formulario completo, que es el comportamiento
    del alta.
    """
    declarados = (request.POST.get('__campos') or '').strip()
    permitidos = {c.strip() for c in declarados.split(',') if c.strip()} if declarados else None

    crudos = {}
    for campo in objeto.campos_activos():
        if permitidos is not None and campo.nombre not in permitidos:
            continue
        if campo.es_multivalor:
            crudos[campo.nombre] = request.POST.getlist(campo.nombre)
        elif campo.tipo == TIPO_BOOLEANO:
            crudos[campo.nombre] = request.POST.get(campo.nombre) in ('on', 'true', '1', 'True')
        else:
            crudos[campo.nombre] = request.POST.get(campo.nombre)
    return crudos


@login_required
@secure_module
def registrosView(request, slug):
    objeto = _objeto_por_slug(request, slug)

    if request.method == 'POST':
        return _procesar_accion(request, objeto)

    data = {
        'titulo': objeto.nombre_plural,
        'descripcion': objeto.descripcion or f'Registros de {objeto.nombre_plural.lower()}',
        'ruta': request.path,
    }
    addData(request, data)

    qs = RegistroPersonalizado.objects.filter(objeto=objeto, status=True)

    url_vars = ''
    criterio = (request.GET.get('criterio') or '').strip()
    if criterio:
        # Búsqueda sobre el JSONB completo: alcanza para un buscador general y
        # evita armar un OR por campo. El índice GIN cubre la contención, no el
        # icontains sobre el texto serializado, así que se acota con el filtro
        # por objeto que sí usa índice.
        qs = qs.extra(where=["datos::text ILIKE %s"], params=[f'%{criterio}%'])
        data['criterio'] = criterio
        url_vars += f'&criterio={quote(criterio)}'

    listado = qs.order_by('-id')
    data['objeto'] = objeto
    data['campos'] = list(objeto.campos_activos())
    data['columnas'] = list(objeto.campos_de_listado())
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    paginador(request, listado, 25, data, url_vars)
    return render(request, 'objetos/registros_listado.html', data)


def _procesar_accion(request, objeto):
    action = request.POST.get('action')
    try:
        with transaction.atomic():
            if action == 'add':
                return _guardar(request, objeto)
            if action == 'change':
                return _guardar(request, objeto, editar=True)
            if action == 'delete':
                return _borrar(request, objeto)
            if action == 'detalle':
                return _detalle(request, objeto)
            if action == 'asociar':
                return _asociar(request, objeto)
            if action == 'desasociar':
                return _desasociar(request, objeto)
    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error al procesar la solicitud: {ex}'})

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})


def _guardar(request, objeto, editar=False):
    crudos = _leer_datos_del_post(request, objeto)
    # Al editar solo se valida lo que vino: un campo obligatorio que el
    # formulario no incluyó ya tiene valor guardado y no hay por qué exigirlo
    # de nuevo. En el alta se exigen todos.
    limpios, errores = objeto.validar_datos(crudos, parcial=editar)

    if errores:
        return JsonResponse({
            'error': True,
            'message': 'Revisá los campos marcados.',
            'form': [errores],
        })

    if editar:
        registro = _registro(request, objeto, int(request.POST.get('pk') or 0))
        if not registro:
            return JsonResponse({'error': True, 'message': f'No se encontró el {objeto.nombre_singular.lower()}.'})
        # Merge en vez de reemplazo: si un campo se agregó después de crear el
        # registro, los valores viejos no se pierden.
        registro.datos = {**(registro.datos or {}), **limpios}
        registro.save(request)
        log(f'{objeto.nombre_singular} actualizado', request, 'change', obj=registro.id)
        return JsonResponse({'error': False, 'message': f'{objeto.nombre_singular} actualizado.', 'reload': True})

    registro = RegistroPersonalizado(objeto=objeto, datos=limpios)
    registro.save(request)
    log(f'{objeto.nombre_singular} creado', request, 'add', obj=registro.id)
    return JsonResponse({'error': False, 'message': f'{objeto.nombre_singular} creado.', 'reload': True})


def _borrar(request, objeto):
    registro = _registro(request, objeto, int(request.POST.get('pk') or 0))
    if not registro:
        return JsonResponse({'error': True, 'message': f'No se encontró el {objeto.nombre_singular.lower()}.'})
    registro.status = False
    registro.save(request)
    log(f'{objeto.nombre_singular} eliminado', request, 'delete', obj=registro.id)
    return JsonResponse({'error': False, 'message': f'{objeto.nombre_singular} eliminado.', 'reload': True})


def _detalle(request, objeto):
    registro = _registro(request, objeto, int(request.POST.get('pk') or 0))
    if not registro:
        return JsonResponse({'error': True, 'message': f'No se encontró el {objeto.nombre_singular.lower()}.'})

    valores = []
    for campo in objeto.campos_activos():
        valores.append({
            'nombre': campo.nombre,
            'etiqueta': campo.etiqueta,
            'tipo': campo.tipo,
            'valor': registro.datos.get(campo.nombre),
            'valor_texto': registro.valor_formateado(campo),
        })

    asociaciones = []
    for a in registro.asociaciones_salientes.filter(status=True).select_related('destino__objeto'):
        asociaciones.append({
            'id': a.id,
            'etiqueta': a.etiqueta or 'se relaciona con',
            'objeto': a.destino.objeto.nombre_singular,
            'registro': a.destino.etiqueta_visible(),
        })

    return JsonResponse({
        'error': False,
        'registro': {
            'id': registro.id,
            'titulo': registro.etiqueta_visible(),
            'valores': valores,
            'asociaciones': asociaciones,
        },
    })


def _asociar(request, objeto):
    origen = _registro(request, objeto, int(request.POST.get('pk') or 0))
    if not origen:
        return JsonResponse({'error': True, 'message': 'No se encontró el registro de origen.'})

    destino = RegistroPersonalizado.objects.filter(
        pk=int(request.POST.get('destino_id') or 0), status=True,
        objeto__in=objetos_visibles(request),
    ).first()
    if not destino:
        return JsonResponse({'error': True, 'message': 'No se encontró el registro de destino.'})
    if destino.id == origen.id:
        return JsonResponse({'error': True, 'message': 'Un registro no se puede asociar consigo mismo.'})

    etiqueta = (request.POST.get('etiqueta') or '').strip()
    _, creada = AsociacionRegistro.objects.get_or_create(
        origen=origen, destino=destino, etiqueta=etiqueta,
        defaults={'usuario_creacion': request.user},
    )
    if not creada:
        return JsonResponse({'error': True, 'message': 'Esa asociación ya existe.'})
    return JsonResponse({'error': False, 'message': 'Asociación creada.'})


def _desasociar(request, objeto):
    asociacion = AsociacionRegistro.objects.filter(
        pk=int(request.POST.get('pk') or 0), status=True,
        origen__objeto__in=objetos_visibles(request),
    ).first()
    if not asociacion:
        return JsonResponse({'error': True, 'message': 'No se encontró la asociación.'})
    asociacion.status = False
    asociacion.save(request)
    return JsonResponse({'error': False, 'message': 'Asociación eliminada.'})
