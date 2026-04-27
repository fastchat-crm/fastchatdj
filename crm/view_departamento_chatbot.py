import json
import sys
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template

from autenticacion.models import Usuario
from core.custom_models import FormError
from core.funciones import addData, paginador, salva_auditoria, secure_module, redirectAfterPostGet, log
from core.funciones_adicionales import salva_logs, customgetattr
from .forms import IndustriaForm, ActividadEconomicaForm, DepartamentoChatBotForm, AddPerfilDepartamentoChatBotForm
from .models import Industria, ActividadEconomica, DepartamentoChatBot, OpcionDepartamentoChatBot, \
    PerfilDepartamentoChatBot, EndpointApiChatbot
from django.contrib import messages


@login_required
@secure_module
def departamentoChatbotsView(request):
    data = {'titulo': 'Departamentos & Chatbots',
            'descripcion': 'Gestión de departamentos, preguntas y respuestas rapidas para el chatbot',
            'modulo': 'CRM',
            'ruta': request.path,
            'fecha': str(date.today())
            }
    model = DepartamentoChatBot
    Formulario = DepartamentoChatBotForm

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                # Cuando el form vino del render full-page, redirige al listado
                # despues de guardar; si vino del modal, sigue con reload.
                redirect_to = (request.POST.get('redirect_to') or '').strip()
                ok_response = (
                    {'error': False, 'to': redirect_to}
                    if redirect_to else
                    {'error': False, 'reload': True}
                )
                if action == 'add':
                    form = Formulario(request.POST, request=request)
                    if form.is_valid():
                        form.save()
                        opciones_json = json.loads(request.POST.get('arbol_json'))
                        if opciones_json:
                            sincronizar_opciones(form.instance, opciones_json)
                        log(f"Registro un departamento {form.instance.__str__()}", request, "add", obj=form.instance.id)
                        res_json.append(ok_response)
                    else:
                        raise FormError(form)
                elif action == 'change':
                        filtro = model.objects.get(pk=int(request.POST['pk']))
                        form = Formulario(request.POST, instance=filtro, request=request)
                        if form.is_valid() and filtro:
                            form.save()
                            try:
                                opciones_json = json.loads(request.POST.get('arbol_json', '[]'))
                            except json.JSONDecodeError:
                                raise Exception("El formato de las opciones es inválido.")

                            ids_existentes = list(filtro.opciondepartamentochatbot_set.filter(status=True).values_list('id', flat=True))

                            ids_actualizados = sincronizar_opciones(filtro, opciones_json)

                            ids_eliminados = set(ids_existentes) - set(ids_actualizados)
                            if ids_eliminados:
                                OpcionDepartamentoChatBot.objects.filter(id__in=ids_eliminados).update(status=False)

                            log(f"Editó un departamento {form.instance}", request, "change", obj=form.instance.id)
                            res_json.append(ok_response)
                        else:
                            raise FormError(form)
                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    filtro.status = False
                    filtro.save(request)
                    PerfilDepartamentoChatBot.objects.filter(status=True, departamento=filtro).update(status=False)
                    OpcionDepartamentoChatBot.objects.filter(status=True, departamento=filtro).update(status=False)
                    log(f"Elimino un departamento {filtro.__str__()}", request, "del", obj=filtro.id)
                    messages.success(request, f"Registro Eliminado")
                    res_json={"error":False}
                elif action == 'guardar_usuarios':
                    try:
                        pk = int(request.POST['pk'])
                        filtro = model.objects.get(pk=pk)
                        ids_usuarios = json.loads(request.POST.get('usuarios', '[]'))
                        usuarios_creados = []
                        for uid in ids_usuarios:
                            usuario = Usuario.objects.get(pk=uid)
                            ya_existe = PerfilDepartamentoChatBot.objects.filter(departamento=filtro, usuario=usuario,status=True).exists()

                            if not ya_existe:
                                relacion = PerfilDepartamentoChatBot.objects.create(departamento=filtro,usuario=usuario)

                                usuarios_creados.append({
                                    "id": usuario.id,
                                    "id_relacion": relacion.id,
                                    "nombre": usuario.full_name(),
                                    "documento": usuario.documento,
                                    "email": usuario.email,
                                    "telcelular": usuario.telcelular,
                                    "foto": usuario.foto.url if usuario.foto else ""
                                })
                        return JsonResponse({'result': True, 'usuarios': usuarios_creados})
                    except Exception as ex:
                        return JsonResponse({'result': False, 'message': str(ex)})
                elif action == 'eliminar_usuario':
                    filtro = PerfilDepartamentoChatBot.objects.get(pk=int(request.POST['id']))
                    filtro.status = False
                    filtro.save(request)
                    log(f"Elimino un usuario del departamento {filtro.__str__()}", request, "del", obj=filtro.id)
                    res_json={"error":False}
                elif action == 'generar_con_ia':
                    return _generar_departamento_con_ia(request)
                elif action == 'guardar_meta':
                    return _guardar_meta(request)
                elif action == 'guardar_opcion':
                    return _guardar_opcion(request)
                elif action == 'eliminar_opcion':
                    return _eliminar_opcion(request)
                elif action == 'mover_opcion':
                    return _mover_opcion(request)
        except ValueError as ex:
            res_json.append({'error': True, "message": str(ex)})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            line = sys.exc_info()[-1].tb_lineno
            res_json.append({'error': True, "message": f"{ex} - Line {line}"})
        return JsonResponse(res_json, safe=False)

    elif request.method == 'GET':
        addData(request, data)
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            # full=1 → render full page (extends base.html); modo legacy = JSON modal.
            full_page = request.GET.get('full') == '1'

            if action == 'add':
                try:
                    data["form"] = Formulario()
                    data["endpoints_json"] = json.dumps(list(
                        EndpointApiChatbot.objects.filter(status=True).order_by('nombre')
                        .values('id', 'nombre', 'base_url')
                    ))
                    if full_page:
                        data.update({
                            'pagina_completa': True,
                            'titulo_pagina': f'Agregar {data["titulo"]}',
                            'ruta_post': request.path,
                            'filtro': None,
                        })
                        return render(request, 'crm/departamento_chatbots/form_pagina.html', data)
                    template = get_template("crm/departamento_chatbots/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

            elif action == 'change':
                try:
                    pk = int(request.GET['id'])
                    filtro = model.objects.get(pk=pk)
                    data["filtro"] = filtro
                    data["form"] = Formulario(instance=filtro)
                    data["opciones_json"] = json.dumps(filtro.obtener_arbol_opciones())
                    data["endpoints_json"] = json.dumps(list(
                        EndpointApiChatbot.objects.filter(status=True).order_by('nombre')
                        .values('id', 'nombre', 'base_url')
                    ))
                    if full_page:
                        data.update({
                            'pagina_completa': True,
                            'titulo_pagina': f'Editar {filtro}',
                            'ruta_post': request.path,
                            'arbol_plano': _serializar_arbol_opciones(filtro),
                            'tipos_nodo_choices': OpcionDepartamentoChatBot.TIPOS_NODO,
                            'validaciones_choices': OpcionDepartamentoChatBot.VALIDACIONES,
                            'endpoints_disponibles': EndpointApiChatbot.objects.filter(status=True).order_by('nombre'),
                        })
                        return render(request, 'crm/departamento_chatbots/form_pagina.html', data)
                    template = get_template("crm/departamento_chatbots/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

            elif action == 'editar_opcion':
                # Devuelve HTML del form de un nodo (modal en form_pagina).
                try:
                    op_id = int(request.GET.get('id') or 0)
                    parent_id = int(request.GET.get('parent_id') or 0)
                    dep_id = int(request.GET.get('departamento_id') or 0)
                    contexto = {
                        'tipos_nodo_choices': OpcionDepartamentoChatBot.TIPOS_NODO,
                        'validaciones_choices': OpcionDepartamentoChatBot.VALIDACIONES,
                        'endpoints_disponibles': EndpointApiChatbot.objects.filter(status=True).order_by('nombre'),
                    }
                    if op_id:
                        opcion = OpcionDepartamentoChatBot.objects.filter(pk=op_id, status=True).first()
                        if not opcion:
                            return JsonResponse({'result': False, 'message': 'Nodo no encontrado'})
                        contexto.update({
                            'opcion': opcion,
                            'es_nuevo': False,
                            'departamento_id': opcion.departamento_id,
                            'parent_id': opcion.opcion_padre_id or 0,
                            'config_json_str': json.dumps(opcion.config or {}, indent=2, ensure_ascii=False),
                        })
                    else:
                        contexto.update({
                            'opcion': None,
                            'es_nuevo': True,
                            'departamento_id': dep_id,
                            'parent_id': parent_id,
                            'config_json_str': '{}',
                        })
                    template = get_template('crm/departamento_chatbots/_form_opcion.html')
                    return JsonResponse({'result': True, 'data': template.render(contexto)})
                except Exception as ex:
                    return JsonResponse({'result': False, 'message': str(ex)})

            elif action == 'ver':
                pk = int(request.GET['id'])
                filtro = model.objects.get(pk=pk)
                data["pk"] = pk
                data["form"] = Formulario(instance=filtro, ver=True)
                return render(request, 'crm/departamento_chatbots/form.html', data)

            elif action == 'addUsers':
                try:
                    pk = int(request.GET['id'])
                    filtro = model.objects.get(pk=pk)
                    data["filtro"] = filtro
                    data["form"] = form = AddPerfilDepartamentoChatBotForm()
                    form.fields['usuarios'].queryset = Usuario.objects.none()
                    template = get_template("crm/departamento_chatbots/form_usuarios.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})
            
            elif action == 'buscarpersonas':
                try:
                    q = request.GET['q'].upper().strip()
                    qspersona = Usuario.objects.filter(status=True).order_by('last_name')
                    s = q.split(" ")
                    if len(s) == 1:
                        qspersona = qspersona.filter((Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(documento__icontains=q)), Q(status=True)).distinct()[:15]
                    elif len(s) == 2:
                        qspersona = qspersona.filter((Q(last_name__contains=s[0])) |
                                                     (Q(first_name__icontains=s[0]) & Q(
                                                         first_name__icontains=s[1])) |
                                                     (Q(first_name__icontains=s[0]) & Q(
                                                         last_name__contains=s[1]))).filter(
                            status=True).distinct()[:15]
                    else:
                        qspersona = qspersona.filter(
                            (Q(first_name__contains=s[0]) & Q(last_name__contains=s[1])) |
                            (Q(first_name__contains=s[0]) & Q(first_name__contains=s[1]))).filter(
                            status=True).distinct()[:15]
                    data = {
                        "result": "ok",
                        "results": [
                            {
                                "id": x.pk,
                                "documento": f"{x.documento if x.documento else 'Sin documento'}",
                                "text": x.full_name(),
                                "foto": x.get_foto_gris()
                            } for x in qspersona
                        ]
                    }
                    return JsonResponse(data)
                except Exception as ex:
                    data = {"result": "ok", "results": []}
                    return JsonResponse(data)


        criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True), ''
        if criterio:
            filtros = filtros & (Q(nombre__icontains=criterio))
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio
        listado = model.objects.filter(filtros)
        data["list_count"] = listado.count()
        data["url_vars"] = url_vars
        paginador(request, listado.order_by('nombre'), 20, data, url_vars)

        # Flag para mostrar/esconder el botón "Crear con IA". Solo activo si
        # Configuracion tiene token_ia cargado Y el switch ia_features_activas=True.
        from seguridad.models import Configuracion
        _confi = Configuracion.get_instancia()
        data["ia_disponible"] = bool(
            _confi and _confi.pk
            and getattr(_confi, 'ia_features_activas', False)
            and getattr(_confi, 'token_ia_id', None)
        )
        return render(request, 'crm/departamento_chatbots/view.html', data)


TIPOS_NODO_VALIDOS = {t[0] for t in OpcionDepartamentoChatBot.TIPOS_NODO}
VALIDACIONES_VALIDAS = {v[0] for v in OpcionDepartamentoChatBot.VALIDACIONES}


def _aplicar_campos_nodo(opcion, item, padre):
    from crm.models import EndpointApiChatbot

    tipo_nodo = item.get('tipo_nodo') or 'respuesta'
    if tipo_nodo not in TIPOS_NODO_VALIDOS:
        tipo_nodo = 'respuesta'
    validacion_tipo = item.get('validacion_tipo') or 'none'
    if validacion_tipo not in VALIDACIONES_VALIDAS:
        validacion_tipo = 'none'

    opcion.tipo_nodo = tipo_nodo
    opcion.es_inicio = bool(item.get('es_inicio')) and padre is None

    # config: si el frontend manda un dict NO vacío, actualiza; si manda vacío,
    # preserva el existente (para no borrar config editada sólo en Admin).
    cfg = item.get('config')
    if isinstance(cfg, dict) and cfg:
        opcion.config = cfg
    elif not opcion.config:
        opcion.config = {}

    opcion.variable_destino = (item.get('variable_destino') or '').strip()[:80]
    opcion.validacion_tipo = validacion_tipo
    opcion.validacion_expresion = (item.get('validacion_expresion') or '').strip()[:250]
    opcion.mensaje_error = (item.get('mensaje_error') or '').strip()
    try:
        opcion.reintentos_max = max(0, int(item.get('reintentos_max') or 3))
    except (TypeError, ValueError):
        opcion.reintentos_max = 3

    endpoint_id = item.get('endpoint_id')
    if endpoint_id:
        try:
            opcion.endpoint = EndpointApiChatbot.objects.filter(pk=int(endpoint_id), status=True).first()
        except (TypeError, ValueError):
            opcion.endpoint = None
    else:
        opcion.endpoint = None


def sincronizar_opciones(departamento, lista, padre=None):
    nuevos_ids = []
    ids_al_nivel_raiz = []

    for index, item in enumerate(lista, 1):
        opcion_id = item.get('id', None)

        if opcion_id and OpcionDepartamentoChatBot.objects.filter(id=opcion_id, departamento=departamento).exists():
            opcion = OpcionDepartamentoChatBot.objects.get(id=opcion_id)
        else:
            opcion = OpcionDepartamentoChatBot(departamento=departamento)

        opcion.nombre = item.get('nombre', '').strip()
        opcion.respuesta = item.get('respuesta', '').strip()
        opcion.orden = index
        opcion.opcion_padre = padre
        _aplicar_campos_nodo(opcion, item, padre)
        opcion.save()

        nuevos_ids.append(opcion.id)
        if padre is None:
            ids_al_nivel_raiz.append(opcion.id)

        hijos = item.get('hijos', [])
        if hijos:
            nuevos_ids += sincronizar_opciones(departamento, hijos, padre=opcion)

    # Asegurar que haya al menos un nodo raíz con es_inicio=True.
    # Si ninguno lo tiene, se marca el primero (por orden) para que el motor
    # tenga un punto de entrada claro.
    if padre is None and ids_al_nivel_raiz:
        hay_inicio = OpcionDepartamentoChatBot.objects.filter(
            id__in=ids_al_nivel_raiz, es_inicio=True, status=True
        ).exists()
        if not hay_inicio:
            OpcionDepartamentoChatBot.objects.filter(id=ids_al_nivel_raiz[0]).update(es_inicio=True)

    return nuevos_ids


# ============================================================================
# Generador IA — wrapper HTTP. La logica IA vive en
# `agents_ai/ai_actions/dpchatbots_crm.py` (centralizada para todos los providers).
# ============================================================================
def _generar_departamento_con_ia(request):
    """Action: generar_con_ia. Wrapper HTTP delgado: valida configuracion del
    sistema, resuelve la apikey y delega al modulo IA centralizado."""
    from seguridad.models import Configuracion
    from agents_ai.ai_actions import IAActionError
    from agents_ai.ai_actions import dpchatbots_crm

    confi = Configuracion.get_instancia()
    if not confi or not getattr(confi, 'ia_features_activas', False) or not confi.token_ia_id:
        return JsonResponse({
            'error': True,
            'message': 'Features de IA del sistema deshabilitadas. Configurá un token IA en Configuración.',
        })

    try:
        resultado = dpchatbots_crm.generar(
            descripcion=request.POST.get('descripcion'),
            tipo_negocio=request.POST.get('tipo_negocio'),
            tono=request.POST.get('tono') or 'amable',
            apikey_obj=confi.token_ia,
            usuario=request.user,
        )
    except IAActionError as ex:
        return JsonResponse({'error': True, 'message': str(ex)})
    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'Error generando departamento: {ex}'})

    log(
        f"Generó departamento '{resultado['nombre']}' con IA ({resultado['opciones_count']} opciones)",
        request, "add", obj=resultado['departamento_id'],
    )
    return JsonResponse({
        'error': False,
        'nombre': resultado['nombre'],
        'departamento_id': resultado['departamento_id'],
        'opciones_count': resultado['opciones_count'],
    })


