"""Generación de explicación narrativa de un flujo de departamento con IA.

Cachea el resultado en `DepartamentoChatBot.explicacion_ia` y solo regenera
cuando algún nodo del flujo fue modificado después de la última generación.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from agents_ai.ai_actions.base import IAActionError, build_llm, log_consumo


logger = logging.getLogger(__name__)


def _serializar_flujo_para_prompt(depto):
    """Vuelca el flujo del depto en formato compacto que el LLM pueda entender:
    nodos numerados con su tipo, mensaje principal y conexiones salientes.
    """
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


def generar_explicacion_flujo(depto, apikey_obj, usuario=None) -> str:
    """Llama al LLM para generar un resumen narrativo del flujo del depto.
    Persiste el resultado en `depto.explicacion_ia` + timestamp.

    Returns: el texto generado.
    Raises: IAActionError en cualquier fallo de LLM o config.
    """
    flujo_txt = _serializar_flujo_para_prompt(depto)
    if not flujo_txt:
        raise IAActionError('El departamento no tiene nodos para explicar.')

    prompt = (
        'Sos un experto explicando flujos conversacionales de chatbots de WhatsApp '
        'a operadores no técnicos. Te paso la estructura del flujo y necesito que '
        'redactes una explicación CLARA y CORTA de cómo funciona, paso a paso.\n\n'
        f'Departamento: "{depto.nombre}"\n'
        f'Mensaje de saludo: "{depto.mensaje_saludo or "(sin saludo)"}"\n\n'
        'NODOS DEL FLUJO (numerados; cada uno indica tipo, qué hace y a dónde va después):\n'
        f'{flujo_txt}\n\n'
        'Redactá la explicación en español neutro, en máximo 350 palabras, con esta estructura:\n'
        '1. **Objetivo** — qué resuelve este flujo en una línea.\n'
        '2. **Recorrido principal** — el camino feliz, paso por paso (numerado).\n'
        '3. **Bifurcaciones importantes** — qué pasa si el cliente elige X o si una API falla.\n'
        '4. **Side-effects** — si algún paso envía correo, dispara webhook o termina la conversación.\n'
        '5. **Datos que captura** — lista de variables que recolecta (cedula, placa, etc.).\n\n'
        'Usá Markdown ligero (*negrita*, listas con -). NO incluyas IDs de nodos en la respuesta '
        'a menos que sean críticos. Sé directo, sin frases tipo "este flujo es genial".'
    )

    llm, modelo, provider = build_llm(
        apikey_obj, force_json=False,
        max_tokens=1200, temperature=0.3,
    )
    try:
        msg = llm.invoke(prompt)
    except Exception as ex:
        raise IAActionError(f'Error invocando LLM ({provider.name}): {ex}')

    contenido = (getattr(msg, 'content', None) or str(msg)).strip()
    if not contenido:
        raise IAActionError('El LLM devolvió respuesta vacía.')

    # Loguear consumo (no rompe si falla).
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
