from django.db import transaction
from django.http import JsonResponse

from core.funciones import log
from .models import *


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
# Generar AgentesIA (snapshot) a partir de un DepartamentoChatBot. Operación
# determinista, no llama a LLM: vuelca saludo, árbol de opciones, endpoints
# y perfil de empresa al `contexto_estatico` del agente. Mantiene los dos
# módulos (departamentos vs agentes IA) totalmente desacoplados — el agente
# generado vive aparte y se edita en el editor estándar de IA.
# ============================================================================
def _arbol_opciones_a_markdown(nodos, nivel=0):
    """Recorre el árbol devuelto por `obtener_arbol_opciones()` y produce
    una lista jerárquica en Markdown apta para inyectar en el prompt."""
    sangria = '  ' * nivel
    lineas = []
    for n in nodos:
        nombre = (n.get('nombre') or '(sin nombre)').strip()
        tipo = n.get('tipo_nodo') or 'respuesta'
        respuesta = (n.get('respuesta') or '').strip()
        cfg = n.get('config') or {}
        lineas.append(f"{sangria}- **{nombre}** _[{tipo}]_")
        if respuesta:
            lineas.append(f"{sangria}  · Respuesta: {respuesta[:300]}")
        if tipo == 'pregunta':
            preg = (cfg.get('pregunta') or '').strip()
            if preg:
                lineas.append(f"{sangria}  · Pregunta: {preg[:300]}")
            if n.get('variable_destino'):
                lineas.append(f"{sangria}  · Guarda en variable `{n['variable_destino']}`")
        elif tipo == 'http':
            metodo = (cfg.get('metodo') or 'GET').upper()
            path = (cfg.get('path') or '').strip() or '/'
            lineas.append(f"{sangria}  · Llamada `{metodo} {path}`")
            extrae = cfg.get('extraer') or []
            if extrae:
                vars_str = ', '.join(
                    f"`{e.get('variable')}` ← `{e.get('jsonpath')}`"
                    for e in extrae[:6] if e.get('variable')
                )
                if vars_str:
                    lineas.append(f"{sangria}    Extrae: {vars_str}")
        elif tipo == 'menu':
            mensaje = (cfg.get('mensaje') or '').strip()
            if mensaje:
                lineas.append(f"{sangria}  · Mensaje del menú: {mensaje[:300]}")
        elif tipo == 'cta_url':
            url = (cfg.get('url') or '').strip()
            if url:
                lineas.append(f"{sangria}  · URL: {url}")
        elif tipo == 'handoff':
            lineas.append(f"{sangria}  · Transfiere a un asesor humano")
        hijos = n.get('hijos') or []
        if hijos:
            lineas.append(_arbol_opciones_a_markdown(hijos, nivel + 1))
    return '\n'.join(lineas)


def _serializar_dpto_para_agente(dpto):
    """Convierte un `DepartamentoChatBot` en texto plano (Markdown ligero)
    apto para `AgentesIA.contexto_estatico`. Incluye saludo, palabras clave,
    árbol de opciones y endpoints API vinculados a sus nodos HTTP."""
    partes = [f"# Departamento de origen: {dpto.nombre}"]

    saludo = (dpto.mensaje_saludo or '').strip()
    if saludo:
        partes.append(f"\n## Saludo inicial sugerido\n{saludo}")

    palabras = dpto.get_palabras_clave()
    if palabras:
        partes.append("\n## Palabras clave que activan este flujo")
        partes.append('\n'.join(f"- {p}" for p in palabras))

    arbol = dpto.obtener_arbol_opciones()
    if arbol:
        partes.append("\n## Flujo y opciones del menú")
        partes.append(_arbol_opciones_a_markdown(arbol, nivel=0))

    nodos_http = OpcionDepartamentoChatBot.objects.filter(
        departamento=dpto, status=True, tipo_nodo='http', endpoint__isnull=False,
    ).select_related('endpoint').order_by('orden', 'id')

    if nodos_http.exists():
        # 1) Resumen de endpoints (host base reutilizado)
        partes.append("\n## Endpoints API base disponibles")
        endpoints_vistos = {}
        for n in nodos_http:
            ep = n.endpoint
            if ep.id not in endpoints_vistos:
                endpoints_vistos[ep.id] = ep
        for ep in endpoints_vistos.values():
            linea = f"- **{ep.nombre}** — `{ep.base_url}`"
            if (ep.descripcion or '').strip():
                linea += f"\n  {ep.descripcion.strip()}"
            partes.append(linea)

        # 2) Catálogo detallado por nodo HTTP — el agente puede usarlo para
        #    saber qué API llamar para resolver consultas concretas (ej. "consulta
        #    placa X" → GET /vehiculo/?placa=X).
        partes.append("\n## Llamadas HTTP del flujo (catálogo para el agente)")
        for n in nodos_http:
            cfg = n.config or {}
            metodo = (cfg.get('metodo') or 'GET').upper()
            path = (cfg.get('path') or '').strip() or '/'
            base = (n.endpoint.base_url or '').rstrip('/')
            url_completa = base + '/' + path.lstrip('/')

            partes.append(f"\n### {n.nombre}")
            partes.append(f"- **{metodo}** `{url_completa}`")

            query = cfg.get('query') or {}
            if query:
                qs_lineas = ', '.join(f"`{k}`={v}" for k, v in query.items())
                partes.append(f"- Query: {qs_lineas}")

            body = cfg.get('body') or {}
            if body and metodo in ('POST', 'PUT', 'PATCH'):
                campos = ', '.join(f"`{k}`" for k in body.keys())
                partes.append(f"- Body fields: {campos}")

            extrae = cfg.get('extraer') or []
            if extrae:
                partes.append("- Variables que extrae de la respuesta:")
                for e in extrae:
                    var = e.get('variable')
                    jp = e.get('jsonpath')
                    if var and jp:
                        partes.append(f"  - `{var}` ← `${jp}`")

            timeout = cfg.get('timeout_seg') or n.endpoint.timeout_seg
            partes.append(f"- Timeout: {timeout}s")

    return '\n'.join(partes).strip()


# `_crear_agente_desde_dpto` se movió a
# `agents_ai/ai_actions/agentes_crm.py:crear_desde_depto`. La view importa
# desde ahí. Esta función ya no existe en este módulo.


# ============================================================================
# Duplicación de departamento. Dos endpoints: `_duplicar_info` (resumen para
# el modal de confirmación) y `_duplicar_departamento` (clona depto + nodos +
# conexiones + asignaciones de usuarios). El nodo `EstadoFlujoChatbot` no se
# clona — es estado runtime de conversaciones reales.
# ============================================================================
def _duplicar_info(request):
    """GET-via-POST opcional: devuelve resumen del depto a duplicar para
    pintar el modal de confirmación (cuenta de nodos, palabras clave, etc.)."""
    try:
        dpto_id = int(request.POST.get('id') or request.GET.get('id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': True, 'message': 'ID inválido.'})

    dpto = DepartamentoChatBot.objects.filter(pk=dpto_id, status=True).first()
    if not dpto:
        return JsonResponse({'error': True, 'message': 'Departamento no encontrado.'})

    palabras = dpto.get_palabras_clave()
    count_opciones = OpcionDepartamentoChatBot.objects.filter(
        departamento=dpto, status=True,
    ).count()
    count_usuarios = PerfilDepartamentoChatBot.objects.filter(
        departamento=dpto, status=True,
    ).count()
    count_conexiones = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=dpto, status=True,
    ).count()
    count_endpoints = OpcionDepartamentoChatBot.objects.filter(
        departamento=dpto, status=True, tipo_nodo='http', endpoint__isnull=False,
    ).values_list('endpoint_id', flat=True).distinct().count()

    return JsonResponse({
        'error': False,
        'data': {
            'id': dpto.id,
            'nombre': dpto.nombre,
            'color': dpto.color,
            'mensaje_saludo': dpto.mensaje_saludo or '',
            'palabras_clave': palabras,
            'es_default': bool(dpto.es_default),
            'activo_tradicional': bool(dpto.activo_tradicional),
            'count_opciones': count_opciones,
            'count_conexiones': count_conexiones,
            'count_endpoints': count_endpoints,
            'count_usuarios': count_usuarios,
            'nombre_sugerido': f"{dpto.nombre} - COPIA",
        },
    })


