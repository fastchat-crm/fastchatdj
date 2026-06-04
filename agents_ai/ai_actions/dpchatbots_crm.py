"""Acciones IA sobre DepartamentoChatBot.

Puntos de entrada:
  - `generar(descripcion, tipo_negocio, tono, apikey_obj, usuario)` →
    crea un depto completo desde una descripción libre.
  - `explicar_flujo(depto, apikey_obj)` → genera/cachea una explicación
    narrativa del flujo de un depto existente.
  - `explicacion_esta_actualizada(depto)` → helper booleano para el editor.

La logica de validacion HTTP / construccion de respuesta se queda en la view
(`crm/view_departamento_chatbot.py`); aca solo vive la pieza IA y la persistencia.
"""
import json
import logging

from django.db import transaction
from django.utils import timezone

from .base import IAActionError, build_llm, invocar_json, log_consumo
from .prompts import get_prompt

logger = logging.getLogger(__name__)


# ============================================================================
# Persistencia del arbol generado
# ============================================================================
def _crear_opciones_recursivo(departamento, opciones_lista, parent=None,
                              orden_inicial: int = 0) -> int:
    """Crea OpcionDepartamentoChatBot en cascada respetando jerarquia del JSON IA.

    `tipo_nodo` se decide por la presencia de hijos:
      - hijos no vacios → 'menu' (presenta opciones, ESPERA input del cliente)
      - hijos vacios    → 'respuesta' (envia texto y termina la rama)

    Sin esta distincion el motor auto-recorria todo el arbol sin parar
    (manda greeting + sub-menu + opcion + respuesta-final, todo de corrido).

    `nombre` = texto del boton visible (≤100). `respuesta` = mensaje del bot.
    La IA puede devolver `texto_boton` (preferido) o `nombre`.
    """
    from crm.models import OpcionDepartamentoChatBot

    creadas = 0
    for i, op in enumerate(opciones_lista):
        if not isinstance(op, dict):
            continue
        texto = (op.get('texto_boton') or op.get('nombre') or '').strip()
        if not texto:
            continue
        respuesta_txt = (op.get('respuesta') or '').strip()
        hijos = op.get('hijos') or []
        tiene_hijos = isinstance(hijos, list) and len(hijos) > 0
        tipo = 'menu' if tiene_hijos else 'respuesta'

        # Soporte CTA URL: si la IA devuelve `cta_url` (link externo) en una
        # opción hoja, lo guardamos en `config` para que el motor lo render
        # como botón interactivo cta_url en vez de texto plano.
        config = {}
        cta_url = (op.get('cta_url') or '').strip()
        cta_display = (op.get('cta_display_text') or op.get('cta_text') or '').strip()
        if cta_url and not tiene_hijos:
            config['cta_url'] = cta_url[:2000]
            if cta_display:
                config['cta_display_text'] = cta_display[:20]

        nueva = OpcionDepartamentoChatBot.objects.create(
            departamento=departamento,
            opcion_padre=parent,
            nombre=texto[:100],
            respuesta=respuesta_txt[:2000],
            orden=orden_inicial + i,
            tipo_nodo=tipo,
            es_inicio=(parent is None and i == 0),
            usuario_creacion=departamento.usuario_creacion,
            config=config,
        )
        creadas += 1
        if tiene_hijos:
            creadas += _crear_opciones_recursivo(departamento, hijos, parent=nueva)
    return creadas


