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
                        contexto.update({
                            'opcion': opcion,
                            'es_nuevo': False,
                            'departamento_id': opcion.departamento_id,
                            'parent_id': opcion.opcion_padre_id or 0,
                            'config_json_str': json.dumps(cfg, indent=2, ensure_ascii=False),
                            # Sub-piezas serializadas para los inputs específicos del form HTTP.
                            'http_query_json_str':   json.dumps(cfg.get('query') or {}, indent=2, ensure_ascii=False) if cfg.get('query') else '',
                            'http_body_json_str':    json.dumps(cfg.get('body') or {}, indent=2, ensure_ascii=False) if cfg.get('body') else '',
                            'http_headers_json_str': json.dumps(cfg.get('headers') or {}, indent=2, ensure_ascii=False) if cfg.get('headers') else '',
                            'http_extraer_json_str': json.dumps(cfg.get('extraer') or [], indent=2, ensure_ascii=False) if cfg.get('extraer') else '',
                        })
                    else:
                        contexto.update({
                            'opcion': None,
                            'es_nuevo': True,
                            'departamento_id': dep_id,
                            'parent_id': parent_id,
                            'config_json_str': '{}',
                            'http_query_json_str': '',
                            'http_body_json_str': '',
                            'http_headers_json_str': '',
                            'http_extraer_json_str': '',
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
def _build_meta_payload(departamento):
    """Construye payload Meta Cloud API del primer mensaje del bot.

    Lee primero `config.opciones` del nodo root (formato del motor de flujo).
    Si no existe, cae al árbol legacy `opcion_padre`. Despacha por tipo_nodo:
        cta_url   → interactive cta_url
        ubicacion → location
        menu      → interactive button (≤3) o list (>3) usando config.opciones
        pregunta  → text (config.pregunta como cuerpo)
        respuesta → text (config.mensaje o respuesta)
    """
    # Root: prefiere es_inicio=True, sino primer huérfano del árbol legacy.
    root = OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, status=True, es_inicio=True,
    ).order_by('orden', 'id').first()
    if not root:
        root = OpcionDepartamentoChatBot.objects.filter(
            departamento=departamento, opcion_padre__isnull=True, status=True,
        ).order_by('orden', 'id').first()

    base = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': '593XXXXXXXXX',
    }

    if not root:
        body_text = (departamento.mensaje_saludo or departamento.nombre or '—').strip()
        return {**base, 'type': 'text', 'text': {
            'preview_url': False,
            'body': body_text[:4096],
        }}

    cfg = root.config or {}
    saludo = (departamento.mensaje_saludo or '').strip()

    # Body según tipo del nodo
    if root.tipo_nodo == 'menu':
        msg_nodo = (cfg.get('mensaje') or root.respuesta or '').strip()
        body_text = (saludo + ('\n\n' + msg_nodo if msg_nodo else '')).strip() or msg_nodo or saludo
    elif root.tipo_nodo == 'pregunta':
        body_text = (cfg.get('pregunta') or root.respuesta or saludo).strip()
    elif root.tipo_nodo == 'respuesta':
        body_text = (cfg.get('mensaje') or root.respuesta or saludo).strip()
    else:
        body_text = (root.respuesta or saludo or departamento.nombre or '—').strip()
    if not body_text:
        body_text = departamento.nombre or '—'

    # Despacho por tipo del root
    if root.tipo_nodo == 'cta_url':
        return {**base, 'type': 'interactive', 'interactive': {
            'type': 'cta_url',
            'body': {'text': body_text[:1024]},
            'action': {
                'name': 'cta_url',
                'parameters': {
                    'display_text': (cfg.get('display_text') or 'Abrir')[:20],
                    'url': cfg.get('url') or '',
                },
            },
        }}

    if root.tipo_nodo == 'ubicacion':
        return {**base, 'type': 'location', 'location': {
            'latitude': cfg.get('lat') or 0,
            'longitude': cfg.get('lng') or 0,
            'name': cfg.get('name') or '',
            'address': cfg.get('address') or '',
        }}

    # Lista de opciones: 1) config.opciones (motor flujo), 2) hijos legacy
    items = []  # [{id, title, description}]
    opciones_cfg = cfg.get('opciones') or []
    if root.tipo_nodo == 'menu' and opciones_cfg:
        for opt in opciones_cfg:
            etq = (opt.get('etiqueta') or opt.get('valor') or '').strip()
            sal = (opt.get('salida') or opt.get('valor') or '').strip()
            if not etq:
                continue
            items.append({
                'id': sal[:256] or f'opcion_{len(items)+1}',
                'title': etq[:24],
                'description': '',
            })
    else:
        hijos = list(OpcionDepartamentoChatBot.objects.filter(
            opcion_padre=root, status=True,
        ).order_by('orden', 'id'))
        for op in hijos:
            items.append({
                'id': (op.boton_id or f'opcion_{op.id}')[:256],
                'title': ((op.nombre or '').strip() or f'Opción {op.id}')[:24],
                'description': ((op.respuesta or '').strip()[:72]) or '',
            })

    if not items:
        return {**base, 'type': 'text', 'text': {
            'preview_url': False,
            'body': body_text[:4096],
        }}

    if len(items) <= 3:
        botones = [{
            'type': 'reply',
            'reply': {'id': it['id'], 'title': it['title'][:20]},
        } for it in items]
        return {**base, 'type': 'interactive', 'interactive': {
            'type': 'button',
            'body': {'text': body_text[:1024]},
            'action': {'buttons': botones},
        }}

    # Meta tiene límite hard de 10 rows POR SECCIÓN (max 10 secciones).
    # Con >10 opciones, paginamos en chunks de 10 con títulos sintéticos.
    sections = []
    if len(items) <= 10:
        sections = [{'title': 'Opciones', 'rows': items}]
    else:
        for i in range(0, min(len(items), 100), 10):
            chunk = items[i:i + 10]
            sections.append({
                'title': f'Opciones {i + 1}–{i + len(chunk)}',
                'rows': chunk,
            })
    return {**base, 'type': 'interactive', 'interactive': {
        'type': 'list',
        'body': {'text': body_text[:1024]},
        'action': {
            'button': 'Ver opciones',
            'sections': sections,
        },
    }}