def _duplicar_departamento(request):
    """Action: duplicar. Clona DepartamentoChatBot completo:
      1. Nuevo Departamento con los mismos campos (es_default forzado a False).
      2. Clona OpcionDepartamentoChatBot manteniendo árbol (opcion_padre).
      3. Clona ConexionNodoChatbot remapeando origen/destino.
      4. Clona PerfilDepartamentoChatBot (asignaciones de usuarios)."""
    try:
        dpto_id = int(request.POST.get('id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': True, 'message': 'ID inválido.'})

    dpto = DepartamentoChatBot.objects.filter(pk=dpto_id, status=True).first()
    if not dpto:
        return JsonResponse({'error': True, 'message': 'Departamento no encontrado.'})

    nuevo_nombre = (request.POST.get('nuevo_nombre') or '').strip() or f"{dpto.nombre} - COPIA"
    if len(nuevo_nombre) > 100:
        nuevo_nombre = nuevo_nombre[:100]

    with transaction.atomic():
        nuevo = DepartamentoChatBot(
            nombre=nuevo_nombre,
            color=dpto.color,
            mensaje_saludo=dpto.mensaje_saludo,
            palabras_clave=dpto.palabras_clave,
            es_default=False,  # nunca duplicar el default; evita conflicto de ruteo
            activo_tradicional=dpto.activo_tradicional,
            # Reset configurable: viaja igual al clon. Lo único que no se copia
            # es el HistorialMovimientoNodo (auditoría del original; el clon
            # arranca con historial vacío).
            reset_triggers=list(dpto.reset_triggers or []),
            mensaje_reset=dpto.mensaje_reset or '',
        )
        nuevo.save(request)

        # Pase 1 — clonar nodos sin opcion_padre (lo seteamos en pase 2 con el mapeo)
        nodos_origen = list(OpcionDepartamentoChatBot.objects.filter(
            departamento=dpto, status=True,
        ).order_by('id'))
        mapeo_nodos = {}  # old_id → new_node
        for n in nodos_origen:
            nuevo_nodo = OpcionDepartamentoChatBot(
                departamento=nuevo,
                orden=n.orden,
                nombre=n.nombre,
                respuesta=n.respuesta,
                opcion_padre=None,
                boton_id=n.boton_id,
                tipo_nodo=n.tipo_nodo,
                es_inicio=n.es_inicio,
                config=n.config or {},
                endpoint=n.endpoint,  # endpoints son compartidos, no se clonan
                variable_destino=n.variable_destino,
                validacion_tipo=n.validacion_tipo,
                validacion_expresion=n.validacion_expresion,
                mensaje_error=n.mensaje_error,
                reintentos_max=n.reintentos_max,
                posicion_x=n.posicion_x,
                posicion_y=n.posicion_y,
            )
            nuevo_nodo.save(request)
            mapeo_nodos[n.id] = nuevo_nodo

        # Pase 2 — setear opcion_padre con el mapeo
        for n in nodos_origen:
            if n.opcion_padre_id and n.opcion_padre_id in mapeo_nodos:
                nuevo_nodo = mapeo_nodos[n.id]
                nuevo_nodo.opcion_padre = mapeo_nodos[n.opcion_padre_id]
                nuevo_nodo.save(request)

        # Pase 3 — clonar conexiones del grafo
        conexiones = ConexionNodoChatbot.objects.filter(
            nodo_origen__departamento=dpto, status=True,
        )
        count_conex_clonadas = 0
        for c in conexiones:
            origen_new = mapeo_nodos.get(c.nodo_origen_id)
            destino_new = mapeo_nodos.get(c.nodo_destino_id)
            if not origen_new or not destino_new:
                continue
            ConexionNodoChatbot(
                nodo_origen=origen_new,
                nodo_destino=destino_new,
                etiqueta=c.etiqueta,
                orden=c.orden,
                descripcion=c.descripcion,
            ).save(request)
            count_conex_clonadas += 1

        # Pase 4 — clonar usuarios asignados
        perfiles = PerfilDepartamentoChatBot.objects.filter(
            departamento=dpto, status=True,
        )
        count_usuarios_clonados = 0
        for p in perfiles:
            PerfilDepartamentoChatBot(
                departamento=nuevo,
                usuario=p.usuario,
            ).save(request)
            count_usuarios_clonados += 1

    log(
        f"Duplicó departamento '{dpto.nombre}' → '{nuevo.nombre}' "
        f"({len(mapeo_nodos)} nodos, {count_conex_clonadas} conexiones, "
        f"{count_usuarios_clonados} usuarios)",
        request, "add", obj=nuevo.id,
    )
    return JsonResponse({
        'error': False,
        'departamento_id': nuevo.id,
        'departamento_nombre': nuevo.nombre,
        'nodos': len(mapeo_nodos),
        'conexiones': count_conex_clonadas,
        'usuarios': count_usuarios_clonados,
        'mensaje': f"Departamento duplicado como '{nuevo.nombre}'.",
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
    ).select_related('endpoint', 'endpoint__credencial').only(
        'id', 'nombre', 'orden', 'tipo_nodo', 'es_inicio', 'opcion_padre_id',
        'boton_id', 'respuesta', 'config', 'endpoint_id', 'variable_destino',
        'validacion_tipo', 'validacion_expresion', 'mensaje_error', 'reintentos_max',
        'departamento_id',
        'endpoint__id', 'endpoint__nombre', 'endpoint__base_url',
        'endpoint__credencial__id', 'endpoint__credencial__nombre',
        'endpoint__credencial__tipo',
    )
    nodos_by_id = {n.id: n for n in nodos_qs}
    if not nodos_by_id:
        return []

    hijos_legacy_por_padre = {}
    for n in nodos_by_id.values():
        if n.opcion_padre_id:
            hijos_legacy_por_padre.setdefault(n.opcion_padre_id, []).append(n)
    for lst in hijos_legacy_por_padre.values():
        lst.sort(key=lambda x: (x.orden, x.id))

    conex_qs = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=departamento, status=True,
    ).select_related('nodo_destino', 'nodo_origen').only(
        'id', 'nodo_origen_id', 'nodo_destino_id', 'etiqueta', 'orden', 'descripcion',
        'nodo_destino__id', 'nodo_destino__nombre', 'nodo_destino__tipo_nodo',
        'nodo_origen__id', 'nodo_origen__nombre', 'nodo_origen__tipo_nodo',
    ).order_by('nodo_origen', 'orden', 'id')
    conex_by_origen_etq = {}
    for c in conex_qs:
        conex_by_origen_etq.setdefault(c.nodo_origen_id, {}).setdefault(c.etiqueta or '', c)

    def _destino(op_id, etiqueta):
        c = conex_by_origen_etq.get(op_id, {}).get(etiqueta)
        return nodos_by_id.get(c.nodo_destino_id) if c else None

    def _siguiente_default(op_id):
        salidas = conex_by_origen_etq.get(op_id, {})
        for et in ('', 'ok'):
            c = salidas.get(et)
            if c:
                return nodos_by_id.get(c.nodo_destino_id)
        return None

    items = []
    visited = set()

    def _walk(op, lvl):
        if op.id in visited:
            return
        visited.add(op.id)
        items.append({'opcion': op, 'nivel': lvl})
        cfg = op.config or {}
        salidas_grafo = conex_by_origen_etq.get(op.id, {})
        if op.tipo_nodo == 'menu':
            for opt in (cfg.get('opciones') or []):
                sal = (opt.get('salida') or '').strip()
                dest = _destino(op.id, sal) if sal else _siguiente_default(op.id)
                if dest:
                    _walk(dest, lvl + 1)
            if not salidas_grafo:
                for c in hijos_legacy_por_padre.get(op.id, []):
                    _walk(c, lvl + 1)
        elif op.tipo_nodo == 'condicional':
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

    inicio = next((n for n in nodos_by_id.values() if n.es_inicio), None)
    if not inicio:
        sin_padre = [n for n in nodos_by_id.values() if not n.opcion_padre_id]
        sin_padre.sort(key=lambda x: (x.orden, x.id))
        inicio = sin_padre[0] if sin_padre else None
    if inicio:
        _walk(inicio, 0)

    for n in sorted(nodos_by_id.values(), key=lambda x: (x.orden, x.id)):
        if n.id not in visited:
            items.append({'opcion': n, 'nivel': 0})
            visited.add(n.id)
    return items