# ============================================================================
# Serialización plana del árbol de opciones para render server-side. Cada item
# trae el objeto opción y su nivel de profundidad (0 = raíz). El template
# muestra cada uno con margin-left = nivel * indent.
# ============================================================================
def _serializar_arbol_opciones(departamento, padre=None, nivel=0):
    items = []
    qs = OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, opcion_padre=padre, status=True,
    ).order_by('orden', 'id')
    for op in qs:
        items.append({'opcion': op, 'nivel': nivel})
        items.extend(_serializar_arbol_opciones(departamento, padre=op, nivel=nivel + 1))
    return items


# ============================================================================
# Autosave granular — endpoints para la nueva UI sin wizard. Cada uno persiste
# *solo* su pieza (header del depto / un nodo / mover / eliminar) para que el
# usuario no pierda cambios al cerrar la pagina.
# ============================================================================
def _guardar_meta(request):
    """action=guardar_meta. Crea o actualiza cabecera del departamento.
    pk=0 → crea uno nuevo y devuelve el id. Subsiguientes saves usan ese id."""
    pk = int(request.POST.get('pk') or 0)
    nombre = (request.POST.get('nombre') or '').strip()[:120]
    color = (request.POST.get('color') or '#6c757d').strip()[:20]
    mensaje = (request.POST.get('mensaje_saludo') or '').strip()

    if pk == 0:
        if len(nombre) < 2:
            return JsonResponse({
                'ok': False,
                'error': 'El nombre necesita al menos 2 caracteres para crear el departamento.',
            })
        dep = DepartamentoChatBot(nombre=nombre, color=color, mensaje_saludo=mensaje)
        dep.save(request)
        log(f"Creó (autosave) departamento {dep}", request, "add", obj=dep.id)
        return JsonResponse({'ok': True, 'departamento_id': dep.id, 'created': True})

    dep = DepartamentoChatBot.objects.filter(pk=pk, status=True).first()
    if not dep:
        return JsonResponse({'ok': False, 'error': 'Departamento no encontrado.'})
    if nombre:
        dep.nombre = nombre
    dep.color = color
    dep.mensaje_saludo = mensaje
    dep.save(request)
    return JsonResponse({'ok': True, 'departamento_id': dep.id, 'created': False})


