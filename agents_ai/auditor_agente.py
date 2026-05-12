"""Auditor IA: analiza la configuracion de un agente + metricas operativas
y llama a un LLM para sugerir mejoras concretas en prompt_template y contexto_estatico.
"""
import json
import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


# Meta-prompt del auditor. Se le pasa al LLM junto con todo el contexto.
AUDITOR_SYSTEM_PROMPT = """Eres un ingeniero de prompts experto en bots conversacionales para WhatsApp.

Tu tarea es auditar la configuracion de un agente IA y proponer mejoras CONCRETAS y APLICABLES que resuelvan los problemas detectados en las metricas.

REGLAS DE ORO:
1. Los mensajes de WhatsApp deben ser CORTOS (maximo 3-4 lineas) salvo que el cliente pida detalle.
2. El bot debe tener IDENTIDAD clara: saber que es, que puede hacer, a quien sirve.
3. PROHIBIDO responder con definiciones genericas tipo Wikipedia.
4. Las preguntas meta ("que puedes hacer", "tienes menu", "ayuda") deben tener respuesta PREPARADA, no depender del RAG.
5. Cuando el bot no sabe, debe OFRECER ALTERNATIVAS (contactar humano, ver menu, dar 3 temas donde si sabe).
6. Tono conversacional y amable, emojis moderados (1-2 por mensaje maximo).

Responde UNICAMENTE con un objeto JSON valido con esta estructura exacta (sin backticks, sin explicacion extra):

{
  "razonamiento": "Analisis breve (2-3 parrafos) de los problemas detectados y estrategia de mejora.",
  "prompt_template_nuevo": "El nuevo prompt completo. DEBE mantener los placeholders que existen en el actual ({context}, {question}, {descripcion_agente}, {contexto_extra}, etc.).",
  "contexto_estatico_nuevo": "Nuevo contexto estatico con FAQ curado. Incluir preguntas que el bot rechazo recientemente, con respuestas especificas del negocio.",
  "faq_sugerido": [
    {"pregunta": "...", "respuesta": "..."},
    ...
  ],
  "gaps_de_entrenamiento": ["tema 1", "tema 2", "..."],
  "cambios_clave": ["bullet de cambio 1", "bullet de cambio 2", "..."]
}
"""


def _detectar_respuestas_problema(texto: str) -> dict:
    """Clasifica una respuesta IA: detecta patrones problematicos."""
    t = (texto or '').lower().strip()
    return {
        'rechazo': bool(re.search(r'no tengo esa informaci[oó]n|no s[eé]|no cuento con|no dispongo', t)),
        'muy_larga': len(texto or '') > 500,
        'wiki': bool(re.search(r'\bes un profesional\b|\bse refiere a\b|\bse define como\b', t)) and len(texto or '') > 300,
        'vacia': len(t) < 5,
    }