def _exportar_flujo_completo(departamento):
    """Snapshot completo del flujo en JSON estructurado.

    Incluye: cabecera del depto, todos los nodos con su config completo,
    todas las conexiones (nodo_origen, nodo_destino, etiqueta), endpoints
    y credenciales referenciados (con secretos REDACTED), y stats agregadas.

    Útil como "ficha técnica" del bot, para auditar configuración antes
    de pasar a producción, o para versionar/exportar entre ambientes.
    """
    from .models import ConexionNodoChatbot
    from datetime import datetime

    nodos_qs = OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, status=True,
    ).select_related('endpoint', 'endpoint__credencial').order_by('orden', 'id')
    conex_qs = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=departamento, status=True,
    ).select_related('nodo_origen', 'nodo_destino').order_by('nodo_origen', 'orden')

    # Recetas de cómo cada tipo de credencial inyecta auth en la request.
    # Útil como documentación cuando alguien arma un seed nuevo.
    USO_AUTH = {
        'none': {
            'descripcion': 'Sin autenticación. El motor no agrega headers extra.',
            'ejemplo': 'Endpoint público (AllowAny).',
            'secretos_esperados': {},
        },
        'bearer': {
            'descripcion': 'Inyecta header Authorization: Bearer <token> en cada request.',
            'ejemplo': '{"token": "eyJhbGciOiJIUzI1NiIs..."}',
            'secretos_esperados': {'token': '<jwt o bearer token>'},
        },
        'basic': {
            'descripcion': 'Inyecta Authorization: Basic base64(usuario:password).',
            'ejemplo': '{"usuario": "api_user", "password": "secret123"}',
            'secretos_esperados': {'usuario': '<user>', 'password': '<pass>'},
        },
        'apikey_header': {
            'descripcion': 'Agrega un header custom con la API key.',
            'ejemplo': '{"nombre_header": "X-API-Key", "valor": "abc123"}',
            'secretos_esperados': {'nombre_header': '<nombre del header>',
                                   'valor': '<api key>'},
        },
        'apikey_query': {
            'descripcion': 'Agrega un query param con la API key.',
            'ejemplo': '{"nombre_param": "api_key", "valor": "abc123"}',
            'secretos_esperados': {'nombre_param': '<nombre del param>',
                                   'valor': '<api key>'},
        },
        'custom_header': {
            'descripcion': 'Mergea un dict de headers personalizados en la request.',
            'ejemplo': '{"headers": {"X-Tenant": "ru", "X-Trace": "abc"}}',
            'secretos_esperados': {'headers': '<dict de headers>'},
        },
    }

    # Endpoints únicos referenciados por nodos http
    endpoints_usados = {}
    creds_usadas = {}
    for n in nodos_qs:
        if n.endpoint and n.endpoint.id not in endpoints_usados:
            ep = n.endpoint
            endpoints_usados[ep.id] = {
                'id': ep.id,
                'nombre': ep.nombre,
                'base_url': ep.base_url,
                'headers_default': ep.headers_default or {},
                'timeout_seg': ep.timeout_seg,
                'descripcion': ep.descripcion or '',
                'credencial_id': ep.credencial_id,
            }
            if ep.credencial and ep.credencial.id not in creds_usadas:
                cr = ep.credencial
                # Secretos REDACTED — exponer solo las claves, no los valores.
                secretos_redacted = {
                    k: '***REDACTED***' for k in (cr.secretos or {})
                }
                receta = USO_AUTH.get(cr.tipo, USO_AUTH['none'])
                creds_usadas[cr.id] = {
                    'id': cr.id,
                    'nombre': cr.nombre,
                    'tipo': cr.tipo,
                    'tipo_display': cr.get_tipo_display(),
                    'secretos': secretos_redacted,
                    'descripcion': cr.descripcion or '',
                    'uso_auth': receta['descripcion'],
                    'secretos_esperados': receta['secretos_esperados'],
                    'ejemplo_secretos': receta['ejemplo'],
                }

    # Stats agregadas
    tipos_count = {}
    for n in nodos_qs:
        tipos_count[n.tipo_nodo] = tipos_count.get(n.tipo_nodo, 0) + 1
    nodo_inicio = next((n for n in nodos_qs if n.es_inicio), None)
    sin_entrada = []  # nodos no alcanzables (sin conexión entrante y no inicio)
    destinos = set(c.nodo_destino_id for c in conex_qs)
    for n in nodos_qs:
        if n.id not in destinos and not n.es_inicio:
            sin_entrada.append({'id': n.id, 'nombre': n.nombre, 'tipo': n.tipo_nodo})

    return {
        '_meta': {
            'exportado_en': datetime.now().isoformat(timespec='seconds'),
            'version_schema': '1.0',
            'nota': 'Secretos de credenciales aparecen como ***REDACTED***',
        },
        '_help': {
            'cookbook': 'Cómo replicar este flujo en un seed Python (estilo seed_ru.py).',
            'imports': (
                "from crm.models import (DepartamentoChatBot, OpcionDepartamentoChatBot,"
                " ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot)"
            ),
            'pasos': [
                '1. Crear DepartamentoChatBot con `nombre`, `color`, `mensaje_saludo`, `palabras_clave`.',
                '2. Crear CredencialApiChatbot con `tipo` y `secretos` (ver `secretos_esperados` por tipo).',
                '3. Crear EndpointApiChatbot con `base_url`, `credencial`, `headers_default`, `timeout_seg`.',
                '4. Crear OpcionDepartamentoChatBot por nodo (tipo + config). Setear `es_inicio=True` en el primero.',
                '5. Crear ConexionNodoChatbot por arista. Etiqueta vacía = default; "ok"/"error" para http; "true"/"false" para condicional; "<salida>" para opciones de menú.',
            ],
            'snippet_endpoint': (
                "credencial = CredencialApiChatbot.objects.create(\n"
                "    nombre='Mi API', tipo='bearer',\n"
                "    secretos={'token': 'eyJhbGc...'},\n"
                ")\n"
                "endpoint = EndpointApiChatbot.objects.create(\n"
                "    nombre='Mi API', base_url='https://api.x.com',\n"
                "    credencial=credencial,\n"
                "    headers_default={'Accept': 'application/json'},\n"
                "    timeout_seg=15,\n"
                ")"
            ),
            'snippet_nodo_http': (
                "OpcionDepartamentoChatBot.objects.create(\n"
                "    departamento=depto, tipo_nodo='http', endpoint=endpoint,\n"
                "    config={\n"
                "        'metodo': 'POST', 'path': '/buscar/',\n"
                "        'body': {'cedula': '{{variables.cedula}}'},\n"
                "        'extraer': [\n"
                "            {'variable': 'nombre', 'jsonpath': 'data.nombre'},\n"
                "            {'variable': 'lista',  'jsonpath': 'data.items'},\n"
                "        ],\n"
                "        'plantilla_respuesta': (\n"
                "            'Hola {{variables.nombre}}\\n'\n"
                "            '{% for it in variables.lista %}'\n"
                "            '• {{it.titulo}}\\n'\n"
                "            '{% endfor %}'\n"
                "        ),\n"
                "    },\n"
                ")"
            ),
            'tips_template': [
                "{{variables.X}} para sustitución escalar.",
                "{{var.objeto.campo}} y {{var.lista[0].campo}} para navegar paths.",
                "{% for x in variables.lista %}...{% endfor %} para iterar listas.",
                "Si la API responde {success: false} el motor enruta por etiqueta 'error' (mostrar mensaje de error en vez de plantilla_respuesta).",
            ],
            'tipos_auth_disponibles': USO_AUTH,
        },
        'departamento': {
            'id': departamento.id,
            'nombre': departamento.nombre,
            'color': departamento.color or '',
            'mensaje_saludo': departamento.mensaje_saludo or '',
            'palabras_clave': departamento.get_palabras_clave(),
            'es_default': bool(departamento.es_default),
            'activo_tradicional': bool(departamento.activo_tradicional),
            'reset_triggers': departamento.get_reset_triggers(),
            'mensaje_reset': departamento.mensaje_reset or '',
        },
        'estadisticas': {
            'total_nodos': nodos_qs.count(),
            'total_conexiones': conex_qs.count(),
            'nodos_por_tipo': tipos_count,
            'nodo_inicio': {
                'id': nodo_inicio.id, 'nombre': nodo_inicio.nombre,
                'tipo': nodo_inicio.tipo_nodo,
            } if nodo_inicio else None,
            'nodos_huerfanos': sin_entrada,
            'endpoints_usados': len(endpoints_usados),
            'credenciales_usadas': len(creds_usadas),
        },
        'endpoints': list(endpoints_usados.values()),
        'credenciales': list(creds_usadas.values()),
        'nodos': [
            {
                'id': n.id,
                'nombre': n.nombre,
                'tipo_nodo': n.tipo_nodo,
                'tipo_display': n.get_tipo_display() if hasattr(n, 'get_tipo_display') else n.tipo_nodo,
                'orden': n.orden,
                'es_inicio': bool(n.es_inicio),
                'opcion_padre_id': n.opcion_padre_id,
                'boton_id': n.boton_id or '',
                'respuesta': n.respuesta or '',
                'config': n.config or {},
                'endpoint_id': n.endpoint_id,
                'variable_destino': n.variable_destino or '',
                'validacion_tipo': n.validacion_tipo or 'none',
                'validacion_expresion': n.validacion_expresion or '',
                'mensaje_error': n.mensaje_error or '',
                'reintentos_max': n.reintentos_max or 3,
            }
            for n in nodos_qs
        ],
        'conexiones': [
            {
                'origen_id': c.nodo_origen_id,
                'origen_nombre': c.nodo_origen.nombre,
                'destino_id': c.nodo_destino_id,
                'destino_nombre': c.nodo_destino.nombre,
                'etiqueta': c.etiqueta or '',
                'orden': c.orden,
                'descripcion': c.descripcion or '',
            }
            for c in conex_qs
        ],
    }


