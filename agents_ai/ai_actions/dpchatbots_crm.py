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