# ============================================================================
# Punto de entrada publico
# ============================================================================
def generar(*, descripcion: str, tipo_negocio: str, tono: str,
            apikey_obj, usuario) -> dict:
    """Genera un DepartamentoChatBot completo via LLM y lo persiste.

    Args:
        descripcion: descripcion del negocio (>=30 chars). Obligatorio.
        tipo_negocio: tipo opcional ('restaurante', 'clinica', etc.).
        tono: 'amable', 'formal', 'cercano', etc. Default 'amable'.
        apikey_obj: instancia ApiKeyIA validada (debe tener clave y estar activa).
        usuario: Usuario que dispara la accion (audit / FK usuario_creacion).

    Returns:
        dict con keys: departamento_id, nombre, opciones_count, tokens, modelo.

    Raises:
        IAActionError — input invalido, JSON malformado, LLM error.
    """
    from crm.models import DepartamentoChatBot

    descripcion = (descripcion or '').strip()
    tipo_negocio = (tipo_negocio or '').strip() or 'no especificado'
    tono = (tono or 'amable').strip() or 'amable'
    if len(descripcion) < 30:
        raise IAActionError("Descripcion muy corta (minimo 30 chars).")

    prompt = get_prompt(
        'dpchatbots_crm',
        descripcion=descripcion,
        tipo_negocio=tipo_negocio,
        tono=tono,
        tono_title=tono.title(),
    )

    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='dpchatbot',
        prompt_preview=descripcion[:300],
        max_tokens=16000,
        temperature=0.4,
    )

    nombre = (payload.get('nombre_departamento') or '').strip()
    if not nombre:
        raise IAActionError("La IA no devolvio nombre_departamento.")

    bienvenida = (payload.get('mensaje_bienvenida') or '').strip()
    opciones_arbol = payload.get('opciones') or []
    if not isinstance(opciones_arbol, list):
        opciones_arbol = []

    with transaction.atomic():
        depto = DepartamentoChatBot.objects.create(
            nombre=nombre,
            mensaje_saludo=bienvenida,
            activo_tradicional=True,
            usuario_creacion=usuario,
        )
        opciones_count = _crear_opciones_recursivo(depto, opciones_arbol, parent=None)

    return {
        'departamento_id': depto.id,
        'nombre': depto.nombre,
        'opciones_count': opciones_count,
        'tokens': tokens,
        'modelo': modelo,
    }


# ============================================================================
# Asistente Q&A: arma un proceso pregunta->respuesta desde respuestas guiadas
# ============================================================================
_VALIDACIONES_OK = {'none', 'email', 'numero', 'telefono', 'cedula', 'fecha', 'ruc', 'regex'}


def _crear_nodos_wizard(departamento, nodos_lista, parent=None, orden_inicial: int = 0) -> int:
    """Persiste el flujo del asistente Q&A. A diferencia del generador simple,
    respeta el `tipo` explícito de cada nodo: menu / pregunta / respuesta /
    handoff / cta_url. El árbol se arma por `opcion_padre`; el motor avanza por
    la rama default (subopciones) en las secuencias de preguntas encadenadas."""
    from crm.models import OpcionDepartamentoChatBot

    nombres_fallback = {
        'pregunta': 'Pregunta', 'handoff': 'Hablar con asesor',
        'menu': 'Menú', 'cta_url': 'Abrir enlace', 'respuesta': 'Respuesta',
    }
    creadas = 0
    for i, nodo in enumerate(nodos_lista):
        if not isinstance(nodo, dict):
            continue
        texto = (nodo.get('texto_boton') or nodo.get('nombre') or '').strip()
        mensaje = (nodo.get('mensaje') or '').strip()
        tipo_in = (nodo.get('tipo') or '').strip().lower()
        hijos = nodo.get('hijos') or []
        tiene_hijos = isinstance(hijos, list) and len(hijos) > 0

        if tipo_in not in ('menu', 'pregunta', 'respuesta', 'handoff', 'cta_url'):
            tipo_in = 'menu' if tiene_hijos else 'respuesta'
        if not texto:
            texto = nombres_fallback.get(tipo_in, 'Respuesta')

        config = {}
        variable_destino = ''
        validacion_tipo = 'none'
        respuesta_txt = ''

        if tipo_in == 'menu':
            tipo_nodo = 'menu'
            if mensaje:
                config['mensaje'] = mensaje[:1000]
        elif tipo_in == 'pregunta':
            tipo_nodo = 'pregunta'
            config['pregunta'] = (nodo.get('pregunta') or mensaje or texto).strip()[:1000]
            variable_destino = (nodo.get('variable') or '').strip()[:60]
            val = (nodo.get('validacion') or 'none').strip().lower()
            validacion_tipo = val if val in _VALIDACIONES_OK else 'none'
        elif tipo_in == 'handoff':
            tipo_nodo = 'handoff'
            if mensaje:
                config['mensaje'] = mensaje[:1000]
        elif tipo_in == 'cta_url':
            tipo_nodo = 'respuesta'
            respuesta_txt = mensaje[:2000]
            cta_url = (nodo.get('cta_url') or '').strip()
            if cta_url:
                config['cta_url'] = cta_url[:2000]
                disp = (nodo.get('cta_display_text') or '').strip()
                if disp:
                    config['cta_display_text'] = disp[:20]
        else:
            tipo_nodo = 'respuesta'
            respuesta_txt = (mensaje or texto)[:2000]

        nueva = OpcionDepartamentoChatBot.objects.create(
            departamento=departamento,
            opcion_padre=parent,
            nombre=texto[:100],
            respuesta=respuesta_txt,
            orden=orden_inicial + i,
            tipo_nodo=tipo_nodo,
            variable_destino=variable_destino,
            validacion_tipo=validacion_tipo,
            mensaje_error=('Dato inválido, intentá de nuevo.' if tipo_nodo == 'pregunta' else ''),
            reintentos_max=3,
            es_inicio=(parent is None and i == 0),
            usuario_creacion=departamento.usuario_creacion,
            config=config,
        )
        creadas += 1
        if tiene_hijos:
            creadas += _crear_nodos_wizard(departamento, hijos, parent=nueva)
    return creadas