def _serializar_para_preview(departamento):
    """Devuelve un grafo plano para el simulador WhatsApp tipo state-machine.

    El JS del preview recorre `nodos[current_id]` paso a paso, evaluando el
    `tipo` del nodo y siguiendo `salidas` por etiqueta. Soporta:
      - menu → renderiza opciones, espera click, avanza por `salida`.
      - pregunta → input de texto, captura en `variable_destino`, avanza ''.
      - http → modo mock (placeholder) o modo real (llama a /probar_http/).
      - condicional → evalúa local con operadores básicos, avanza true/false.
      - set_variable → aplica asignaciones, avanza ''.
      - respuesta/cta_url/ubicacion/handoff/fin → comportamiento estándar.
    """
    from .models import ConexionNodoChatbot

    nodos_qs = list(OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, status=True,
    ))

    hijos_legacy_por_padre = {}
    for n in sorted(nodos_qs, key=lambda x: (x.orden, x.id)):
        if n.opcion_padre_id:
            hijos_legacy_por_padre.setdefault(n.opcion_padre_id, []).append(n.id)

    conex_qs = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=departamento, status=True,
    ).order_by('nodo_origen', 'orden', 'id')
    salidas_by_origen = {}
    for c in conex_qs:
        salidas_by_origen.setdefault(c.nodo_origen_id, []).append({
            'etiqueta': c.etiqueta or '',
            'destino_id': c.nodo_destino_id,
        })

    nodos = {}
    for n in nodos_qs:
        nodos[str(n.id)] = {
            'id': n.id,
            'nombre': n.nombre or '',
            'tipo': n.tipo_nodo,
            'config': n.config or {},
            'respuesta': n.respuesta or '',
            'es_inicio': bool(n.es_inicio),
            'endpoint_id': n.endpoint_id or None,
            'variable_destino': n.variable_destino or '',
            'validacion_tipo': n.validacion_tipo or 'none',
            'salidas': salidas_by_origen.get(n.id, []),
            'hijos_legacy': hijos_legacy_por_padre.get(n.id, []),
        }

    inicio = next((n for n in nodos_qs if n.es_inicio), None)
    if not inicio:
        sin_padre = [n for n in nodos_qs if not n.opcion_padre_id]
        sin_padre.sort(key=lambda x: (x.orden, x.id))
        inicio = sin_padre[0] if sin_padre else None

    return {
        'departamento': {
            'id': departamento.id,
            'nombre': departamento.nombre,
            'color': departamento.color or '#16a34a',
            'mensaje_saludo': departamento.mensaje_saludo or '',
        },
        'nodos': nodos,
        'inicio_id': inicio.id if inicio else None,
    }


def _resumen_accion_nodo(n):
    """Resumen corto de QUÉ ejecuta el nodo, para el subtítulo en el diagrama.
    Se calcula desde `tipo_nodo` + `config` para que el editor visual muestre
    la acción real sin tener que abrir cada nodo."""
    cfg = n.config or {}
    t = n.tipo_nodo
    if t == 'http':
        base = f"{cfg.get('metodo') or 'GET'} {cfg.get('path') or ''}".strip()
        if n.endpoint_id and getattr(n, 'endpoint', None):
            base = f"{base} · {n.endpoint.nombre}".strip(' ·')
        return base or 'Llamada HTTP'
    if t == 'funcion':
        return 'fn: ' + (cfg.get('funcion_codigo') or '—')
    if t == 'condicional':
        conds = cfg.get('condiciones') or []
        return f"{len(conds)} condición(es) · {(cfg.get('operador') or 'and').upper()}"
    if t == 'set_variable':
        return f"{len(cfg.get('asignaciones') or [])} asignación(es)"
    if t == 'menu':
        fuente = cfg.get('opciones_fuente') or {}
        if fuente.get('variable'):
            return 'opciones desde ' + fuente['variable']
        n_inline = len(cfg.get('opciones') or [])
        if n_inline:
            return f"{n_inline} opción(es) inline"
        return 'botones desde hijos'
    if t == 'cta_url':
        return (cfg.get('display_text') or 'Botón') + ' → URL externa'
    if t == 'ubicacion':
        return cfg.get('name') or 'Ubicación / mapa'
    if t == 'handoff':
        return 'Deriva a asesor humano'
    if t == 'agenda_turno':
        sub = {'reservar': 'Reservar', 'cancelar': 'Cancelar', 'reagendar': 'Reagendar'}
        return 'Agenda: ' + sub.get((cfg.get('sub_action') or 'reservar'), 'Reservar')
    if t == 'loop':
        return 'Itera ' + str(cfg.get('iterations_expr') or '?')
    if t == 'pregunta':
        return ('Guarda → ' + n.variable_destino) if n.variable_destino else 'Pregunta al usuario'
    if t == 'fin':
        return 'Cierra la conversación'
    if t == 'respuesta':
        return 'Texto + botón URL' if cfg.get('cta_url') else 'Envía texto'
    return ''