def _serializar_arbol_opciones(departamento, padre=None, nivel=0):
    """Aplana el flujo del depto en lista [{opcion, nivel}] respetando jerarquía.

    Recorre el grafo `ConexionNodoChatbot` + `config.opciones` (formato del
    motor de flujo). Cae al árbol legacy `opcion_padre` solo si no hay grafo.
    Anti-ciclo via `visited`: cada nodo aparece una sola vez.
    """
    if padre is not None:
        # Llamadas recursivas legacy: mantener compat con el árbol opcion_padre.
        items = []
        qs = OpcionDepartamentoChatBot.objects.filter(
            departamento=departamento, opcion_padre=padre, status=True,
        ).order_by('orden', 'id')
        for op in qs:
            items.append({'opcion': op, 'nivel': nivel})
            items.extend(_serializar_arbol_opciones(departamento, padre=op, nivel=nivel + 1))
        return items

    from .models import ConexionNodoChatbot

    nodos_qs = OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, status=True,
    )
    nodos_by_id = {n.id: n for n in nodos_qs}
    if not nodos_by_id:
        return []

    conex_qs = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=departamento, status=True,
    ).order_by('nodo_origen', 'orden', 'id')
    conex_by_origen = {}
    for c in conex_qs:
        conex_by_origen.setdefault(c.nodo_origen_id, []).append(c)

    def _destino(op_id, etiqueta):
        for c in conex_by_origen.get(op_id, []):
            if c.etiqueta == etiqueta:
                return nodos_by_id.get(c.nodo_destino_id)
        return None

    def _siguiente_default(op_id):
        for et in ('', 'ok'):
            d = _destino(op_id, et)
            if d:
                return d
        return None

    items = []
    visited = set()

    def _walk(op, lvl):
        if op.id in visited:
            return
        visited.add(op.id)
        items.append({'opcion': op, 'nivel': lvl})
        cfg = op.config or {}
        if op.tipo_nodo == 'menu':
            for opt in (cfg.get('opciones') or []):
                sal = (opt.get('salida') or '').strip()
                dest = _destino(op.id, sal) if sal else _siguiente_default(op.id)
                if dest:
                    _walk(dest, lvl + 1)
            # Fallback legacy: hijos por opcion_padre
            for c in OpcionDepartamentoChatBot.objects.filter(
                opcion_padre=op, status=True,
            ).order_by('orden', 'id'):
                _walk(c, lvl + 1)
        elif op.tipo_nodo == 'condicional':
            # Sigue ambas ramas; 'true' primero para que el árbol refleje
            # la lógica natural ("si pasa la condición → este sub-flujo").
            for et in ('true', 'false'):
                d = _destino(op.id, et)
                if d:
                    _walk(d, lvl + 1)
        elif op.tipo_nodo in ('respuesta', 'pregunta', 'set_variable', 'cta_url'):
            sig = _siguiente_default(op.id)
            if sig:
                _walk(sig, lvl + 1)
        elif op.tipo_nodo == 'http':
            sig = _destino(op.id, 'ok') or _siguiente_default(op.id)
            if sig:
                _walk(sig, lvl + 1)
        # handoff / fin / ubicacion → no descendientes

    inicio = next((n for n in nodos_by_id.values() if n.es_inicio), None)
    if not inicio:
        inicio = OpcionDepartamentoChatBot.objects.filter(
            departamento=departamento, opcion_padre__isnull=True, status=True,
        ).order_by('orden', 'id').first()
    if inicio:
        _walk(inicio, 0)

    # Anexar nodos huérfanos del grafo (sin entrada y no inicio) al final, nivel 0,
    # para que el editor pueda verlos y conectarlos.
    for n in sorted(nodos_by_id.values(), key=lambda x: (x.orden, x.id)):
        if n.id not in visited:
            items.append({'opcion': n, 'nivel': 0})
            visited.add(n.id)
    return items


