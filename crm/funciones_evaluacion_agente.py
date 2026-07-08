"""Suite de evaluación de agentes IA.

Ejecuta las preguntas de prueba guardadas contra el agente REAL (mismo motor
que producción, sin tocar historial ni memoria) y un juez LLM califica cada
respuesta en UNA sola llamada batch: ¿usó datos del entrenamiento?, ¿inventó?,
¿cumple el criterio? Devuelve score 0-10 por pregunta y global.
"""
import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

_MAX_PREGUNTAS = 15
_UMBRAL_APROBADA = 7

_PROMPT_JUEZ = """Eres un auditor de calidad de bots de WhatsApp. Evalúa las respuestas de un bot a preguntas de prueba.

Para cada ítem determina:
- uso_datos: true si la respuesta da información concreta del negocio (precios, horarios, productos); false si es evasiva o genérica.
- inventa: true si la respuesta afirma datos que probablemente NO están en el material del negocio (números, promociones o políticas sospechosamente específicos sin criterio que los respalde) o contradice el criterio.
- cumple_criterio: true/false si hay CRITERIO definido; null si el ítem no tiene criterio.
- score: entero 0-10 (10 = respuesta correcta, útil y natural; 0 = inventada o inútil).
- comentario: máximo 20 palabras, en español.

Responde ÚNICAMENTE con JSON válido:
{{"resultados": [{{"i": 1, "uso_datos": true, "inventa": false, "cumple_criterio": true, "score": 9, "comentario": "..."}}]}}

ÍTEMS A EVALUAR:
{items}"""


def _construir_consultor(agente, apikey_obj):
    from agents_ai.agente_consultor import AgenteConsultor
    from core.constantes import PROMPT_TEMPLATES
    vs_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path) if agente.vectorstore_path else ''
    vs_enlaces = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path) if agente.vectorstore_enlaces_path else ''
    return AgenteConsultor(
        vectorstore_path=vs_path,
        vectorstore_enlaces_path=vs_enlaces,
        provider=apikey_obj.proveedor,
        apikey=apikey_obj.descripcion,
        model_name=(apikey_obj.modelo or None),
        conversacion=None,
        prompt_template_text=(agente.prompt_template or '').strip() or PROMPT_TEMPLATES.get('es', ''),
        contexto_estatico=agente.contexto_estatico or None,
        perfil=agente.perfil,
        agente=agente,
        base_url=(getattr(apikey_obj, 'base_url', '') or None),
    )


def _clamp_score(valor):
    try:
        return max(0, min(10, int(valor)))
    except (TypeError, ValueError):
        return 0


def ejecutar_evaluacion(agente, apikey_obj):
    """Corre la suite completa. Devuelve la EvaluacionAgente creada o None si no hay preguntas."""
    from crm.models import EvaluacionAgente, ConsumoTokenIA

    preguntas = list(agente.preguntas_evaluacion.filter(status=True)[:_MAX_PREGUNTAS])
    if not preguntas:
        return None

    consultor = _construir_consultor(agente, apikey_obj)
    tokens_in = tokens_out = 0
    filas = []
    for p in preguntas:
        try:
            r = consultor.consultar(p.pregunta, agente.descripcion or '')
            filas.append({
                'pregunta': p.pregunta, 'criterio': p.criterio,
                'respuesta': (r.respuesta or '')[:1500], 'sin_datos': r.sin_datos,
            })
            tokens_in += r.tokens_entrada
            tokens_out += r.tokens_salida
        except Exception as exc:
            logger.warning("Evaluación agente %s: pregunta falló: %s", agente.id, exc)
            filas.append({
                'pregunta': p.pregunta, 'criterio': p.criterio,
                'respuesta': f'(error del motor: {exc})'[:500], 'sin_datos': True,
            })

    # Juez LLM — UNA sola llamada batch para todas las preguntas.
    from agents_ai.ai_actions import build_llm, parse_json_response
    partes = []
    for i, f in enumerate(filas, start=1):
        partes.append(
            f"ÍTEM {i}:\nPREGUNTA: {f['pregunta'][:300]}\n"
            f"CRITERIO: {f['criterio'][:300] or '(sin criterio)'}\n"
            f"RESPUESTA DEL BOT: {f['respuesta']}"
        )
    veredictos = {}
    try:
        llm, modelo, provider = build_llm(apikey_obj, force_json=True, max_tokens=3000, temperature=0.1)
        respuesta_juez = llm.invoke(_PROMPT_JUEZ.format(items='\n\n'.join(partes)))
        t_in, t_out = provider.extract_tokens(respuesta_juez)
        tokens_in += t_in
        tokens_out += t_out
        data = parse_json_response(respuesta_juez.content)
        for v in data.get('resultados', []):
            veredictos[v.get('i')] = v
    except Exception as exc:
        logger.warning("Evaluación agente %s: juez LLM falló: %s", agente.id, exc)

    resultados, aprobadas, suma = [], 0, 0
    for i, f in enumerate(filas, start=1):
        v = veredictos.get(i, {})
        score = _clamp_score(v.get('score'))
        inventa = bool(v.get('inventa'))
        aprobada = score >= _UMBRAL_APROBADA and not inventa
        if aprobada:
            aprobadas += 1
        suma += score
        resultados.append({
            'pregunta': f['pregunta'], 'criterio': f['criterio'],
            'respuesta': f['respuesta'], 'sin_datos': f['sin_datos'],
            'uso_datos': bool(v.get('uso_datos')), 'inventa': inventa,
            'cumple_criterio': v.get('cumple_criterio'),
            'score': score, 'comentario': str(v.get('comentario') or '')[:200],
            'aprobada': aprobada,
        })

    score_global = round(suma / len(filas), 1) if filas else 0
    evaluacion = EvaluacionAgente.objects.create(
        agente=agente, score=score_global,
        total_preguntas=len(filas), aprobadas=aprobadas,
        resultados=resultados, tokens_total=tokens_in + tokens_out,
    )
    try:
        if tokens_in or tokens_out:
            ConsumoTokenIA.objects.create(
                apikey=apikey_obj, agente=agente,
                tokens_entrada=tokens_in, tokens_salida=tokens_out,
                tokens_total=tokens_in + tokens_out,
                modelo=(apikey_obj.modelo or ''), origen='auditor',
                prompt_preview=f'Evaluación de agente ({len(filas)} preguntas)',
            )
    except Exception:
        logger.exception('No se pudo registrar el consumo de la evaluación')
    return evaluacion