def recopilar_metricas(agente, dias=30) -> dict:
    """Calcula metricas operativas del agente para los ultimos N dias."""
    from crm.models import ConsumoTokenIA
    from whatsapp.models import MensajeWhatsApp, ConversacionWhatsApp, TrazaMensajeIA

    corte = timezone.now() - timedelta(days=dias)

    # Sesiones y conversaciones vinculadas a este agente
    sesiones = agente.sesionwhatsapp_set.all() if hasattr(agente, 'sesionwhatsapp_set') else []
    try:
        from whatsapp.models import SesionWhatsApp
        sesiones_qs = SesionWhatsApp.objects.filter(agente_ia=agente)
    except Exception:
        sesiones_qs = None

    total_msgs_ia = 0
    rechazos = 0
    largas = 0
    wiki = 0
    vacias = 0
    respuestas_muestra = []
    preguntas_rechazadas = []

    if sesiones_qs is not None:
        # Mensajes IA del agente (generados por bot)
        msgs_ia = MensajeWhatsApp.objects.filter(
            conversacion__contacto__sesion__in=sesiones_qs,
            ia_generado=True,
            fecha__gte=corte,
        ).select_related('conversacion', 'conversacion__contacto', 'conversacion__contacto__sesion').order_by('-fecha')[:500]
        total_msgs_ia = msgs_ia.count() if hasattr(msgs_ia, 'count') else len(list(msgs_ia))

        for m in msgs_ia:
            flags = _detectar_respuestas_problema(m.mensaje or '')
            if flags['rechazo']:
                rechazos += 1
                # Buscar la pregunta que precedio
                try:
                    pregunta = MensajeWhatsApp.objects.filter(
                        conversacion=m.conversacion,
                        fecha__lt=m.fecha,
                        ia_generado=False,
                    ).exclude(remitente=m.conversacion.sesion.numero).order_by('-fecha').first()
                    if pregunta and pregunta.mensaje:
                        preguntas_rechazadas.append(pregunta.mensaje[:200])
                except Exception:
                    pass
            if flags['muy_larga']:
                largas += 1
            if flags['wiki']:
                wiki += 1
            if flags['vacia']:
                vacias += 1
            if len(respuestas_muestra) < 10 and (flags['rechazo'] or flags['muy_larga']):
                respuestas_muestra.append({
                    'fecha': m.fecha.strftime('%Y-%m-%d %H:%M'),
                    'texto': (m.mensaje or '')[:300],
                    'problema': (
                        'rechazo' if flags['rechazo']
                        else 'muy_larga' if flags['muy_larga']
                        else 'wiki'
                    ),
                })

    # Errores en pipeline (trazas)
    try:
        trazas_error = TrazaMensajeIA.objects.filter(
            sesion__in=sesiones_qs, nivel='error', fecha__gte=corte,
        ).count() if sesiones_qs is not None else 0
    except Exception:
        trazas_error = 0

    # Tokens (ConsumoTokenIA.fecha — no fecha_registro)
    try:
        total_tokens = ConsumoTokenIA.objects.filter(
            agente=agente, fecha__gte=corte
        ).values_list('tokens_total', flat=True)
        suma_tokens = sum(total_tokens) if total_tokens else 0
    except Exception:
        suma_tokens = 0

    pct = lambda n: round((n / total_msgs_ia) * 100, 1) if total_msgs_ia else 0

    # Deduplicar preguntas rechazadas (top frecuencia)
    from collections import Counter
    preg_counter = Counter(preguntas_rechazadas)
    top_rechazadas = [{'pregunta': p, 'veces': n} for p, n in preg_counter.most_common(10)]

    return {
        'dias': dias,
        'total_mensajes_ia': total_msgs_ia,
        'rechazos': rechazos,
        'pct_rechazos': pct(rechazos),
        'respuestas_largas': largas,
        'pct_largas': pct(largas),
        'respuestas_wikipedia': wiki,
        'pct_wiki': pct(wiki),
        'respuestas_vacias': vacias,
        'trazas_error': trazas_error,
        'tokens_consumidos': suma_tokens,
        'sesiones_activas': sesiones_qs.filter(status=True).count() if sesiones_qs is not None else 0,
        'docs_entrenamiento': agente.detalleagentesai_set.filter(status=True).count(),
        'api_keys_activas': agente.apikey.filter(estado=True).count(),
        'top_preguntas_rechazadas': top_rechazadas,
        'respuestas_problema_muestra': respuestas_muestra,
    }