def _flags_nodo(n):
    """Banderas/badges cortos para el subtítulo (efectos colaterales)."""
    cfg = n.config or {}
    flags = []
    if cfg.get('envia_correo'):
        flags.append('correo')
    if cfg.get('notificar_asesor'):
        flags.append('asesor')
    if n.variable_destino and n.tipo_nodo not in ('pregunta',):
        flags.append('→' + n.variable_destino)
    if n.validacion_tipo and n.validacion_tipo != 'none':
        flags.append(n.validacion_tipo)
    return flags


def _serializar_para_canvas(departamento):
    """Grafo para el editor visual (Drawflow). A diferencia del preview, expone
    `x`/`y` por nodo y un `conexion_id` por salida para edición directa.

    Las aristas combinan el grafo moderno (`ConexionNodoChatbot`) con el árbol
    legacy (`opcion_padre`) para que flujos viejos también se vean conectados.
    """
    from .models import ConexionNodoChatbot

    TIPOS_NODO = OpcionDepartamentoChatBot.TIPOS_NODO

    nodos_qs = list(OpcionDepartamentoChatBot.objects.filter(
        departamento=departamento, status=True,
    ).select_related('endpoint'))
    by_id = {n.id: n for n in nodos_qs}

    conex_qs = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=departamento, status=True,
    ).order_by('nodo_origen', 'orden', 'id')

    edges = {}
    for c in conex_qs:
        edges[(c.nodo_origen_id, c.nodo_destino_id)] = {
            'conexion_id': c.id,
            'etiqueta': c.etiqueta or '',
            'destino_id': c.nodo_destino_id,
        }
    for n in sorted(nodos_qs, key=lambda x: (x.orden, x.id)):
        if n.opcion_padre_id and (n.opcion_padre_id, n.id) not in edges:
            padre = by_id.get(n.opcion_padre_id)
            etiqueta = n.nombre if (padre and padre.tipo_nodo == 'menu') else ''
            edges[(n.opcion_padre_id, n.id)] = {
                'conexion_id': None,
                'etiqueta': etiqueta,
                'destino_id': n.id,
            }

    salidas_by_origen = {}
    for (origen, _destino), e in edges.items():
        salidas_by_origen.setdefault(origen, []).append(e)

    tipo_labels = dict(TIPOS_NODO)
    nodos = []
    for n in nodos_qs:
        nodos.append({
            'id': n.id,
            'nombre': n.nombre or '',
            'tipo': n.tipo_nodo,
            'tipo_label': tipo_labels.get(n.tipo_nodo, n.tipo_nodo),
            'respuesta': (n.respuesta or '')[:140],
            'accion': _resumen_accion_nodo(n),
            'flags': _flags_nodo(n),
            'es_inicio': bool(n.es_inicio),
            'x': float(n.posicion_x or 0),
            'y': float(n.posicion_y or 0),
            'salidas': salidas_by_origen.get(n.id, []),
        })

    inicio = next((n for n in nodos_qs if n.es_inicio), None)
    if not inicio:
        sin_padre = [n for n in nodos_qs if not n.opcion_padre_id]
        sin_padre.sort(key=lambda x: (x.orden, x.id))
        inicio = sin_padre[0] if sin_padre else None

    return {
        'departamento': {
            'id': departamento.id,
            'nombre': departamento.nombre,
            'color': departamento.color or '#16a34a',
            'activo_tradicional': bool(departamento.activo_tradicional),
        },
        'nodos': nodos,
        'inicio_id': inicio.id if inicio else None,
        'tipos': [{'value': v, 'label': l} for v, l in TIPOS_NODO],
    }