def _serializar_para_preview(departamento):
    """Estructura compacta para el simulador WhatsApp del flujo. Cada nodo
    incluye sus hijos inline para que el JS no tenga que recorrer un mapa.

    Recorre el grafo real `ConexionNodoChatbot` + `config.opciones` (formato
    del motor `motor_flujo_chatbot`). Cae al árbol legacy `opcion_padre` solo
    si no hay ni opciones ni conexiones salientes.
    """
    from .models import ConexionNodoChatbot

    nodos_qs = OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, status=True,
    )
    nodos_by_id = {n.id: n for n in nodos_qs}

    conex_qs = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=departamento, status=True,
    ).order_by('nodo_origen', 'orden', 'id')
    conex_by_origen = {}
    for c in conex_qs:
        conex_by_origen.setdefault(c.nodo_origen_id, []).append(c)

    def _destino(op_id, etiqueta):
        for c in conex_by_origen.get(op_id, []):
            if c.etiqueta == etiqueta:
                return nodos_by_id.get(c.nodo_destino_id)
        return None

    def _siguiente_default(op_id):
        # Default = etiqueta vacía o 'ok'.
        for et in ('', 'ok'):
            d = _destino(op_id, et)
            if d:
                return d
        return None

    def _conv(op, visited):
        if op.id in visited:
            return {
                'id': op.id, 'nombre': op.nombre or '', 'respuesta': '',
                'tipo': op.tipo_nodo, 'boton_id': op.boton_id or f'opcion_{op.id}',
                'es_inicio': False, 'config': op.config or {},
                'hijos': [], 'cycle': True,
            }
        visited = visited | {op.id}
        cfg = op.config or {}
        hijos_data = []

        if op.tipo_nodo == 'menu':
            # 1) Opciones del config (motor flujo): cada salida resuelve a un nodo.
            opciones = cfg.get('opciones') or []
            for opt in opciones:
                etq = (opt.get('etiqueta') or opt.get('valor') or '').strip()
                sal = (opt.get('salida') or '').strip()
                dest = _destino(op.id, sal) if sal else _siguiente_default(op.id)
                if not dest:
                    continue
                child = _conv(dest, visited)
                # El botón muestra la etiqueta de la opción, no el nombre del nodo destino.
                child['nombre'] = etq or child.get('nombre', '')
                child['boton_id'] = sal or child.get('boton_id', '')
                hijos_data.append(child)
            # 2) Fallback árbol legacy
            if not hijos_data:
                hijos_data = [
                    _conv(c, visited)
                    for c in OpcionDepartamentoChatBot.objects.filter(
                        opcion_padre=op, status=True,
                    ).order_by('orden', 'id')
                ]
        elif op.tipo_nodo in ('respuesta', 'pregunta', 'set_variable',
                              'condicional', 'cta_url'):
            sig = _siguiente_default(op.id)
            if sig:
                hijos_data = [_conv(sig, visited)]
        elif op.tipo_nodo == 'http':
            sig = _destino(op.id, 'ok') or _siguiente_default(op.id)
            if sig:
                hijos_data = [_conv(sig, visited)]
        # handoff/fin/ubicacion → sin hijos

        return {
            'id': op.id,
            'nombre': op.nombre or '',
            'respuesta': op.respuesta or '',
            'tipo': op.tipo_nodo,
            'boton_id': op.boton_id or f'opcion_{op.id}',
            'es_inicio': bool(op.es_inicio),
            'config': cfg,
            'hijos': hijos_data,
        }

    inicio = OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, status=True, es_inicio=True,
    ).order_by('orden', 'id').first()
    if not inicio:
        inicio = OpcionDepartamentoChatBot.objects.filter(
            departamento=departamento, opcion_padre__isnull=True, status=True,
        ).order_by('orden', 'id').first()

    raices_data = [_conv(inicio, set())] if inicio else []

    return {
        'departamento': {
            'id': departamento.id,
            'nombre': departamento.nombre,
            'color': departamento.color or '#16a34a',
            'mensaje_saludo': departamento.mensaje_saludo or '',
        },
        'raices': raices_data,
    }