def construir_prompt_auditor(agente, metricas: dict) -> str:
    """Arma el prompt completo que se le pasa al LLM auditor."""
    perfil = agente.perfil
    perfil_info = ''
    if perfil:
        perfil_info = f"""
Nombre empresa: {getattr(perfil, 'nombre_empresa', '') or '—'}
Descripcion: {(getattr(perfil, 'descripcion', '') or '')[:600]}
""".strip()

    partes = [
        AUDITOR_SYSTEM_PROMPT,
        "",
        "=== CONFIGURACION ACTUAL DEL AGENTE ===",
        f"Nombre: {agente.nombre}",
        f"Descripcion: {agente.descripcion or '(sin descripcion)'}",
        "",
        "--- PROMPT TEMPLATE ACTUAL ---",
        agente.prompt_template or '(vacio)',
        "",
        "--- CONTEXTO ESTATICO ACTUAL ---",
        (agente.contexto_estatico or '(vacio)')[:4000],
        "",
        "--- PERFIL DE NEGOCIO ---",
        perfil_info or '(sin perfil asignado)',
        "",
        "=== METRICAS DE SALUD (ultimos {} dias) ===".format(metricas.get('dias', 30)),
        f"Total mensajes IA enviados: {metricas.get('total_mensajes_ia', 0)}",
        f"Respuestas de rechazo ('no tengo esa info'): {metricas.get('rechazos', 0)} ({metricas.get('pct_rechazos', 0)}%)",
        f"Respuestas demasiado largas (>500 chars): {metricas.get('respuestas_largas', 0)} ({metricas.get('pct_largas', 0)}%)",
        f"Respuestas estilo Wikipedia: {metricas.get('respuestas_wikipedia', 0)} ({metricas.get('pct_wiki', 0)}%)",
        f"Errores en pipeline: {metricas.get('trazas_error', 0)}",
        f"Docs de entrenamiento: {metricas.get('docs_entrenamiento', 0)}",
        f"API Keys activas: {metricas.get('api_keys_activas', 0)}",
        "",
        "=== TOP PREGUNTAS QUE EL BOT RECHAZO ===",
    ]
    top = metricas.get('top_preguntas_rechazadas') or []
    if top:
        for i, item in enumerate(top, 1):
            partes.append(f"{i}. [{item['veces']}x] {item['pregunta']}")
    else:
        partes.append("(ninguna)")

    partes += [
        "",
        "=== MUESTRA DE RESPUESTAS PROBLEMATICAS ===",
    ]
    muestra = metricas.get('respuestas_problema_muestra') or []
    if muestra:
        for m in muestra:
            partes.append(f"[{m['fecha']}] ({m['problema']}): {m['texto']}")
    else:
        partes.append("(sin muestra disponible)")

    partes += [
        "",
        "=== RESPONDE AHORA ===",
        "Devuelve UNICAMENTE el JSON con la estructura indicada, sin comentarios ni backticks.",
    ]
    return "\n".join(partes)