def generar_wizard(*, descripcion: str, tipo_negocio: str, tono: str,
                   objetivo: str, datos_cliente: str, opciones_menu: str,
                   handoff_cuando: str, apikey_obj, usuario) -> dict:
    """Genera un DepartamentoChatBot con un PROCESO pregunta->respuesta a partir
    de las respuestas del asistente guiado (Q&A). Soporta captura de datos
    (nodos `pregunta` con validación) y `handoff`.

    Raises:
        IAActionError — input inválido, JSON malformado, LLM error.
    """
    from crm.models import DepartamentoChatBot

    descripcion = (descripcion or '').strip()
    if len(descripcion) < 30:
        raise IAActionError("Descripcion muy corta (minimo 30 chars).")
    tipo_negocio = (tipo_negocio or '').strip() or 'no especificado'
    tono = (tono or 'amable').strip() or 'amable'
    objetivo = (objetivo or '').strip() or 'Atender la consulta del cliente.'
    datos_cliente = (datos_cliente or '').strip() or '(ninguno)'
    opciones_menu = (opciones_menu or '').strip() or '(ninguna especificada)'
    handoff_cuando = (handoff_cuando or '').strip() or 'Cuando el cliente pida hablar con una persona.'

    prompt = get_prompt(
        'dpchatbots_wizard',
        descripcion=descripcion, tipo_negocio=tipo_negocio,
        tono=tono, tono_title=tono.title(),
        objetivo=objetivo, datos_cliente=datos_cliente,
        opciones_menu=opciones_menu, handoff_cuando=handoff_cuando,
    )

    payload, tokens, modelo = invocar_json(
        prompt, apikey_obj=apikey_obj, origen='dpchatbot_wizard',
        prompt_preview=objetivo[:300], max_tokens=16000, temperature=0.4,
    )

    nombre = (payload.get('nombre_departamento') or '').strip()
    if not nombre:
        raise IAActionError("La IA no devolvio nombre_departamento.")
    bienvenida = (payload.get('mensaje_bienvenida') or '').strip()
    nodos = payload.get('nodos') or []
    if not isinstance(nodos, list):
        nodos = []

    res = _persistir_flujo(nombre, bienvenida, nodos, usuario)
    res['tokens'] = tokens
    res['modelo'] = modelo
    return res


def _persistir_flujo(nombre, bienvenida, nodos, usuario) -> dict:
    """Crea el DepartamentoChatBot + nodos desde un payload de flujo ya armado.
    Lo comparten el asistente guiado (`generar_wizard`) y el conversacional
    (`crear_desde_borrador`)."""
    from crm.models import DepartamentoChatBot
    with transaction.atomic():
        depto = DepartamentoChatBot.objects.create(
            nombre=nombre,
            mensaje_saludo=bienvenida,
            activo_tradicional=True,
            usuario_creacion=usuario,
        )
        opciones_count = _crear_nodos_wizard(depto, nodos, parent=None)
    return {
        'departamento_id': depto.id,
        'nombre': depto.nombre,
        'opciones_count': opciones_count,
    }


# ============================================================================
# Asistente conversacional (chat multi-turno con borrador del flujo)
# ============================================================================
def _historial_a_texto(historial) -> str:
    if not isinstance(historial, list):
        return '(sin mensajes previos)'
    lineas = []
    for m in historial[-20:]:
        if not isinstance(m, dict):
            continue
        rol = 'Operador' if (m.get('rol') == 'user') else 'Asistente'
        txt = (m.get('texto') or '').strip()
        if txt:
            lineas.append(f'{rol}: {txt}')
    return '\n'.join(lineas) or '(sin mensajes previos)'