def _guardar_opcion(request):
    """action=guardar_opcion. Crea o actualiza UN nodo del flujo.
    opcion_id=0 → crea; >0 → update. Devuelve el id real para que el frontend
    deje de mandar 0 en saves siguientes."""
    try:
        dep_pk = int(request.POST['departamento_id'])
    except (KeyError, ValueError):
        return JsonResponse({'ok': False, 'error': 'departamento_id requerido'})
    dep = DepartamentoChatBot.objects.filter(pk=dep_pk, status=True).first()
    if not dep:
        return JsonResponse({'ok': False, 'error': 'Departamento no encontrado'})

    op_id = int(request.POST.get('opcion_id') or 0)
    if op_id:
        opcion = OpcionDepartamentoChatBot.objects.filter(pk=op_id, departamento=dep).first()
        if not opcion:
            return JsonResponse({'ok': False, 'error': 'Nodo no encontrado'})
        es_nuevo = False
    else:
        opcion = OpcionDepartamentoChatBot(departamento=dep)
        es_nuevo = True

    parent_id = request.POST.get('parent_id') or ''
    if parent_id and parent_id not in ('0', 'null', 'none'):
        try:
            opcion.opcion_padre = OpcionDepartamentoChatBot.objects.filter(
                pk=int(parent_id), departamento=dep, status=True,
            ).first()
        except (TypeError, ValueError):
            opcion.opcion_padre = None
    else:
        opcion.opcion_padre = None

    opcion.nombre = (request.POST.get('nombre') or '').strip()[:100]
    opcion.respuesta = (request.POST.get('respuesta') or '').strip()
    tipo = (request.POST.get('tipo_nodo') or 'respuesta').strip()
    opcion.tipo_nodo = tipo if tipo in TIPOS_NODO_VALIDOS else 'respuesta'
    opcion.es_inicio = request.POST.get('es_inicio') in ('1', 'true', 'on') and opcion.opcion_padre is None
    orden_raw = request.POST.get('orden')
    if orden_raw:
        try:
            opcion.orden = int(orden_raw)
        except (TypeError, ValueError):
            opcion.orden = 0
    elif es_nuevo:
        # auto-incrementar: max(orden) entre hermanos + 1
        from django.db.models import Max
        max_orden = OpcionDepartamentoChatBot.objects.filter(
            departamento=dep, opcion_padre=opcion.opcion_padre, status=True,
        ).aggregate(m=Max('orden'))['m'] or 0
        opcion.orden = max_orden + 1

    opcion.variable_destino = (request.POST.get('variable_destino') or '').strip()[:80]
    val_tipo = (request.POST.get('validacion_tipo') or 'none').strip()
    opcion.validacion_tipo = val_tipo if val_tipo in VALIDACIONES_VALIDAS else 'none'
    opcion.validacion_expresion = (request.POST.get('validacion_expresion') or '').strip()[:250]
    opcion.mensaje_error = (request.POST.get('mensaje_error') or '').strip()
    try:
        opcion.reintentos_max = max(0, int(request.POST.get('reintentos_max') or 3))
    except (TypeError, ValueError):
        opcion.reintentos_max = 3

    cfg_raw = request.POST.get('config_json')
    if cfg_raw is not None and cfg_raw != '':
        try:
            parsed = json.loads(cfg_raw)
            if isinstance(parsed, dict):
                opcion.config = parsed
            else:
                return JsonResponse({'ok': False, 'error': 'config_json debe ser objeto'})
        except json.JSONDecodeError as ex:
            return JsonResponse({'ok': False, 'error': f'config_json invalido: {ex}'})
    elif not opcion.config:
        opcion.config = {}

    end_id = request.POST.get('endpoint_id') or ''
    if end_id and end_id not in ('0', 'null', 'none'):
        try:
            opcion.endpoint = EndpointApiChatbot.objects.filter(pk=int(end_id), status=True).first()
        except (TypeError, ValueError):
            opcion.endpoint = None
    else:
        opcion.endpoint = None

    opcion.save(request)

    # Si no hay otro nodo raiz con es_inicio=True y este es raiz, marcalo.
    if opcion.opcion_padre is None:
        hay_inicio = OpcionDepartamentoChatBot.objects.filter(
            departamento=dep, opcion_padre__isnull=True,
            es_inicio=True, status=True,
        ).exclude(pk=opcion.pk).exists()
        if not hay_inicio and not opcion.es_inicio:
            opcion.es_inicio = True
            opcion.save(request)

    return JsonResponse({
        'ok': True,
        'opcion_id': opcion.id,
        'created': not bool(op_id),
    })