def _invocar_llm(apikey_obj, prompt_text):
    """Invoca al LLM forzando salida JSON estructurada cuando el proveedor lo soporta."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        ChatGoogleGenerativeAI = None
    try:
        from langchain_community.chat_models import ChatOpenAI
    except ImportError:
        ChatOpenAI = None

    proveedor = apikey_obj.proveedor
    modelo_cfg = (getattr(apikey_obj, 'modelo', '') or '').strip()
    if proveedor == 2:
        if not ChatGoogleGenerativeAI:
            raise RuntimeError("langchain_google_genai no instalado")
        modelo = modelo_cfg or 'gemini-2.5-flash'
        llm = ChatGoogleGenerativeAI(
            model=modelo,
            google_api_key=apikey_obj.descripcion,
            max_output_tokens=16000,
            temperature=0.3,
            model_kwargs={"response_mime_type": "application/json"},
        )
    elif proveedor == 3:
        if not ChatOpenAI:
            raise RuntimeError("ChatOpenAI no disponible")
        modelo = modelo_cfg or 'gpt-4o-mini'
        llm = ChatOpenAI(
            model_name=modelo,
            openai_api_key=apikey_obj.descripcion,
            max_tokens=16000,
            temperature=0.3,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
    elif proveedor == 4:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise RuntimeError("langchain_anthropic no instalado")
        modelo = modelo_cfg or 'claude-haiku-4-5-20251001'
        llm = ChatAnthropic(
            model=modelo,
            anthropic_api_key=apikey_obj.descripcion,
            max_tokens=16000,
            temperature=0.3,
        )
    else:
        raise RuntimeError(
            f"Proveedor {proveedor} no soportado por el auditor. "
            f"Usá una API Key con proveedor Gemini, OpenAI o Claude."
        )

    msg = llm.invoke(prompt_text)
    texto = getattr(msg, 'content', '') or ''
    tokens = 0
    try:
        meta = getattr(msg, 'usage_metadata', None) or {}
        tokens = meta.get('total_tokens', 0) or 0
    except Exception:
        pass
    return texto, modelo, tokens


def _reparar_json_llm(texto: str) -> str:
    """Repara errores comunes en JSON devuelto por LLMs:
    - Saltos de linea literales dentro de strings (no escapados como \\n)
    - Tabs/returns no escapados
    - Strings sin cerrar al final (por truncamiento)
    - Llaves sin cerrar
    """
    s = (texto or '').strip()
    # 1. Quitar fences de markdown
    s = re.sub(r'^```(?:json)?\s*', '', s)
    s = re.sub(r'\s*```\s*$', '', s)
    # 2. Extraer desde el primer { hasta el ultimo }
    i = s.find('{')
    j = s.rfind('}')
    if i >= 0:
        s = s[i:] if j <= i else s[i:j + 1]

    # 3. Escapar chars de control dentro de strings (estado-maquina)
    out = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string:
            if ch == '\n':
                out.append('\\n')
            elif ch == '\r':
                out.append('\\r')
            elif ch == '\t':
                out.append('\\t')
            elif ord(ch) < 0x20:
                out.append(f'\\u{ord(ch):04x}')
            else:
                out.append(ch)
        else:
            out.append(ch)
    s = ''.join(out)

    # 4. Cerrar string sin cerrar (truncamiento)
    if s.count('"') % 2 == 1:
        s += '"'
    # 5. Cerrar llaves/corchetes faltantes
    abiertas_llaves = s.count('{') - s.count('}')
    abiertos_corch = s.count('[') - s.count(']')
    if abiertos_corch > 0:
        s += ']' * abiertos_corch
    if abiertas_llaves > 0:
        s += '}' * abiertas_llaves
    return s


def _parsear_json_respuesta(texto: str) -> dict:
    """Extrae JSON del output del LLM con varios niveles de reparacion."""
    t = (texto or '').strip()
    # 1) Intento directo
    try:
        return json.loads(t)
    except Exception:
        pass
    # 2) Quitar fences + extraer entre { }
    t2 = re.sub(r'^```(?:json)?\s*', '', t)
    t2 = re.sub(r'\s*```\s*$', '', t2)
    ini = t2.find('{')
    fin = t2.rfind('}')
    if ini >= 0 and fin > ini:
        try:
            return json.loads(t2[ini:fin + 1])
        except Exception:
            pass
    # 3) Reparacion pesada (escapa saltos dentro de strings, cierra llaves, etc.)
    try:
        return json.loads(_reparar_json_llm(t))
    except Exception as ex:
        # Re-lanzar con mensaje mas descriptivo y snippet del texto problematico
        raise ValueError(
            f"No se pudo parsear el JSON del LLM tras 3 intentos ({ex}). "
            f"Primeros 500 chars de la respuesta: {t[:500]}"
        )


def ejecutar_auditoria(agente, usuario=None, apikey_obj=None, dias=30):
    """Flujo completo: recopila metricas, llama al LLM, persiste resultado.

    Returns: AuditoriaAgenteIA (con estado='generado' si ok, 'error' si fallo).
    """
    from crm.models import AuditoriaAgenteIA
    auditoria = AuditoriaAgenteIA.objects.create(
        agente=agente, usuario=usuario,
        snapshot_prompt=agente.prompt_template,
        snapshot_contexto=agente.contexto_estatico,
        estado='pendiente',
    )
    try:
        metricas = recopilar_metricas(agente, dias=dias)
        auditoria.metricas = metricas

        if not apikey_obj:
            apikey_obj = agente.apikey.filter(estado=True).first()
        if not apikey_obj:
            raise RuntimeError("El agente no tiene API keys activas para invocar al auditor.")

        prompt = construir_prompt_auditor(agente, metricas)
        respuesta, modelo, tokens = _invocar_llm(apikey_obj, prompt)
        # Persistir siempre la respuesta cruda (util para debug si el JSON falla)
        auditoria.respuesta_cruda = (respuesta or '')[:20000]
        auditoria.modelo_usado = modelo
        auditoria.tokens_usados = tokens

        # Registrar consumo de tokens
        if tokens and apikey_obj:
            try:
                from crm.models import ConsumoTokenIA
                from crm.alertas_consumo import verificar_alerta_consumo
                ConsumoTokenIA.objects.create(
                    apikey=apikey_obj, agente=agente,
                    tokens_entrada=0, tokens_salida=0,
                    tokens_total=tokens, modelo=modelo,
                    origen='auditor',
                    prompt_preview='Auditoria de agente IA',
                )
                verificar_alerta_consumo(apikey_obj, tokens)
            except Exception:
                logger.exception("Error registrando consumo del auditor")

        datos = _parsear_json_respuesta(respuesta)
        auditoria.sugerencias = datos
        auditoria.razonamiento = datos.get('razonamiento') or ''
        auditoria.estado = 'generado'
        auditoria.save()
        return auditoria
    except Exception as ex:
        logger.exception("Error en auditoria IA")
        auditoria.estado = 'error'
        auditoria.error_mensaje = str(ex)[:2000]
        auditoria.save()
        return auditoria


def aplicar_sugerencia(auditoria, campo, usuario=None):
    """Aplica un campo especifico de la sugerencia al agente.
    campo: 'prompt_template' | 'contexto_estatico'
    """
    if auditoria.estado not in ('generado', 'aplicado'):
        raise RuntimeError("Esta auditoria no tiene sugerencias aplicables.")
    sug = auditoria.sugerencias or {}
    agente = auditoria.agente

    if campo == 'prompt_template':
        nuevo = sug.get('prompt_template_nuevo')
        if not nuevo:
            raise RuntimeError("La sugerencia no incluye prompt_template_nuevo.")
        agente.prompt_template = nuevo
    elif campo == 'contexto_estatico':
        nuevo = sug.get('contexto_estatico_nuevo')
        if not nuevo:
            raise RuntimeError("La sugerencia no incluye contexto_estatico_nuevo.")
        agente.contexto_estatico = nuevo
    else:
        raise RuntimeError(f"Campo no soportado: {campo}")

    agente.save()
    aplicaciones = dict(auditoria.aplicaciones or {})
    aplicaciones[campo] = {
        'aplicado_en': timezone.now().isoformat(),
        'usuario_id': getattr(usuario, 'id', None),
    }
    auditoria.aplicaciones = aplicaciones
    # Si ambos campos aplicados, marcar cerrado
    if 'prompt_template' in aplicaciones and 'contexto_estatico' in aplicaciones:
        auditoria.estado = 'cerrado'
    else:
        auditoria.estado = 'aplicado'
    auditoria.save()
    return auditoria


def aplicar_faq_sugerido(auditoria, usuario=None) -> int:
    """Importa las entradas `faq_sugerido` del JSON del auditor como FaqAgente
    en estado 'pendiente' (el cliente aprobará desde el tab de Preguntas Frecuentes).

    Retorna el número de FAQs creadas. Evita duplicados exactos por pregunta
    dentro del mismo agente.
    """
    from crm.models import FaqAgente
    sug = auditoria.sugerencias or {}
    lista = sug.get('faq_sugerido') or []
    if not isinstance(lista, list) or not lista:
        return 0
    agente = auditoria.agente
    creadas = 0
    for item in lista:
        if not isinstance(item, dict):
            continue
        pregunta = (item.get('pregunta') or '').strip()
        respuesta = (item.get('respuesta') or '').strip()
        if not pregunta or not respuesta:
            continue
        if FaqAgente.objects.filter(agente=agente, pregunta__iexact=pregunta).exists():
            continue
        FaqAgente.objects.create(
            agente=agente,
            pregunta=pregunta[:2000],
            respuesta=respuesta[:4000],
            origen='auditor',
            estado='pendiente',
            auditoria_origen=auditoria,
        )
        creadas += 1

    aplicaciones = dict(auditoria.aplicaciones or {})
    aplicaciones['faq_sugerido'] = {
        'aplicado_en': timezone.now().isoformat(),
        'usuario_id': getattr(usuario, 'id', None),
        'creadas': creadas,
    }
    auditoria.aplicaciones = aplicaciones
    if auditoria.estado == 'generado':
        auditoria.estado = 'aplicado'
    auditoria.save()
    return creadas


def revertir_auditoria(auditoria, usuario=None):
    """Restaura el snapshot previo a la auditoria."""
    agente = auditoria.agente
    agente.prompt_template = auditoria.snapshot_prompt or agente.prompt_template
    agente.contexto_estatico = auditoria.snapshot_contexto
    agente.save()
    aplicaciones = dict(auditoria.aplicaciones or {})
    aplicaciones['revertido'] = {
        'revertido_en': timezone.now().isoformat(),
        'usuario_id': getattr(usuario, 'id', None),
    }
    auditoria.aplicaciones = aplicaciones
    auditoria.estado = 'generado'
    auditoria.save()
    return auditoria