def conversar(*, historial, mensaje, borrador, apikey_obj, usuario=None) -> dict:
    """Un turno del asistente conversacional. `historial` = lista de
    {rol:'user'|'assistant', texto}. `borrador` = flujo JSON actual (o None).

    Devuelve {respuesta, flujo, listo, tokens, modelo}.
    """
    mensaje = (mensaje or '').strip()
    if not mensaje:
        raise IAActionError('Mensaje vacío.')

    borrador_txt = '(aún no hay borrador)'
    if isinstance(borrador, dict) and borrador:
        try:
            borrador_txt = json.dumps(borrador, ensure_ascii=False)[:8000]
        except (TypeError, ValueError):
            borrador_txt = '(borrador no serializable)'

    prompt = get_prompt(
        'dpchatbots_chat',
        historial=_historial_a_texto(historial),
        borrador=borrador_txt,
        mensaje=mensaje,
    )
    payload, tokens, modelo = invocar_json(
        prompt, apikey_obj=apikey_obj, origen='dpchatbot_chat',
        prompt_preview=mensaje[:300], max_tokens=16000, temperature=0.5,
    )
    flujo = payload.get('flujo')
    if not isinstance(flujo, dict):
        flujo = borrador if isinstance(borrador, dict) else None
    return {
        'respuesta': (payload.get('respuesta') or '').strip(),
        'flujo': flujo,
        'listo': bool(payload.get('listo')),
        'tokens': tokens,
        'modelo': modelo,
    }


def crear_desde_borrador(*, flujo, usuario) -> dict:
    """Persiste el flujo acordado en el chat. `flujo` = dict con
    nombre_departamento, mensaje_bienvenida, nodos[]."""
    if not isinstance(flujo, dict):
        raise IAActionError('Borrador inválido.')
    nombre = (flujo.get('nombre_departamento') or '').strip()
    if not nombre:
        raise IAActionError('El borrador todavía no tiene nombre de departamento.')
    bienvenida = (flujo.get('mensaje_bienvenida') or '').strip()
    nodos = flujo.get('nodos') or []
    if not isinstance(nodos, list) or not nodos:
        raise IAActionError('El borrador todavía no tiene pasos definidos.')
    return _persistir_flujo(nombre, bienvenida, nodos, usuario)


# ============================================================================
# Editar un departamento existente por chat (cargar como borrador + reemplazar)
# ============================================================================
_TIPOS_BORRADOR = {'menu', 'pregunta', 'respuesta', 'handoff', 'cta_url'}


def _arbol_a_nodos_borrador(arbol) -> list:
    """Convierte el árbol de `obtener_arbol_opciones()` al esquema de nodos del
    asistente (reverso de `_crear_nodos_wizard`). Solo cubre el árbol por
    `opcion_padre`; flujos con aristas complejas del canvas se aproximan."""
    out = []
    for n in arbol:
        cfg = n.get('config') or {}
        tipo = n.get('tipo_nodo') or 'respuesta'
        if tipo not in _TIPOS_BORRADOR:
            tipo = 'menu' if n.get('hijos') else 'respuesta'
        nd = {
            'tipo': tipo,
            'texto_boton': n.get('nombre') or '',
            'mensaje': cfg.get('mensaje') or n.get('respuesta') or '',
        }
        if tipo == 'pregunta':
            nd['pregunta'] = cfg.get('pregunta') or n.get('respuesta') or ''
            nd['variable'] = n.get('variable_destino') or ''
            nd['validacion'] = n.get('validacion_tipo') or 'none'
        if cfg.get('cta_url'):
            nd['tipo'] = 'cta_url'
            nd['cta_url'] = cfg.get('cta_url')
            nd['cta_display_text'] = cfg.get('cta_display_text') or ''
        hijos = n.get('hijos') or []
        if hijos:
            nd['hijos'] = _arbol_a_nodos_borrador(hijos)
        out.append(nd)
    return out


def serializar_a_borrador(depto) -> dict:
    """Vuelca un DepartamentoChatBot existente al esquema de borrador del
    asistente, para precargarlo en el chat de edición."""
    return {
        'nombre_departamento': depto.nombre,
        'descripcion_departamento': '',
        'mensaje_bienvenida': depto.mensaje_saludo or '',
        'nodos': _arbol_a_nodos_borrador(depto.obtener_arbol_opciones()),
    }


