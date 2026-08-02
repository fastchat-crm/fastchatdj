"""Diseñador de objetos personalizados — `/objetos/`.

Acá el usuario define sus entidades y campos. Los registros se cargan en
`/objetos/<slug>/` (ver `view_registros.py`).
"""
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, secure_module

from .models import (
    TIPO_CAMPO_CHOICES,
    TIPOS_CON_OPCIONES,
    CampoPersonalizado,
    ObjetoPersonalizado,
    normalizar_clave,
)


def objetos_visibles(request):
    qs = ObjetoPersonalizado.objects.filter(status=True)
    if not request.user.is_superuser:
        qs = qs.filter(usuario=request.user)
    return qs


def _objeto_del_usuario(request, pk):
    return objetos_visibles(request).filter(pk=pk).first()


def _slug_libre(base):
    """Slug único. Si "propiedad" ya existe prueba propiedad-2, -3, …"""
    slug = base or 'objeto'
    n = 1
    while ObjetoPersonalizado.objects.filter(slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    return slug


@login_required
@secure_module
def objetosView(request):
    if request.method == 'POST':
        return _procesar_accion(request)

    data = {
        'titulo': 'Objetos personalizados',
        'descripcion': 'Definí tus propias entidades sin tocar código',
        'ruta': request.path,
    }
    addData(request, data)

    objetos = list(objetos_visibles(request).order_by('nombre_plural'))
    for o in objetos:
        o.total_campos = o.campos_activos().count()
        o.total_registros = o.registros.filter(status=True).count()

    data['objetos'] = objetos
    data['tipos_campo'] = TIPO_CAMPO_CHOICES
    data['tipos_con_opciones'] = list(TIPOS_CON_OPCIONES)
    return render(request, 'objetos/listado.html', data)


def _procesar_accion(request):
    action = request.POST.get('action')
    try:
        with transaction.atomic():
            if action == 'add_objeto':
                return _guardar_objeto(request)
            if action == 'change_objeto':
                return _guardar_objeto(request, editar=True)
            if action == 'delete_objeto':
                return _borrar_objeto(request)
            if action == 'add_campo':
                return _guardar_campo(request)
            if action == 'change_campo':
                return _guardar_campo(request, editar=True)
            if action == 'delete_campo':
                return _borrar_campo(request)
            if action == 'listar_campos':
                return _listar_campos(request)
            if action == 'ordenar_campos':
                return _ordenar_campos(request)
    except ValidationError as ex:
        return JsonResponse({'error': True, 'message': '; '.join(
            f'{k}: {" ".join(v)}' for k, v in ex.message_dict.items()
        ) if hasattr(ex, 'message_dict') else str(ex)})
    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error al procesar la solicitud: {ex}'})

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})


def _guardar_objeto(request, editar=False):
    singular = (request.POST.get('nombre_singular') or '').strip()
    plural = (request.POST.get('nombre_plural') or '').strip()
    icono = (request.POST.get('icono') or '').strip() or 'fa fa-cube'
    descripcion = (request.POST.get('descripcion') or '').strip()

    if not singular or not plural:
        return JsonResponse({'error': True, 'message': 'El nombre en singular y en plural son obligatorios.'})

    if editar:
        objeto = _objeto_del_usuario(request, int(request.POST.get('pk') or 0))
        if not objeto:
            return JsonResponse({'error': True, 'message': 'No se encontró el objeto.'})
        objeto.nombre_singular = singular
        objeto.nombre_plural = plural
        objeto.icono = icono
        objeto.descripcion = descripcion
        objeto.save(request)
        log(f'Objeto personalizado actualizado: {plural}', request, 'change', obj=objeto.id)
        return JsonResponse({'error': False, 'message': 'Objeto actualizado.', 'reload': True})

    objeto = ObjetoPersonalizado(
        usuario=request.user,
        nombre_singular=singular,
        nombre_plural=plural,
        slug=_slug_libre(normalizar_clave(plural).replace('_', '-')),
        icono=icono,
        descripcion=descripcion,
    )
    objeto.save(request)
    log(f'Objeto personalizado creado: {plural}', request, 'add', obj=objeto.id)
    return JsonResponse({
        'error': False,
        'message': f'"{plural}" creado. Ahora agregale campos.',
        'objeto_id': objeto.id,
        'reload': True,
    })


def _borrar_objeto(request):
    objeto = _objeto_del_usuario(request, int(request.POST.get('pk') or 0))
    if not objeto:
        return JsonResponse({'error': True, 'message': 'No se encontró el objeto.'})
    # Soft-delete: los registros quedan en BD pero dejan de listarse.
    objeto.status = False
    objeto.save(request)
    log(f'Objeto personalizado eliminado: {objeto.nombre_plural}', request, 'delete', obj=objeto.id)
    return JsonResponse({'error': False, 'message': 'Objeto eliminado.', 'reload': True})


def _leer_opciones(request):
    """Las opciones llegan como texto multilínea, una por renglón."""
    crudo = (request.POST.get('opciones') or '').strip()
    if not crudo:
        return None
    return [linea.strip() for linea in crudo.splitlines() if linea.strip()]