def _serializar_para_preview_LEGACY(departamento):
    """Versión nested anterior. Deprecada — el preview ahora usa flat map."""
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
    ).select_related('endpoint', 'endpoint__credencial').only(
        'id', 'nombre', 'orden', 'tipo_nodo', 'es_inicio', 'opcion_padre_id',
        'boton_id', 'respuesta', 'config', 'endpoint_id', 'variable_destino',
        'validacion_tipo', 'validacion_expresion', 'mensaje_error', 'reintentos_max',
        'departamento_id',
        'endpoint__id', 'endpoint__nombre',
        'endpoint__credencial__id', 'endpoint__credencial__nombre',
    )
    nodos_by_id = {n.id: n for n in nodos_qs}
    if not nodos_by_id:
        return []

    hijos_legacy_por_padre = {}
    for n in nodos_by_id.values():
        if n.opcion_padre_id:
            hijos_legacy_por_padre.setdefault(n.opcion_padre_id, []).append(n)
    for lst in hijos_legacy_por_padre.values():
        lst.sort(key=lambda x: (x.orden, x.id))

    conex_qs = ConexionNodoChatbot.objects.filter(
        nodo_origen__departamento=departamento, status=True,
    ).select_related('nodo_destino').only(
        'id', 'nodo_origen_id', 'nodo_destino_id', 'etiqueta', 'orden',
        'nodo_destino__id', 'nodo_destino__nombre', 'nodo_destino__tipo_nodo',
    ).order_by('nodo_origen', 'orden', 'id')
    conex_by_origen_etq = {}
    for c in conex_qs:
        conex_by_origen_etq.setdefault(c.nodo_origen_id, {}).setdefault(c.etiqueta or '', c)

    def _conex_etq(op_id, etiqueta):
        return conex_by_origen_etq.get(op_id, {}).get(etiqueta)

    def _conex_default(op_id):
        salidas = conex_by_origen_etq.get(op_id, {})
        return salidas.get('') or salidas.get('ok')

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
            if not hijos:
                for c in hijos_legacy_por_padre.get(op.id, []):
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

        return {'opcion': op, 'hijos': hijos, 'etiqueta': ''}

    inicio = next((n for n in nodos_by_id.values() if n.es_inicio), None)
    if not inicio:
        sin_padre = [n for n in nodos_by_id.values() if not n.opcion_padre_id]
        sin_padre.sort(key=lambda x: (x.orden, x.id))
        inicio = sin_padre[0] if sin_padre else None

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
    from agenda.models import GrupoAgenda

    pk = int(request.POST.get('pk') or 0)
    nombre = (request.POST.get('nombre') or '').strip()[:120]
    color = (request.POST.get('color') or '#6c757d').strip()[:20]
    mensaje = (request.POST.get('mensaje_saludo') or '').strip()
    palabras = (request.POST.get('palabras_clave') or '').strip()
    mensaje_reset = (request.POST.get('mensaje_reset') or '').strip()
    reset_raw = request.POST.get('reset_triggers') or ''
    reset_lista = [
        line.strip().lower()
        for line in reset_raw.splitlines()
        if line.strip()
    ]
    es_default = request.POST.get('es_default') in ('1', 'true', 'on')
    activo_tradicional = request.POST.get('activo_tradicional') in ('1', 'true', 'on')

    grupo_obj = None
    grupo_raw = (request.POST.get('grupo_agenda_id') or '').strip()
    if grupo_raw and grupo_raw not in ('0', 'null', 'none'):
        try:
            grupo_obj = GrupoAgenda.objects.filter(pk=int(grupo_raw), status=True).first()
        except (TypeError, ValueError):
            grupo_obj = None

    if pk == 0:
        if len(nombre) < 2:
            return JsonResponse({
                'ok': False,
                'error': 'El nombre necesita al menos 2 caracteres para crear el departamento.',
            })
        dep = DepartamentoChatBot(
            nombre=nombre, color=color, mensaje_saludo=mensaje,
            palabras_clave=palabras, mensaje_reset=mensaje_reset,
            reset_triggers=reset_lista, es_default=es_default,
            activo_tradicional=activo_tradicional, grupo_agenda=grupo_obj,
        )
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
    dep.palabras_clave = palabras
    dep.mensaje_reset = mensaje_reset
    dep.reset_triggers = reset_lista
    dep.es_default = es_default
    dep.activo_tradicional = activo_tradicional
    dep.grupo_agenda = grupo_obj
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
            padre_nuevo = OpcionDepartamentoChatBot.objects.filter(
                pk=int(parent_id), departamento=dep, status=True,
            ).first()
            if padre_nuevo:
                if padre_nuevo.pk == opcion.pk:
                    return JsonResponse({'ok': False, 'error': 'Un nodo no puede ser su propio padre'})
                # Anti-ciclo (solo aplica si el nodo ya existe; al crear no hay descendientes).
                if opcion.pk and _es_descendiente(opcion, padre_nuevo):
                    return JsonResponse({
                        'ok': False,
                        'error': f'Ciclo: "{padre_nuevo.nombre}" es descendiente de este nodo.',
                    })
            opcion.opcion_padre = padre_nuevo
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

    # Campos comunes a todos los tipos (variable_destino, validacion_*,
    # mensaje_error, reintentos_max). Si el form no los manda, preservamos
    # el valor actual; si manda vacío, se aplica vacío.
    if 'variable_destino' in request.POST:
        opcion.variable_destino = (request.POST.get('variable_destino') or '').strip()[:80]
    if 'validacion_tipo' in request.POST:
        vt = (request.POST.get('validacion_tipo') or 'none').strip()
        opcion.validacion_tipo = vt if vt in VALIDACIONES_VALIDAS else 'none'
    if 'validacion_expresion' in request.POST:
        opcion.validacion_expresion = (request.POST.get('validacion_expresion') or '').strip()[:250]
    if 'mensaje_error' in request.POST:
        opcion.mensaje_error = (request.POST.get('mensaje_error') or '').strip()
    if 'reintentos_max' in request.POST:
        try:
            opcion.reintentos_max = max(0, min(99, int(request.POST.get('reintentos_max') or 3)))
        except (TypeError, ValueError):
            opcion.reintentos_max = 3
    for coord in ('posicion_x', 'posicion_y'):
        if coord in request.POST:
            try:
                setattr(opcion, coord, float(request.POST.get(coord) or 0))
            except (TypeError, ValueError):
                pass

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
        if request.POST.get('envia_correo'):
            cfg['envia_correo'] = True
        if request.POST.get('http_enviar_respuesta_en_error'):
            cfg['enviar_respuesta_en_error'] = True
        timeout_raw = (request.POST.get('http_timeout_seg') or '').strip()
        if timeout_raw:
            try:
                cfg['timeout_seg'] = max(1, min(120, int(timeout_raw)))
            except (TypeError, ValueError):
                pass
        opcion.config = cfg
    elif opcion.tipo_nodo == 'menu':
        cfg = dict(opcion.config or {})

        etiquetas_opt = (request.POST.getlist('menu_opt_etiqueta[]')
                         or request.POST.getlist('menu_opt_etiqueta'))
        valores_opt = (request.POST.getlist('menu_opt_valor[]')
                       or request.POST.getlist('menu_opt_valor'))
        salidas_opt = (request.POST.getlist('menu_opt_salida[]')
                       or request.POST.getlist('menu_opt_salida'))
        opciones_inline = []
        for et, val, sal in zip(etiquetas_opt, valores_opt, salidas_opt):
            et_s = (et or '').strip()
            val_s = (val or '').strip()
            sal_s = (sal or '').strip()
            if not et_s and not val_s:
                continue
            opciones_inline.append({
                'etiqueta': et_s,
                'valor': val_s,
                'salida': sal_s or val_s,
            })
        if opciones_inline:
            cfg['opciones'] = opciones_inline
        else:
            cfg.pop('opciones', None)

        var = (request.POST.get('menu_fuente_variable') or '').strip()
        if var:
            fuente = {
                'variable':       var,
                'campo_id':       (request.POST.get('menu_fuente_campo_id') or 'id').strip() or 'id',
                'campo_etiqueta': (request.POST.get('menu_fuente_campo_etiqueta') or 'nombre').strip() or 'nombre',
                'salida':         (request.POST.get('menu_fuente_salida') or '').strip(),
            }
            limite_raw = (request.POST.get('menu_fuente_limite') or '').strip()
            if limite_raw.isdigit():
                fuente['limite'] = int(limite_raw)
            cfg['opciones_fuente'] = fuente
        else:
            cfg.pop('opciones_fuente', None)

        # Atajo "valor por defecto": el menú muestra solo Sí/Otra. Si todos
        # los campos relevantes están vacíos, removemos la key entera para
        # que el motor caiga al menú normal sin marcador residual.
        default_valor = (request.POST.get('menu_default_valor') or '').strip()
        if default_valor:
            cfg['opcion_default'] = {
                'valor':           default_valor,
                'etiqueta':        (request.POST.get('menu_default_etiqueta') or '').strip(),
                'pregunta':        (request.POST.get('menu_default_pregunta') or '').strip(),
                'etiqueta_si':     (request.POST.get('menu_default_etiqueta_si') or '').strip(),
                'etiqueta_otra':   (request.POST.get('menu_default_etiqueta_otra') or '').strip(),
                'salida_si':       (request.POST.get('menu_default_salida_si') or '').strip(),
                'salida_otra':     (request.POST.get('menu_default_salida_otra') or '').strip(),
            }
        else:
            cfg.pop('opcion_default', None)
        for k in ('pregunta', 'url', 'display_text',
                  'lat', 'lng', 'name', 'address', 'meta_type',
                  'metodo', 'path', 'plantilla_respuesta'):
            cfg.pop(k, None)
        cfg['mensaje'] = opcion.respuesta
        opcion.config = cfg
        opcion.endpoint = None
    elif opcion.tipo_nodo == 'condicional':
        cfg = {}
        raw = (request.POST.get('cond_condiciones_json') or '').strip()
        if raw:
            try:
                conds = json.loads(raw)
            except (TypeError, ValueError) as ex:
                return JsonResponse({'ok': False, 'error': f'Condiciones JSON inválido: {str(ex)[:120]}'})
            if not isinstance(conds, list):
                return JsonResponse({'ok': False, 'error': 'Condiciones debe ser array JSON'})
            cfg['condiciones'] = conds
        operador = (request.POST.get('cond_operador') or 'and').strip().lower()
        cfg['operador'] = operador if operador in ('and', 'or') else 'and'
        opcion.config = cfg
        opcion.endpoint = None
    elif opcion.tipo_nodo == 'set_variable':
        cfg = {}
        raw = (request.POST.get('setvar_asignaciones_json') or '').strip()
        if raw:
            try:
                asigs = json.loads(raw)
            except (TypeError, ValueError) as ex:
                return JsonResponse({'ok': False, 'error': f'Asignaciones JSON inválido: {str(ex)[:120]}'})
            if not isinstance(asigs, list):
                return JsonResponse({'ok': False, 'error': 'Asignaciones debe ser array JSON'})
            cfg['asignaciones'] = asigs
        opcion.config = cfg
        opcion.endpoint = None
    elif opcion.tipo_nodo == 'funcion':
        # Función Python registrada — análogo a HTTP pero sin URL: el código
        # registrado se invoca directo. `endpoint` es opcional (algunas
        # funciones lo necesitan para outbound HTTP, otras no).
        codigo = (request.POST.get('funcion_codigo') or '').strip()
        if not codigo:
            return JsonResponse({'ok': False, 'error': 'funcion_codigo es requerido para tipo Función'})

        cfg = {'funcion_codigo': codigo}

        # Body opcional como JSON con templates.
        body_raw = (request.POST.get('funcion_body') or '').strip()
        if body_raw:
            try:
                body = json.loads(body_raw)
            except (TypeError, ValueError) as ex:
                return JsonResponse({'ok': False, 'error': f'Body JSON inválido: {str(ex)[:120]}'})
            cfg['body'] = body

        # Extraer (variable + jsonpath) — mismo formato que http.
        extr_raw = (request.POST.get('funcion_extraer') or '').strip()
        if extr_raw:
            try:
                extr = json.loads(extr_raw)
            except (TypeError, ValueError) as ex:
                return JsonResponse({'ok': False, 'error': f'Extraer JSON inválido: {str(ex)[:120]}'})
            if not isinstance(extr, list):
                return JsonResponse({'ok': False, 'error': 'Extraer debe ser array JSON'})
            cfg['extraer'] = extr

        try:
            cfg['timeout_seg'] = int(request.POST.get('funcion_timeout') or 30)
        except (TypeError, ValueError):
            cfg['timeout_seg'] = 30

        if request.POST.get('funcion_envia_correo'):
            cfg['envia_correo'] = True

        plantilla_fn = (request.POST.get('funcion_plantilla') or '').strip()
        if plantilla_fn:
            cfg['plantilla_respuesta'] = plantilla_fn
        if request.POST.get('funcion_enviar_respuesta_en_error'):
            cfg['enviar_respuesta_en_error'] = True

        opcion.config = cfg
        # endpoint es FK ya tomado del select del form (se asigna en el bloque
        # general de guardado del form, no acá). Aceptar 0/empty como None.
        ep_raw = (request.POST.get('endpoint') or '').strip()
        if ep_raw and ep_raw not in ('0', '', 'null'):
            try:
                ep = EndpointApiChatbot.objects.filter(pk=int(ep_raw), status=True).first()
                opcion.endpoint = ep
            except (TypeError, ValueError):
                opcion.endpoint = None
        else:
            opcion.endpoint = None
    elif opcion.tipo_nodo == 'agenda_turno':
        # Nodo de agenda: solo elige la sub-acción. La agenda concreta
        # (servicios/recursos/horarios) se configura a nivel de sesión vía
        # `grupo_agenda`. Salidas típicas: vacío (ok), `cancelado`.
        sub = (request.POST.get('agenda_sub_action') or 'reservar').strip().lower()
        if sub not in ('reservar', 'cancelar', 'reagendar'):
            sub = 'reservar'
        opcion.config = {'sub_action': sub}
        opcion.endpoint = None
    elif opcion.tipo_nodo == 'loop':
        # Bucle: itera N veces. Salidas: `body` (cada iteración) y `done`
        # (al terminar). `index_var` expone el contador a los nodos del cuerpo.
        cfg = {}
        iter_expr = (request.POST.get('loop_iterations_expr') or '').strip()
        cfg['iterations_expr'] = iter_expr
        cfg['index_var'] = (request.POST.get('loop_index_var') or 'i').strip() or 'i'
        try:
            cfg['base_index'] = int(request.POST.get('loop_base_index') or 1)
        except (TypeError, ValueError):
            cfg['base_index'] = 1
        cfg['body_label'] = (request.POST.get('loop_body_label') or 'body').strip() or 'body'
        cfg['done_label'] = (request.POST.get('loop_done_label') or 'done').strip() or 'done'
        opcion.config = cfg
        opcion.endpoint = None
    else:
        # Tipos sin form específico (respuesta, pregunta, fin, handoff) →
        # el textarea "Mensaje al cliente" se guarda en `opcion.respuesta`
        # pero el motor lee primero `config.mensaje` / `config.pregunta`.
        # Sincronizamos para que la edición del UI llegue al runtime sin
        # quedar desfasada respecto al config sembrado.
        if opcion.config and (
            'url' in opcion.config or 'lat' in opcion.config or 'meta_type' in opcion.config
            or 'metodo' in opcion.config or 'path' in opcion.config
        ):
            opcion.config = {}
        elif not opcion.config:
            opcion.config = {}

        cfg = dict(opcion.config or {})
        if opcion.tipo_nodo in ('respuesta', 'fin', 'handoff'):
            cfg['mensaje'] = opcion.respuesta
            cfg.pop('pregunta', None)
        elif opcion.tipo_nodo == 'pregunta':
            cfg['pregunta'] = opcion.respuesta
            cfg.pop('mensaje', None)
        if opcion.tipo_nodo == 'respuesta':
            resp_cta_url = (request.POST.get('respuesta_cta_url') or '').strip()
            resp_cta_text = (request.POST.get('respuesta_cta_display_text') or '').strip()[:20]
            if resp_cta_url:
                cfg['cta_url'] = resp_cta_url
                cfg['cta_display_text'] = resp_cta_text or 'Abrir'
            else:
                cfg.pop('cta_url', None)
                cfg.pop('cta_display_text', None)
        opcion.config = cfg
        if opcion.tipo_nodo != 'http':
            opcion.endpoint = None

    cfg_universal = dict(opcion.config or {})
    if request.POST.get('notificar_asesor'):
        cfg_universal['notificar_asesor'] = True
        msg_asesor = (request.POST.get('mensaje_asesor') or '').strip()
        if msg_asesor:
            cfg_universal['mensaje_asesor'] = msg_asesor[:1000]
        else:
            cfg_universal.pop('mensaje_asesor', None)
    else:
        cfg_universal.pop('notificar_asesor', None)
        cfg_universal.pop('mensaje_asesor', None)
    opcion.config = cfg_universal

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

    # ── Conexiones salientes (ConexionNodoChatbot) ──────────────────
    # `salidas_json` viaja como JSON-array desde el form:
    #   [{etiqueta:"ok", destino_id:95}, {etiqueta:"error", destino_id:900}, ...]
    # Reescribimos las conexiones del nodo: borramos las que no vinieron,
    # actualizamos las existentes, creamos las nuevas. Solo pisamos si el
    # form mandó el campo (presencia explícita); si no vino, mantenemos.
    salidas_raw = request.POST.get('salidas_json')
    if salidas_raw is not None:
        try:
            salidas = json.loads(salidas_raw or '[]')
        except (TypeError, ValueError):
            salidas = None
        if isinstance(salidas, list):
            from .models import ConexionNodoChatbot
            actuales = {c.id: c for c in ConexionNodoChatbot.objects.filter(
                nodo_origen=opcion, status=True,
            )}
            ids_recibidos = set()
            for orden_idx, item in enumerate(salidas, start=1):
                if not isinstance(item, dict):
                    continue
                try:
                    destino_id = int(item.get('destino_id') or 0)
                except (TypeError, ValueError):
                    continue
                if destino_id <= 0:
                    continue
                destino = OpcionDepartamentoChatBot.objects.filter(
                    pk=destino_id, departamento=dep, status=True,
                ).first()
                if not destino:
                    continue
                etiqueta = (item.get('etiqueta') or '').strip()[:50]
                descripcion = (item.get('descripcion') or '').strip()[:200]
                conex_id = item.get('id')
                try:
                    conex_id = int(conex_id) if conex_id else None
                except (TypeError, ValueError):
                    conex_id = None
                if conex_id and conex_id in actuales:
                    c = actuales[conex_id]
                    c.nodo_destino = destino
                    c.etiqueta = etiqueta
                    c.descripcion = descripcion
                    c.orden = orden_idx
                    c.save()
                    ids_recibidos.add(conex_id)
                else:
                    nueva = ConexionNodoChatbot.objects.create(
                        nodo_origen=opcion,
                        nodo_destino=destino,
                        etiqueta=etiqueta,
                        descripcion=descripcion,
                        orden=orden_idx,
                    )
                    ids_recibidos.add(nueva.id)
            # Soft-delete de las conexiones que ya no figuran en el form.
            for cid, c in actuales.items():
                if cid not in ids_recibidos:
                    c.status = False
                    c.save()

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


