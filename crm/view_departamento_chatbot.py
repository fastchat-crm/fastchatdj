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
from .funciones_departamento_chatbot import (
    sincronizar_opciones,
    _generar_departamento_con_ia,
    _crear_agente_desde_dpto,
    _duplicar_info,
    _duplicar_departamento,
    _guardar_meta,
    _guardar_opcion,
    _eliminar_opcion,
    _mover_opcion,
    _probar_http,
    _serializar_arbol_opciones,
    _serializar_arbol_anidado,
    _serializar_para_preview,
    _build_meta_payload,
    _exportar_flujo_completo,
)
from .models import Industria, ActividadEconomica, DepartamentoChatBot, OpcionDepartamentoChatBot, \
    PerfilDepartamentoChatBot, EndpointApiChatbot, EstadoFlujoChatbot, ConexionNodoChatbot
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
                    # Soft-delete con cascada manual a TODO lo que cuelgue del
                    # departamento. Necesario porque varios FKs son SET_NULL en
                    # BD (no borran realmente) y la UI filtra por status=True.
                    # Sin esto quedan "huérfanos lógicos": referencias a un
                    # departamento status=False que la UI no muestra pero el
                    # motor del flujo sigue resolviendo.
                    from whatsapp.models import SesionWhatsApp
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    with transaction.atomic():
                        filtro.status = False
                        filtro.save(request)
                        # Asesores asignados al depto.
                        PerfilDepartamentoChatBot.objects.filter(
                            status=True, departamento=filtro
                        ).update(status=False)
                        # Nodos del flujo del depto.
                        OpcionDepartamentoChatBot.objects.filter(
                            status=True, departamento=filtro
                        ).update(status=False)
                        # Estado runtime del flujo (en qué nodo quedó cada conversación).
                        EstadoFlujoChatbot.objects.filter(
                            status=True, departamento=filtro
                        ).update(status=False, departamento=None, nodo_actual=None)
                        # Sesiones que tenían este depto como entrada por defecto.
                        SesionWhatsApp.objects.filter(
                            departamento_default=filtro
                        ).update(departamento_default=None)
                        # M2M sesiones ↔ departamentos (la tabla intermedia no
                        # tiene status, hay que limpiar la relación a mano).
                        for sesion in SesionWhatsApp.objects.filter(departamentos=filtro):
                            sesion.departamentos.remove(filtro)
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
                elif action == 'crear_agente_desde_dpto':
                    return _crear_agente_desde_dpto(request)
                elif action == 'duplicar_info':
                    return _duplicar_info(request)
                elif action == 'duplicar':
                    return _duplicar_departamento(request)
                elif action == 'guardar_meta':
                    return _guardar_meta(request)
                elif action == 'guardar_opcion':
                    return _guardar_opcion(request)
                elif action == 'eliminar_opcion':
                    return _eliminar_opcion(request)
                elif action == 'mover_opcion':
                    return _mover_opcion(request)
                elif action == 'probar_http':
                    return _probar_http(request)
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
                            'arbol_anidado': _serializar_arbol_anidado(filtro),
                            'tipos_nodo_choices': OpcionDepartamentoChatBot.TIPOS_NODO,
                            'validaciones_choices': OpcionDepartamentoChatBot.VALIDACIONES,
                            'endpoints_disponibles': EndpointApiChatbot.objects.filter(status=True).order_by('nombre'),
                        })
                        return render(request, 'crm/departamento_chatbots/form_pagina.html', data)
                    template = get_template("crm/departamento_chatbots/form.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, 'message': str(ex)})

            elif action == 'diagrama':
                # Diagrama del árbol de decisiones, full-page (no modal).
                try:
                    pk = int(request.GET['id'])
                    filtro = model.objects.get(pk=pk)
                    data["filtro"] = filtro
                    data["arbol_anidado"] = _serializar_arbol_anidado(filtro)
                    return render(request, 'crm/departamento_chatbots/diagrama.html', data)
                except Exception as ex:
                    return JsonResponse({'result': False, 'message': str(ex)})

            elif action == 'preview':
                # Simulador WhatsApp-like del flujo. Renderiza pagina full con
                # arbol serializado en JSON para que el JS del cliente lo recorra.
                try:
                    pk = int(request.GET['id'])
                    filtro = model.objects.get(pk=pk)
                    data["filtro"] = filtro
                    data["preview_json"] = json.dumps(_serializar_para_preview(filtro), ensure_ascii=False)
                    return render(request, 'crm/departamento_chatbots/preview.html', data)
                except Exception as ex:
                    return JsonResponse({'result': False, 'message': str(ex)})

            elif action == 'exportar_meta_payload':
                # Devuelve el JSON Meta Cloud API (interactive button/list) construido
                # desde el saludo del depto + sus opciones raíz/primeras hijas.
                try:
                    dep_id = int(request.GET.get('id') or 0)
                    filtro = model.objects.filter(pk=dep_id, status=True).first()
                    if not filtro:
                        return JsonResponse({'result': False, 'message': 'Departamento no encontrado'})
                    payload = _build_meta_payload(filtro)
                    return JsonResponse({'result': True, 'payload': payload})
                except Exception as ex:
                    return JsonResponse({'result': False, 'message': str(ex)})

            elif action == 'exportar_flujo_json':
                # Devuelve el snapshot COMPLETO del flujo: depto + nodos +
                # conexiones + endpoints/credenciales referenciados. Sirve
                # para auditar configuración, exportar/importar entre
                # ambientes, y como "ficha técnica" del bot.
                try:
                    dep_id = int(request.GET.get('id') or 0)
                    filtro = model.objects.filter(pk=dep_id, status=True).first()
                    if not filtro:
                        return JsonResponse({'result': False, 'message': 'Departamento no encontrado'})
                    payload = _exportar_flujo_completo(filtro)
                    return JsonResponse({'result': True, 'data': payload})
                except Exception as ex:
                    return JsonResponse({'result': False, 'message': str(ex)})

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
                        cfg = opcion.config or {}
                        # Padres posibles: nodos del mismo depto excluyendo self
                        # y todo el sub-árbol (anti-ciclo).
                        descendientes_ids = set()
                        pendientes = [opcion]
                        while pendientes:
                            n = pendientes.pop()
                            descendientes_ids.add(n.pk)
                            for h in n.subopciones.filter(status=True):
                                pendientes.append(h)
                        padres_disponibles = OpcionDepartamentoChatBot.objects.filter(
                            departamento=opcion.departamento, status=True,
                        ).exclude(pk__in=descendientes_ids).order_by('orden', 'nombre')
                        contexto.update({
                            'opcion': opcion,
                            'es_nuevo': False,
                            'departamento_id': opcion.departamento_id,
                            'parent_id': opcion.opcion_padre_id or 0,
                            'padres_disponibles': padres_disponibles,
                            'config_json_str': json.dumps(cfg, indent=2, ensure_ascii=False),
                            # Sub-piezas serializadas para los inputs específicos del form HTTP.
                            'http_query_json_str':   json.dumps(cfg.get('query') or {}, indent=2, ensure_ascii=False) if cfg.get('query') else '',
                            'http_body_json_str':    json.dumps(cfg.get('body') or {}, indent=2, ensure_ascii=False) if cfg.get('body') else '',
                            'http_headers_json_str': json.dumps(cfg.get('headers') or {}, indent=2, ensure_ascii=False) if cfg.get('headers') else '',
                            'http_extraer_json_str': json.dumps(cfg.get('extraer') or [], indent=2, ensure_ascii=False) if cfg.get('extraer') else '',
                            # Condicional / set_variable: JSON serializado para el textarea.
                            'cond_condiciones_json_str':    json.dumps(cfg.get('condiciones') or [], indent=2, ensure_ascii=False) if cfg.get('condiciones') else '',
                            'setvar_asignaciones_json_str': json.dumps(cfg.get('asignaciones') or [], indent=2, ensure_ascii=False) if cfg.get('asignaciones') else '',
                        })
                    else:
                        padres_disponibles = OpcionDepartamentoChatBot.objects.filter(
                            departamento_id=dep_id, status=True,
                        ).order_by('orden', 'nombre')
                        contexto.update({
                            'opcion': None,
                            'es_nuevo': True,
                            'departamento_id': dep_id,
                            'parent_id': parent_id,
                            'padres_disponibles': padres_disponibles,
                            'config_json_str': '{}',
                            'http_query_json_str': '',
                            'http_body_json_str': '',
                            'http_headers_json_str': '',
                            'http_extraer_json_str': '',
                            'cond_condiciones_json_str': '',
                            'setvar_asignaciones_json_str': '',
                        })
                    template = get_template('crm/departamento_chatbots/_form_opcion.html')
                    return JsonResponse({'result': True, 'data': template.render(contexto)})
                except Exception as ex:
                    return JsonResponse({'result': False, 'message': str(ex)})

            elif action == 'ficha_opcion':
                # Devuelve la ficha read-only de un nodo: TODOS los campos
                # registrados (modelo + config dinámico + endpoint + conexiones
                # entrantes/salientes + auditoría). El front la muestra en
                # un modal aparte del modal de edición.
                try:
                    op_id = int(request.GET.get('id') or 0)
                    opcion = (
                        OpcionDepartamentoChatBot.objects
                        .select_related('endpoint', 'endpoint__credencial', 'opcion_padre',
                                        'usuario_creacion', 'usuario_modificacion')
                        .filter(pk=op_id, status=True).first()
                    )
                    if not opcion:
                        return JsonResponse({'result': False, 'message': 'Nodo no encontrado'})
                    cfg = opcion.config or {}
                    salidas = (
                        ConexionNodoChatbot.objects
                        .filter(nodo_origen=opcion, status=True)
                        .select_related('nodo_destino')
                        .order_by('orden', 'id')
                    )
                    entradas = (
                        ConexionNodoChatbot.objects
                        .filter(nodo_destino=opcion, status=True)
                        .select_related('nodo_origen')
                        .order_by('orden', 'id')
                    )
                    contexto = {
                        'opcion': opcion,
                        'cfg': cfg,
                        'config_json_str': json.dumps(cfg, indent=2, ensure_ascii=False),
                        'salidas': salidas,
                        'entradas': entradas,
                    }
                    template = get_template('crm/departamento_chatbots/_ficha_opcion.html')
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

        # API Keys del usuario para el modal "Generar Agente IA desde depto".
        # Si no hay perfil o no hay keys, el modal muestra un aviso amable.
        from .models import ApiKeyIA, PerfilNegocioIA
        _perfil = PerfilNegocioIA.objects.filter(usuario=request.user).first()
        if _perfil:
            data["apikeys_ia"] = list(
                ApiKeyIA.objects.filter(perfil=_perfil, status=True)
                .order_by('alias').values('id', 'alias', 'proveedor', 'modelo')
            )
            data["tiene_perfil_ia"] = True
        else:
            data["apikeys_ia"] = []
            data["tiene_perfil_ia"] = False
        return render(request, 'crm/departamento_chatbots/view.html', data)
