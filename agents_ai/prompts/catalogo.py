"""Catálogo central de prompts del motor de IA.

Registro declarativo (datos puros, sin imports pesados) de TODOS los prompts que
el motor envía a un LLM, más los fragmentos de instrucción que se inyectan a un
prompt (guías de ánimo, presets de personalidad). Sirve para:

  - saber de un vistazo qué prompts existen, dónde viven y dónde se usan;
  - auditar/medir el consumo por prompt;
  - a futuro, exponerlos en el Centro de IA (`/crm/centro-ia/`).

Este módulo NO contiene el texto de los prompts (esos viven en su archivo
fuente): es un índice. Cada entrada apunta a `ubicacion` (archivo → símbolo).
Mantener sincronizado al crear/mover/borrar un prompt del motor.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptInfo:
    clave: str            # identificador estable en snake_case
    grupo: str            # agrupación funcional (ver GRUPOS)
    ubicacion: str        # archivo → símbolo donde se define
    usado_en: str         # función/flujo que lo invoca
    proposito: str        # una frase
    tipo: str             # 'estatico' | 'dinamico' | 'seleccion'
    variables: tuple = field(default_factory=tuple)
    invoca_llm: bool = True


GRUPOS = (
    'consultor',       # chat conversacional WhatsApp (motor principal)
    'cierre',          # resumen + sentimiento al cerrar conversación
    'ai_actions',      # asistentes one-shot de generación de configuración
    'auditor',         # auditoría de configuración de un agente
    'evaluacion',      # juez LLM de calidad de un agente
    'rag',             # conocimiento / memoria / reproceso
    'personalidad',    # presets de persona inyectados al prompt del consultor
    'voz_multimodal',  # voz telefónica e imagen (fuera de prompts/)
)


CATALOGO = (
    # ── Grupo consultor ──────────────────────────────────────────────
    PromptInfo(
        clave='consultor_master_es',
        grupo='consultor',
        ubicacion="agents_ai/prompts/plantillas.py → PROMPT_TEMPLATES['es']",
        usado_en="AgenteConsultor._formatear_prompt/consultar (agente_consultor.py) — fallback del prompt_template del agente",
        proposito="Template maestro del bot conversacional: responde como persona por WhatsApp sin inventar datos fuera del contexto entre ====.",
        tipo='dinamico',
        variables=(
            'nombre_bot', 'descripcion_agente', 'personalidad', 'tono', 'estilo_escritura',
            'contacto_nombre', 'hora_local', 'primera_vez_hoy', 'estado_animo', 'guia_animo',
            'historial_contacto', 'contexto_extra', 'question', 'context',
        ),
    ),
    PromptInfo(
        clave='consultor_recomendado',
        grupo='consultor',
        ubicacion="agents_ai/prompts/recomendados.py → PROMPT_RECOMENDADO",
        usado_en="Tab 'Prompt' del editor de agente (crm/.../entrenamiento/agente/form.html, var prompt_recomendado) — el usuario lo copia como su prompt_template",
        proposito="Plantilla de arranque genérica y editable con reglas anti-alucinación. No la invoca el motor directamente.",
        tipo='dinamico',
        variables=('nombre_bot', 'personalidad', 'tono', 'estilo_escritura', 'context', 'contexto_extra', 'question'),
        invoca_llm=False,
    ),
    PromptInfo(
        clave='fin_conversacion',
        grupo='consultor',
        ubicacion="agents_ai/agente_consultor.py → _FIN_INSTRUCCION + FIN_SIGNAL",
        usado_en="Se concatena al prompt_template cuando no lo trae; consultar() detecta [FIN_CONVERSACION] para cerrar.",
        proposito="Pide al LLM marcar [FIN_CONVERSACION] cuando el cliente se despide.",
        tipo='estatico',
    ),
    PromptInfo(
        clave='resumen_rodante',
        grupo='consultor',
        ubicacion="agents_ai/agente_consultor.py → _actualizar_resumen_rodante (prompt inline)",
        usado_en="Cada _RESUMEN_CADA_N=6 mensajes comprime los turnos fuera de la ventana reciente.",
        proposito="Resumen compacto (≤700 chars) de datos útiles para continuidad intra-conversación.",
        tipo='dinamico',
        variables=('base', 'lineas'),
    ),
    PromptInfo(
        clave='guias_animo',
        grupo='consultor',
        ubicacion="agents_ai/humanizacion.py → _GUIAS_ANIMO / _ANIMO_PATRONES / detectar_animo",
        usado_en="_formatear_prompt rellena {estado_animo}/{guia_animo} del template maestro (regex, sin LLM).",
        proposito="Fragmentos de instrucción de tono inyectados según el ánimo detectado.",
        tipo='seleccion',
        invoca_llm=False,
    ),
    PromptInfo(
        clave='bienvenida_fallback',
        grupo='consultor',
        ubicacion="agents_ai/agente_consultor.py → _saludo_primer_mensaje",
        usado_en="Responde el primer mensaje/saludo sin gastar tokens (usa mensaje_bienvenida o saludo_por_hora).",
        proposito="Saludo inicial sin LLM.",
        tipo='seleccion',
        invoca_llm=False,
    ),

    # ── Grupo cierre ─────────────────────────────────────────────────
    PromptInfo(
        clave='resumidor_cierre',
        grupo='cierre',
        ubicacion="agents_ai/agente_resumidor.py → AgenteResumidor.resumir (prompt inline)",
        usado_en="Al cerrar una conversación; el resumen se indexa como conocimiento RAG.",
        proposito="Resumen claro/breve/cronológico de la conversación cliente-asistente.",
        tipo='dinamico',
        variables=('texto_chat',),
    ),
    PromptInfo(
        clave='sentimiento',
        grupo='cierre',
        ubicacion="agents_ai/agente_resumidor.py → AgenteResumidor.analizar_sentimiento (prompt inline)",
        usado_en="Al cierre/análisis de conversación.",
        proposito="Análisis de sentimiento en JSON (sentimiento, puntuacion 1-10, resumen).",
        tipo='dinamico',
        variables=('texto_chat',),
    ),

    # ── Grupo ai_actions (registry PROMPTS de ai_actions/prompts.py) ──
    PromptInfo(
        clave='pipeline_wa', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['pipeline_wa']",
        usado_en="ai_actions/pipeline_wa.py", proposito="Genera pipeline Kanban de ventas en JSON.",
        tipo='dinamico', variables=('n_min', 'n_max', 'descripcion'),
    ),
    PromptInfo(
        clave='campanas_wa', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['campanas_wa']",
        usado_en="ai_actions/campanas_wa.py", proposito="Genera campaña de marketing multicanal.",
        tipo='dinamico', variables=('canal_principal', 'descripcion_usuario'),
    ),
    PromptInfo(
        clave='horarios_wa_semanales', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['horarios_wa.semanales']",
        usado_en="ai_actions/horarios_wa.py", proposito="Convierte descripción en horarios semanales JSON.",
        tipo='dinamico', variables=('descripcion',),
    ),
    PromptInfo(
        clave='horarios_wa_excepciones', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['horarios_wa.excepciones']",
        usado_en="ai_actions/horarios_wa.py", proposito="Feriados/excepciones a fechas JSON.",
        tipo='dinamico', variables=('anio_actual', 'descripcion'),
    ),
    PromptInfo(
        clave='plantillas_wa_uno', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['plantillas_wa.uno']",
        usado_en="ai_actions/plantillas_wa.py", proposito="Genera UNA plantilla Meta WhatsApp.",
        tipo='dinamico', variables=('contexto_negocio', 'descripcion_usuario'),
    ),
    PromptInfo(
        clave='plantillas_wa_editar', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['plantillas_wa.editar']",
        usado_en="ai_actions/plantillas_wa.py", proposito="Edición asistida de plantilla existente.",
        tipo='dinamico', variables=('plantilla_json', 'instruccion'),
    ),
    PromptInfo(
        clave='plantillas_wa_lote', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['plantillas_wa.lote']",
        usado_en="ai_actions/plantillas_wa.py", proposito="Genera N plantillas en lote.",
        tipo='dinamico', variables=('n', 'descripcion', 'contexto_negocio'),
    ),
    PromptInfo(
        clave='herramientas_crm', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['herramientas_crm']",
        usado_en="ai_actions/herramientas_crm.py", proposito="Config de HerramientaAgente (tool API) desde lenguaje natural.",
        tipo='dinamico', variables=('descripcion_usuario',),
    ),
    PromptInfo(
        clave='agentes_crm', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['agentes_crm']",
        usado_en="ai_actions/agentes_crm.py", proposito="Arquitecto: genera un AgentesIA completo (incl. prompt_template).",
        tipo='dinamico', variables=('tono', 'idioma', 'descripcion_usuario'),
    ),
    PromptInfo(
        clave='dpchatbots_crm', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['dpchatbots_crm']",
        usado_en="ai_actions/dpchatbots_crm.py", proposito="Genera departamento chatbot con menú jerárquico.",
        tipo='dinamico', variables=('tipo_negocio', 'descripcion', 'tono', 'tono_title'),
    ),
    PromptInfo(
        clave='dpchatbots_wizard', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['dpchatbots_wizard']",
        usado_en="ai_actions/dpchatbots_crm.py", proposito="Arma proceso conversacional Q&A desde cuestionario.",
        tipo='dinamico',
        variables=('descripcion', 'tipo_negocio', 'tono', 'tono_title', 'objetivo', 'datos_cliente', 'opciones_menu', 'handoff_cuando'),
    ),
    PromptInfo(
        clave='dpchatbots_chat', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/prompts.py → PROMPTS['dpchatbots_chat']",
        usado_en="ai_actions/dpchatbots_crm.py", proposito="Asistente multi-turno que refina el flujo por chat.",
        tipo='dinamico', variables=('historial', 'borrador', 'mensaje'),
    ),
    PromptInfo(
        clave='dpchatbot_explicar', grupo='ai_actions',
        ubicacion="agents_ai/ai_actions/dpchatbots_crm.py → explicar_flujo (prompt inline, NO en registry)",
        usado_en="ai_actions/dpchatbots_crm.py::explicar_flujo", proposito="Explica en lenguaje natural un flujo de chatbot ya construido.",
        tipo='dinamico', variables=('depto_nombre', 'depto_mensaje_saludo', 'flujo_txt'),
    ),

    # ── Grupo auditor ────────────────────────────────────────────────
    PromptInfo(
        clave='auditor_system',
        grupo='auditor',
        ubicacion="agents_ai/auditor_agente.py → AUDITOR_SYSTEM_PROMPT (+ construir_prompt_auditor)",
        usado_en="ejecutar_auditoria — antepone el system prompt a las métricas del agente.",
        proposito="Meta-prompt que audita config del agente (prompt_template + contexto estático) y devuelve mejoras en JSON.",
        tipo='dinamico',
        variables=('agente', 'perfil', 'metricas'),
    ),

    # ── Grupo evaluacion ─────────────────────────────────────────────
    PromptInfo(
        clave='evaluacion_juez',
        grupo='evaluacion',
        ubicacion="crm/funciones_evaluacion_agente.py → _PROMPT_JUEZ",
        usado_en="ejecutar_evaluacion — juez batch que califica todas las respuestas en 1 llamada.",
        proposito="Puntúa 0-10 por pregunta (uso_datos, inventa, cumple_criterio) en JSON.",
        tipo='dinamico',
        variables=('items',),
    ),

    # ── Grupo rag ────────────────────────────────────────────────────
    PromptInfo(
        clave='resumen_negocio_precomputado',
        grupo='rag',
        ubicacion="agents_ai/rag/reproceso.py → _PROMPT_RESUMEN",
        usado_en="reprocesar_agente — cuando el material estático supera el umbral.",
        proposito="Resumen estructurado (≤20 líneas) del negocio como contexto base.",
        tipo='dinamico',
        variables=('muestra',),
    ),

    # ── Grupo personalidad (fragmentos inyectados, sin LLM propio) ────
    PromptInfo(
        clave='personalidad_presets',
        grupo='personalidad',
        ubicacion="agents_ai/prompts/personalidades.py → PERSONALIDAD_PRESETS",
        usado_en="AgentesIA.save() auto-rellena nombre_bot/personalidad/tono/estilo/temperature; alimentan el template maestro.",
        proposito="Fragmentos de persona/estilo inyectados como {personalidad}/{estilo_escritura} del consultor.",
        tipo='seleccion',
        invoca_llm=False,
    ),

    # ── Grupo voz_multimodal (fuera de prompts/) ─────────────────────
    PromptInfo(
        clave='voz_telefonica',
        grupo='voz_multimodal',
        ubicacion="voz/services.py → pensar() (prompt inline)",
        usado_en="Pipeline de voz STT→LLM→TTS para llamadas telefónicas.",
        proposito="Asistente telefónico; respuestas de máx 2 oraciones en español hablado.",
        tipo='dinamico',
        variables=('contexto', 'texto_usuario'),
    ),
    PromptInfo(
        clave='chat_multimodal_imagen',
        grupo='voz_multimodal',
        ubicacion="crm/view_chat_agente.py → prompt_text (inline)",
        usado_en="Chat de prueba del agente cuando el usuario adjunta una imagen (multimodal).",
        proposito="Pide al modelo analizar la imagen respondiendo como el agente.",
        tipo='dinamico',
        variables=('descripcion_agente', 'contexto_estatico', 'texto_adicional'),
    ),
)


def por_clave(clave: str):
    """Devuelve el PromptInfo con esa clave, o None."""
    for p in CATALOGO:
        if p.clave == clave:
            return p
    return None


def por_grupo(grupo: str):
    """Lista los PromptInfo de un grupo."""
    return [p for p in CATALOGO if p.grupo == grupo]


def claves():
    """Todas las claves del catálogo."""
    return tuple(p.clave for p in CATALOGO)