def _es_descendiente(ancestro, candidato):
    """¿`candidato` está en el sub-árbol de `ancestro`? Detecta ciclos
    al cambiar el padre de un nodo."""
    visitados = set()
    pendientes = [ancestro]
    while pendientes:
        n = pendientes.pop()
        if n.pk in visitados:
            continue
        visitados.add(n.pk)
        for hijo in n.subopciones.filter(status=True):
            if hijo.pk == candidato.pk:
                return True
            pendientes.append(hijo)
    return False


def _mover_opcion(request):
    """action=mover_opcion. Reordena un nodo y/o cambia su padre.
    parent_id puede venir vacio para nodo raiz.

    Audita cada movimiento en `HistorialMovimientoNodo` con snapshot
    de hermanos antes/después para reconstruir el estado en la UI.
    """
    from .models import HistorialMovimientoNodo

    try:
        op_id = int(request.POST['opcion_id'])
    except (KeyError, ValueError):
        return JsonResponse({'ok': False, 'error': 'opcion_id requerido'})

    opcion = OpcionDepartamentoChatBot.objects.filter(pk=op_id, status=True).first()
    if not opcion:
        return JsonResponse({'ok': False, 'error': 'Nodo no encontrado'})

    # ── Snapshot ANTES del movimiento ─────────────────────────
    padre_anterior = opcion.opcion_padre
    orden_anterior = opcion.orden
    siblings_qs_antes = OpcionDepartamentoChatBot.objects.filter(
        departamento=opcion.departamento, opcion_padre=padre_anterior, status=True,
    ).order_by('orden', 'id').values('id', 'nombre', 'orden')
    siblings_antes = [
        {'id': s['id'], 'nombre': s['nombre'], 'orden': s['orden']}
        for s in siblings_qs_antes
    ]

    parent_id = request.POST.get('parent_id') or ''
    if parent_id and parent_id not in ('0', 'null', 'none'):
        try:
            padre = OpcionDepartamentoChatBot.objects.filter(
                pk=int(parent_id), departamento=opcion.departamento, status=True,
            ).first()
            if padre and padre.pk == opcion.pk:
                return JsonResponse({'ok': False, 'error': 'Un nodo no puede ser su propio padre'})
            # Anti-ciclo: el nuevo padre no puede estar dentro del sub-árbol del nodo.
            if padre and _es_descendiente(opcion, padre):
                return JsonResponse({
                    'ok': False,
                    'error': f'Ciclo detectado: "{padre.nombre}" es descendiente de "{opcion.nombre}".',
                })
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

    # ── Snapshot DESPUÉS y persistencia del historial ─────────
    padre_nuevo = opcion.opcion_padre
    siblings_qs_despues = OpcionDepartamentoChatBot.objects.filter(
        departamento=opcion.departamento, opcion_padre=padre_nuevo, status=True,
    ).order_by('orden', 'id').values('id', 'nombre', 'orden')
    siblings_despues = [
        {'id': s['id'], 'nombre': s['nombre'], 'orden': s['orden']}
        for s in siblings_qs_despues
    ]

    motivo = (request.POST.get('motivo') or '').strip()[:200]

    sin_cambio = (
        padre_anterior == padre_nuevo
        and orden_anterior == opcion.orden
        and siblings_antes == siblings_despues
    )
    if not sin_cambio:
        try:
            HistorialMovimientoNodo.objects.create(
                departamento=opcion.departamento,
                nodo=opcion,
                padre_anterior=padre_anterior,
                padre_nuevo=padre_nuevo,
                orden_anterior=orden_anterior,
                orden_nuevo=opcion.orden,
                siblings_anterior_json=siblings_antes,
                siblings_nuevo_json=siblings_despues,
                motivo=motivo,
            )
        except Exception as ex:  # noqa: BLE001 — auditoría no debe romper el move
            log(f'No se pudo persistir HistorialMovimientoNodo: {ex}')

    return JsonResponse({'ok': True, 'opcion_id': opcion.id})