def _eliminar_opcion(request):
    """action=eliminar_opcion. Soft-delete del nodo y todos sus descendientes."""
    try:
        op_id = int(request.POST['opcion_id'])
    except (KeyError, ValueError):
        return JsonResponse({'ok': False, 'error': 'opcion_id requerido'})

    opcion = OpcionDepartamentoChatBot.objects.filter(pk=op_id, status=True).first()
    if not opcion:
        return JsonResponse({'ok': False, 'error': 'Nodo no encontrado'})

    eliminados = [opcion.id]

    def _cascade(nodo):
        for hijo in nodo.subopciones.filter(status=True):
            eliminados.append(hijo.id)
            _cascade(hijo)
            hijo.status = False
            hijo.save(request)

    _cascade(opcion)
    opcion.status = False
    opcion.save(request)
    return JsonResponse({'ok': True, 'eliminados': eliminados})


def _mover_opcion(request):
    """action=mover_opcion. Reordena un nodo y/o cambia su padre.
    parent_id puede venir vacio para nodo raiz."""
    try:
        op_id = int(request.POST['opcion_id'])
    except (KeyError, ValueError):
        return JsonResponse({'ok': False, 'error': 'opcion_id requerido'})

    opcion = OpcionDepartamentoChatBot.objects.filter(pk=op_id, status=True).first()
    if not opcion:
        return JsonResponse({'ok': False, 'error': 'Nodo no encontrado'})

    parent_id = request.POST.get('parent_id') or ''
    if parent_id and parent_id not in ('0', 'null', 'none'):
        try:
            padre = OpcionDepartamentoChatBot.objects.filter(
                pk=int(parent_id), departamento=opcion.departamento, status=True,
            ).first()
            if padre and padre.pk == opcion.pk:
                return JsonResponse({'ok': False, 'error': 'Un nodo no puede ser su propio padre'})
            opcion.opcion_padre = padre
        except (TypeError, ValueError):
            opcion.opcion_padre = None
    else:
        opcion.opcion_padre = None

    try:
        opcion.orden = int(request.POST.get('orden') or 0)
    except (TypeError, ValueError):
        opcion.orden = 0

    opcion.save(request)
    return JsonResponse({'ok': True, 'opcion_id': opcion.id})