def _guardar_campo(request, editar=False):
    objeto = _objeto_del_usuario(request, int(request.POST.get('objeto_id') or 0))
    if not objeto:
        return JsonResponse({'error': True, 'message': 'No se encontró el objeto.'})

    etiqueta = (request.POST.get('etiqueta') or '').strip()
    tipo = (request.POST.get('tipo') or '').strip()
    if not etiqueta:
        return JsonResponse({'error': True, 'message': 'La etiqueta del campo es obligatoria.'})
    if tipo not in dict(TIPO_CAMPO_CHOICES):
        return JsonResponse({'error': True, 'message': 'El tipo de dato no es válido.'})

    requerido = request.POST.get('requerido') in ('on', 'true', '1', 'True')
    mostrar = request.POST.get('mostrar_en_listado') in ('on', 'true', '1', 'True')
    ayuda = (request.POST.get('ayuda') or '').strip()
    opciones = _leer_opciones(request)

    if editar:
        campo = CampoPersonalizado.objects.filter(
            pk=int(request.POST.get('pk') or 0), objeto=objeto, status=True
        ).first()
        if not campo:
            return JsonResponse({'error': True, 'message': 'No se encontró el campo.'})
        # La clave interna NO se toca al editar: cambiarla dejaría huérfanos
        # todos los valores ya guardados en el JSONB de los registros.
        campo.etiqueta = etiqueta
        campo.tipo = tipo
        campo.requerido = requerido
        campo.mostrar_en_listado = mostrar
        campo.ayuda = ayuda
        campo.opciones = opciones
        campo.full_clean(exclude=['usuario_creacion', 'usuario_modificacion'])
        campo.save(request)
        return JsonResponse({'error': False, 'message': 'Campo actualizado.'})

    clave = normalizar_clave(etiqueta)
    if not clave:
        return JsonResponse({'error': True, 'message': 'La etiqueta no produce una clave válida. Usá letras.'})
    if CampoPersonalizado.objects.filter(objeto=objeto, nombre=clave, status=True).exists():
        return JsonResponse({'error': True, 'message': f'Ya existe un campo con la clave "{clave}".'})

    ultimo = objeto.campos_activos().order_by('-orden').first()
    campo = CampoPersonalizado(
        objeto=objeto,
        nombre=clave,
        etiqueta=etiqueta,
        tipo=tipo,
        requerido=requerido,
        mostrar_en_listado=mostrar,
        ayuda=ayuda,
        opciones=opciones,
        orden=(ultimo.orden + 1) if ultimo else 0,
    )
    campo.full_clean(exclude=['usuario_creacion', 'usuario_modificacion'])
    campo.save(request)
    return JsonResponse({'error': False, 'message': f'Campo "{etiqueta}" agregado.'})


def _borrar_campo(request):
    campo = CampoPersonalizado.objects.filter(
        pk=int(request.POST.get('pk') or 0), status=True,
        objeto__in=objetos_visibles(request),
    ).first()
    if not campo:
        return JsonResponse({'error': True, 'message': 'No se encontró el campo.'})
    campo.status = False
    campo.save(request)
    return JsonResponse({
        'error': False,
        'message': 'Campo eliminado. Los valores ya cargados quedan guardados por si lo restaurás.',
    })


def _serializar_campo(campo):
    return {
        'id': campo.id,
        'nombre': campo.nombre,
        'etiqueta': campo.etiqueta,
        'tipo': campo.tipo,
        'tipo_label': campo.get_tipo_display(),
        'requerido': campo.requerido,
        'mostrar_en_listado': campo.mostrar_en_listado,
        'ayuda': campo.ayuda,
        'opciones': '\n'.join(campo.lista_opciones()),
        'orden': campo.orden,
    }


def _listar_campos(request):
    objeto = _objeto_del_usuario(request, int(request.POST.get('objeto_id') or 0))
    if not objeto:
        return JsonResponse({'error': True, 'message': 'No se encontró el objeto.'})
    return JsonResponse({
        'error': False,
        'objeto': {
            'id': objeto.id,
            'nombre_singular': objeto.nombre_singular,
            'nombre_plural': objeto.nombre_plural,
            'slug': objeto.slug,
        },
        'campos': [_serializar_campo(c) for c in objeto.campos_activos()],
    })


def _ordenar_campos(request):
    objeto = _objeto_del_usuario(request, int(request.POST.get('objeto_id') or 0))
    if not objeto:
        return JsonResponse({'error': True, 'message': 'No se encontró el objeto.'})
    try:
        orden = json.loads(request.POST.get('orden') or '[]')
    except json.JSONDecodeError:
        return JsonResponse({'error': True, 'message': 'No se pudo leer el nuevo orden.'})

    for posicion, campo_id in enumerate(orden):
        CampoPersonalizado.objects.filter(pk=campo_id, objeto=objeto).update(orden=posicion)
    return JsonResponse({'error': False, 'message': 'Orden actualizado.'})