def _serializar_arbol_anidado(departamento, padre=None):
    """Versión anidada (estructura recursiva) para el diagrama horizontal.

    Recorre el grafo `ConexionNodoChatbot` + `config.opciones` (formato del
    motor de flujo) — los condicionales abren ramas `true`/`false`, los
    menus abren una rama por opción, los nodos lineales siguen la default.

    Cae al árbol legacy `opcion_padre` si no hay grafo. Anti-ciclo via
    `visited` para que cada nodo aparezca una sola vez.
    """
    if padre is not None:
        # Compat: llamadas recursivas legacy con padre fijo.
        qs = OpcionDepartamentoChatBot.objects.filter(
            departamento=departamento, opcion_padre=padre, status=True,
        ).order_by('orden', 'id')
        return [
            {'opcion': op, 'hijos': _serializar_arbol_anidado(departamento, padre=op),
             'etiqueta': ''}
            for op in qs
        ]

    from .models import ConexionNodoChatbot

    nodos_qs = OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, status=True,
    )
    nodos_by_id = {n.id: n for n in nodos_qs}
    if not nodos_by_id:
        return []

    conex_qs = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=departamento, status=True,
    ).order_by('nodo_origen', 'orden', 'id')
    conex_by_origen = {}
    for c in conex_qs:
        conex_by_origen.setdefault(c.nodo_origen_id, []).append(c)

    def _conex_etq(op_id, etiqueta):
        for c in conex_by_origen.get(op_id, []):
            if c.etiqueta == etiqueta:
                return c
        return None

    def _conex_default(op_id):
        for et in ('', 'ok'):
            c = _conex_etq(op_id, et)
            if c:
                return c
        return None

    def _walk(op, visited):
        if op.id in visited:
            return {'opcion': op, 'hijos': [], 'etiqueta': '',
                    'cycle': True}
        visited = visited | {op.id}
        cfg = op.config or {}
        hijos = []

        if op.tipo_nodo == 'menu':
            opciones_cfg = cfg.get('opciones') or []
            for opt in opciones_cfg:
                etq_label = (opt.get('etiqueta') or opt.get('valor') or '').strip()
                sal = (opt.get('salida') or '').strip()
                conn = _conex_etq(op.id, sal) if sal else _conex_default(op.id)
                if conn:
                    dest = nodos_by_id.get(conn.nodo_destino_id)
                    if dest:
                        sub = _walk(dest, visited)
                        sub['etiqueta'] = etq_label or sal
                        hijos.append(sub)
            # Fallback árbol legacy
            if not hijos:
                for c in OpcionDepartamentoChatBot.objects.filter(
                    opcion_padre=op, status=True,
                ).order_by('orden', 'id'):
                    sub = _walk(c, visited)
                    sub['etiqueta'] = ''
                    hijos.append(sub)
        elif op.tipo_nodo == 'condicional':
            for et, label in (('true', '✓ Sí'), ('false', '✗ No')):
                conn = _conex_etq(op.id, et)
                if conn:
                    dest = nodos_by_id.get(conn.nodo_destino_id)
                    if dest:
                        sub = _walk(dest, visited)
                        sub['etiqueta'] = label
                        hijos.append(sub)
        elif op.tipo_nodo == 'http':
            for et, label in (('ok', '✓ ok'), ('error', '⚠️ error')):
                conn = _conex_etq(op.id, et)
                if conn:
                    dest = nodos_by_id.get(conn.nodo_destino_id)
                    if dest:
                        sub = _walk(dest, visited)
                        sub['etiqueta'] = label
                        hijos.append(sub)
        elif op.tipo_nodo in ('respuesta', 'pregunta', 'set_variable', 'cta_url'):
            conn = _conex_default(op.id)
            if conn:
                dest = nodos_by_id.get(conn.nodo_destino_id)
                if dest:
                    sub = _walk(dest, visited)
                    sub['etiqueta'] = ''
                    hijos.append(sub)
        # handoff / fin / ubicacion → sin hijos

        return {'opcion': op, 'hijos': hijos, 'etiqueta': ''}

    inicio = next((n for n in nodos_by_id.values() if n.es_inicio), None)
    if not inicio:
        inicio = OpcionDepartamentoChatBot.objects.filter(
            departamento=departamento, opcion_padre__isnull=True, status=True,
        ).order_by('orden', 'id').first()

    raices = [_walk(inicio, set())] if inicio else []

    # Anexar nodos huérfanos del grafo (sin entrada y no inicio) al final.
    visited_ids = set()
    def _collect_visited(node):
        visited_ids.add(node['opcion'].id)
        for h in node['hijos']:
            _collect_visited(h)
    for r in raices:
        _collect_visited(r)
    for n in sorted(nodos_by_id.values(), key=lambda x: (x.orden, x.id)):
        if n.id not in visited_ids:
            raices.append({'opcion': n, 'hijos': [], 'etiqueta': ''})
    return raices


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

    # boton_id: input directo o auto-generado desde el nombre (slug legible).
    # Usamos snake_case sin emojis ni caracteres especiales. Si dos nodos terminan
    # con el mismo slug, agregamos sufijo _<id> al guardar.
    import re as _re
    import unicodedata as _ud

    def _slugify(text):
        # NFKD: separa acentos; ascii: descarta no-ascii (emojis, ñ→n, etc.)
        norm = _ud.normalize('NFKD', text or '')
        ascii_txt = norm.encode('ascii', 'ignore').decode('ascii')
        # baja a minúsculas, espacios+guiones a _, descarta lo demás
        slug = _re.sub(r'[^a-zA-Z0-9]+', '_', ascii_txt).strip('_').lower()
        return slug[:50]

    boton_id_input = (request.POST.get('boton_id') or '').strip()[:64]
    boton_id_input = _re.sub(r'[^a-zA-Z0-9_\-]', '', boton_id_input)
    if boton_id_input:
        opcion.boton_id = boton_id_input
    else:
        base = _slugify(opcion.nombre)
        if base:
            # Buscar primer slug libre: base, base_2, base_3, ...
            candidato = base
            n = 1
            qs = OpcionDepartamentoChatBot.objects.filter(departamento=dep, status=True)
            if opcion.pk:
                qs = qs.exclude(pk=opcion.pk)
            while qs.filter(boton_id=candidato).exists():
                n += 1
                candidato = f"{base}_{n}"
            opcion.boton_id = candidato
        else:
            opcion.boton_id = ''

    # config_json se construye según tipo_nodo nativo
    if opcion.tipo_nodo == 'cta_url':
        url = (request.POST.get('accion_url') or '').strip()
        text = (request.POST.get('accion_display_text') or '').strip()[:20]
        if not url:
            return JsonResponse({'ok': False, 'error': 'cta_url requiere URL destino'})
        opcion.config = {
            'url': url,
            'display_text': text or 'Abrir',
        }
    elif opcion.tipo_nodo == 'ubicacion':
        try:
            lat = float(request.POST.get('ubicacion_lat') or 0)
            lng = float(request.POST.get('ubicacion_lng') or 0)
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'lat/lng inválidos'})
        if lat == 0 and lng == 0:
            return JsonResponse({'ok': False, 'error': 'Ubicación requiere lat/lng'})
        opcion.config = {
            'lat': lat, 'lng': lng,
            'name': (request.POST.get('ubicacion_nombre') or '').strip()[:120],
            'address': (request.POST.get('ubicacion_direccion') or '').strip()[:200],
        }
    elif opcion.tipo_nodo == 'http':
        # Endpoint FK
        ep_id = request.POST.get('http_endpoint_id') or ''
        if ep_id.isdigit():
            ep = EndpointApiChatbot.objects.filter(pk=int(ep_id), status=True).first()
            if not ep:
                return JsonResponse({'ok': False, 'error': 'Endpoint no encontrado'})
            opcion.endpoint = ep
        else:
            opcion.endpoint = None

        metodo = (request.POST.get('http_metodo') or 'GET').upper().strip()
        if metodo not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
            metodo = 'GET'
        path = (request.POST.get('http_path') or '').strip()[:500]

        def _parse_json_field(name, default):
            raw = (request.POST.get(name) or '').strip()
            if not raw:
                return default
            try:
                return json.loads(raw)
            except (TypeError, ValueError) as ex:
                return JsonResponse({
                    'ok': False,
                    'error': f'Campo {name} no es JSON válido: {str(ex)[:120]}',
                })

        # Parsear cada campo y propagar errores como respuesta inmediata.
        query = _parse_json_field('http_query_json', {})
        if isinstance(query, JsonResponse):
            return query
        body = _parse_json_field('http_body_json', None)
        if isinstance(body, JsonResponse):
            return body
        headers = _parse_json_field('http_headers_json', {})
        if isinstance(headers, JsonResponse):
            return headers
        extraer = _parse_json_field('http_extraer_json', [])
        if isinstance(extraer, JsonResponse):
            return extraer

        if not isinstance(query, dict):
            return JsonResponse({'ok': False, 'error': 'http query debe ser objeto JSON'})
        if body is not None and not isinstance(body, (dict, list)):
            return JsonResponse({'ok': False, 'error': 'http body debe ser objeto/array JSON'})
        if not isinstance(headers, dict):
            return JsonResponse({'ok': False, 'error': 'http headers debe ser objeto JSON'})
        if not isinstance(extraer, list):
            return JsonResponse({'ok': False, 'error': 'http extraer debe ser array JSON'})

        cfg = {
            'metodo': metodo,
            'path':   path,
            'plantilla_respuesta': (request.POST.get('http_plantilla') or '').strip(),
        }
        if query:    cfg['query']   = query
        if body is not None and body != {}:
            cfg['body'] = body
        if headers:  cfg['headers'] = headers
        if extraer:  cfg['extraer'] = extraer
        opcion.config = cfg
    else:
        # Tipos sin form específico → limpiar config si era de otro tipo (cta_url/
        # ubicacion/http) para evitar dejar fields obsoletos.
        if opcion.config and (
            'url' in opcion.config or 'lat' in opcion.config or 'meta_type' in opcion.config
            or 'metodo' in opcion.config or 'path' in opcion.config
        ):
            opcion.config = {}
        elif not opcion.config:
            opcion.config = {}
        # Si dejó de ser http, desvincular el endpoint también.
        if opcion.tipo_nodo != 'http':
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