def actualizar_desde_borrador(*, departamento_id, flujo, usuario) -> dict:
    """Reemplaza el flujo de un departamento existente con el borrador del chat:
    soft-delete de nodos y aristas previas, recrea desde el borrador y resetea
    los estados de conversación en vuelo de ese depto."""
    from crm.models import (
        DepartamentoChatBot, OpcionDepartamentoChatBot,
        ConexionNodoChatbot, EstadoFlujoChatbot,
    )
    if not isinstance(flujo, dict):
        raise IAActionError('Borrador inválido.')
    depto = DepartamentoChatBot.objects.filter(id=departamento_id, status=True).first()
    if not depto:
        raise IAActionError('Departamento no encontrado.')
    nodos = flujo.get('nodos') or []
    if not isinstance(nodos, list) or not nodos:
        raise IAActionError('El borrador todavía no tiene pasos definidos.')
    nombre = (flujo.get('nombre_departamento') or '').strip() or depto.nombre
    bienvenida = (flujo.get('mensaje_bienvenida') or '').strip()

    with transaction.atomic():
        ConexionNodoChatbot.objects.filter(
            nodo_origen__departamento=depto, status=True,
        ).update(status=False)
        OpcionDepartamentoChatBot.objects.filter(
            departamento=depto, status=True,
        ).update(status=False)
        EstadoFlujoChatbot.objects.filter(
            departamento=depto, status=True,
        ).update(nodo_actual=None, intentos=0)

        depto.nombre = nombre[:100]
        if bienvenida:
            depto.mensaje_saludo = bienvenida
        depto.save()
        opciones_count = _crear_nodos_wizard(depto, nodos, parent=None)

    return {
        'departamento_id': depto.id,
        'nombre': depto.nombre,
        'opciones_count': opciones_count,
    }


# ============================================================================
# Explicación narrativa de un flujo existente (cache + regeneración bajo demanda)
# ============================================================================
def _serializar_flujo_para_prompt(depto) -> str:
    """Vuelca el flujo del depto en formato compacto para que el LLM pueda
    explicarlo: nodos numerados con su tipo, mensaje principal, side-effects
    y conexiones salientes."""
    from crm.models import OpcionDepartamentoChatBot, ConexionNodoChatbot

    nodos = list(
        OpcionDepartamentoChatBot.objects
        .filter(departamento=depto, status=True)
        .select_related('endpoint')
        .order_by('orden', 'id')
    )
    conexiones = list(
        ConexionNodoChatbot.objects
        .filter(nodo_origen__departamento=depto, status=True)
        .select_related('nodo_origen', 'nodo_destino')
        .order_by('nodo_origen__orden', 'orden')
    )
    salidas_por_nodo = {}
    for c in conexiones:
        salidas_por_nodo.setdefault(c.nodo_origen_id, []).append(c)

    lineas = []
    for n in nodos:
        cfg = n.config or {}
        marca = '[INICIO] ' if n.es_inicio else ''
        msg = (cfg.get('mensaje') or cfg.get('pregunta') or n.respuesta or '').strip().replace('\n', ' ')[:200]
        linea = f'#{n.id} ({n.tipo_nodo}) {marca}{n.nombre}'
        if msg:
            linea += f' — "{msg}"'
        if n.tipo_nodo == 'http' and n.endpoint:
            linea += f' [HTTP {(cfg.get("metodo") or "GET")} {n.endpoint.base_url}{cfg.get("path") or ""}]'
        if cfg.get('envia_correo'):
            linea += ' [📧 envía correo a asesores]'
        if n.variable_destino:
            linea += f' [captura en variable: {n.variable_destino}]'
        salidas = salidas_por_nodo.get(n.id) or []
        if salidas:
            sal_str = ', '.join(
                f'{c.etiqueta or "→"}: #{c.nodo_destino_id}'
                for c in salidas
            )
            linea += f' → siguientes: {sal_str}'
        lineas.append(linea)
    return '\n'.join(lineas)


def explicacion_esta_actualizada(depto) -> bool:
    """True si la explicación cacheada sigue vigente (ningún nodo se modificó
    después). False si algún nodo fue tocado o si nunca se generó."""
    if not depto.explicacion_ia or not depto.explicacion_ia_generada_en:
        return False
    from crm.models import OpcionDepartamentoChatBot
    ultima_mod = (
        OpcionDepartamentoChatBot.objects
        .filter(departamento=depto, status=True)
        .order_by('-fecha_modificacion')
        .values_list('fecha_modificacion', flat=True)
        .first()
    )
    if not ultima_mod:
        return True  # depto sin nodos pero con explicación → válida
    return ultima_mod <= depto.explicacion_ia_generada_en