def _probar_http(request):
    """action=probar_http. Ejecuta una request real con la config provista
    (sin guardar) y devuelve status, headers, body y duración. El usuario
    puede pasar `variables_test_json` para resolver `{{variables.x}}`.

    POST params:
      endpoint_id: pk del EndpointApiChatbot
      metodo, path, query_json, body_json, headers_json: tal cual el form del nodo
      variables_test_json: JSON {x: valor, y: valor} para sustituir {{variables.x}}
    """
    import time
    from .motor_flujo_chatbot import ejecutar_http, resolver_expresion

    try:
        ep_id = int(request.POST.get('endpoint_id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'endpoint_id inválido'})
    ep = EndpointApiChatbot.objects.filter(pk=ep_id, status=True).select_related('credencial').first()
    if not ep:
        return JsonResponse({'ok': False, 'error': 'Endpoint no encontrado'})

    metodo = (request.POST.get('metodo') or 'GET').upper().strip()
    path = (request.POST.get('path') or '').strip()

    def _parse(name, default):
        raw = (request.POST.get(name) or '').strip()
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as ex:
            raise ValueError(f'{name} no es JSON válido: {str(ex)[:120]}')

    try:
        query = _parse('query_json', {})
        body = _parse('body_json', None)
        headers = _parse('headers_json', {})
        variables_test = _parse('variables_test_json', {})
    except ValueError as ex:
        return JsonResponse({'ok': False, 'error': str(ex)})

    class _VirtualNode:
        def __init__(self, endpoint, config):
            self.endpoint = endpoint
            self.config = config

    cfg = {
        'metodo': metodo,
        'path': path,
        'query': query if isinstance(query, dict) else {},
        'body': body,
        'headers': headers if isinstance(headers, dict) else {},
    }
    nodo_virtual = _VirtualNode(ep, cfg)
    contexto = {'variables': variables_test if isinstance(variables_test, dict) else {}}

    url_resuelto = (ep.base_url or '').rstrip('/') + '/' + str(
        resolver_expresion(path, contexto) or ''
    ).lstrip('/')

    inicio = time.time()
    try:
        etiqueta, body_resp, status, err = ejecutar_http(nodo_virtual, contexto)
    except Exception as ex:
        return JsonResponse({
            'ok': False,
            'error': f'Excepción al ejecutar: {ex.__class__.__name__}: {str(ex)[:200]}',
            'url': url_resuelto,
        })
    duracion_ms = int((time.time() - inicio) * 1000)

    return JsonResponse({
        'ok': True,
        'url': url_resuelto,
        'metodo': metodo,
        'etiqueta': etiqueta,        # 'ok' o 'error'
        'status': status,
        'duracion_ms': duracion_ms,
        'body': body_resp,
        'error': err,
    })