def explicar_flujo(*, depto, apikey_obj, usuario=None) -> str:
    """Llama al LLM para generar un resumen narrativo del flujo del depto.
    Persiste el resultado en `depto.explicacion_ia` + timestamp.

    Args:
        depto: instancia DepartamentoChatBot.
        apikey_obj: ApiKeyIA validada.
        usuario: opcional, para audit (no se usa hoy pero queda por consistencia).

    Returns:
        El texto generado.

    Raises:
        IAActionError — si el depto está vacío, si el LLM falla, o si la
        respuesta llega vacía.
    """
    flujo_txt = _serializar_flujo_para_prompt(depto)
    if not flujo_txt:
        raise IAActionError('El departamento no tiene nodos para explicar.')

    prompt = (
        'Sos un experto explicando flujos conversacionales de chatbots de WhatsApp '
        'a operadores no técnicos. Te paso la estructura COMPLETA del flujo y '
        'necesito que la expliques EN DETALLE, recorriendo TODOS los nodos en '
        'orden lógico — sin omitir ninguno.\n\n'
        f'Departamento: "{depto.nombre}"\n'
        f'Mensaje de saludo: "{depto.mensaje_saludo or "(sin saludo)"}"\n\n'
        'NODOS DEL FLUJO (numerados; cada uno indica tipo, qué hace, '
        'side-effects y a dónde va después):\n'
        f'{flujo_txt}\n\n'
        'INSTRUCCIONES — redactá la explicación en español neutro con esta '
        'estructura COMPLETA. NO te quedes corto: explicá cada paso del flujo.\n\n'
        '**1. Objetivo del flujo** — 2-3 líneas: qué resuelve y para quién.\n\n'
        '**2. Recorrido paso a paso (camino feliz)** — listá EN ORDEN cada nodo '
        'que el cliente atraviesa cuando todo sale bien. Por cada nodo explicá:\n'
        '   - Qué hace el bot (mensaje que envía, dato que pide, API que consulta).\n'
        '   - Qué se espera del cliente (responder, tocar botón, etc.).\n'
        '   - A dónde avanza después.\n'
        '   Usá numeración (Paso 1, Paso 2, …) o lista anidada con -.\n\n'
        '**3. Bifurcaciones y caminos alternativos** — describí TODAS las ramas '
        'no-felices: qué pasa si una API falla, si el cliente elige una opción '
        'distinta del default, si la validación rechaza la respuesta, si la conv '
        'cae a un nodo de error.\n\n'
        '**4. Side-effects** — listá los nodos que disparan correos, llaman a '
        'webhooks externos, generan handoff, terminan la conversación, o setean '
        'variables relevantes. Indicá QUÉ hacen y CUÁNDO.\n\n'
        '**5. Datos que se capturan** — tabla o lista de las variables que el '
        'flujo recolecta del cliente (cedula, placa, email, etc.) y cuándo.\n\n'
        '**6. Resumen ejecutivo** — 3-5 líneas de cierre que un asesor pueda '
        'leer en 10 segundos para entender el flujo de un vistazo.\n\n'
        'Usá Markdown ligero (*negrita*, listas con -). Es OK mencionar IDs '
        'cuando ayuda a ubicar el nodo (ej. "Paso 4 — pedir cédula (#70)"). '
        'NO uses frases vacías ni adjetivos floridos. Sé concreto.'
    )

    llm, modelo, provider = build_llm(
        apikey_obj, force_json=False,
        max_tokens=4000, temperature=0.3,
    )
    try:
        msg = llm.invoke(prompt)
    except Exception as ex:
        raise IAActionError(f'Error invocando LLM ({provider.name}): {ex}')

    contenido = (getattr(msg, 'content', None) or str(msg)).strip()
    if not contenido:
        raise IAActionError('El LLM devolvió respuesta vacía.')

    try:
        log_consumo(
            msg, apikey_obj=apikey_obj, modelo=modelo,
            origen='dpchatbot_explicar', agente=None, conversacion=None,
            prompt_preview=f'Explicar flujo "{depto.nombre}"',
        )
    except Exception:
        logger.exception('log_consumo falló al explicar depto %s', depto.id)

    depto.explicacion_ia = contenido
    depto.explicacion_ia_generada_en = timezone.now()
    depto.save(update_fields=['explicacion_ia', 'explicacion_ia_generada_en'])

    logger.info('Explicación IA generada para depto %s (%s chars)',
                depto.id, len(contenido))
    return contenido
