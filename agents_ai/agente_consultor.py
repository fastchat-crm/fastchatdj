import logging
import os
import json
from dataclasses import dataclass

from langchain_core.prompts import PromptTemplate
from .providers import get_provider, get_llm_cached, get_embeddings_cached
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

from whatsapp.models import ConversacionWhatsApp
from .memoria.historial import DjangoChatMessageHistory
from .consultor.clasificacion import (
    normalizar_texto,
    _es_saludo,
    _es_ack_simple,
    _es_consulta_amplia,
    _GREETING_WORDS,
)
from .consultor.retrieval import (
    _get_vectorstore_cached,
    invalidate_vectorstore_cache,
    _get_bm25_cached,
    _hybrid_search,
    _dedup_preservando_orden,
    _trim_contexto,
    _extraer_seccion_relevante,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resultado de consulta
# ---------------------------------------------------------------------------

FIN_SIGNAL = "[FIN_CONVERSACION]"

_FIN_INSTRUCCION = (
    "\n\nIMPORTANTE: Si detectas que el usuario se está despidiendo o que la conversación "
    "ha llegado a su conclusión natural, añade exactamente [FIN_CONVERSACION] al final "
    "de tu respuesta, después del punto final. No lo incluyas en ningún otro caso."
)


@dataclass
class ConsultaResultado:
    respuesta: str
    fin_detectado: bool = False
    tokens_entrada: int = 0
    tokens_salida: int = 0
    tokens_total: int = 0
    sin_datos: bool = False  # True cuando el agente no tiene documentos cargados


# ---------------------------------------------------------------------------
# Parámetros de control de tokens
# ---------------------------------------------------------------------------
_FAISS_K           = 5      # chunks a recuperar
_FAISS_FETCH_K     = 20     # candidatos pre-MMR
_MAX_CONTEXT_CHARS = 4_000  # techo del contexto FAISS para consultas específicas
_MAX_STATIC_CHARS  = 1_200  # máx chars del contexto estático en Modo B (suplemento)
_HISTORY_TURNS     = 5      # turnos de historial (5 turnos = 10 mensajes) — suficiente para continuidad típica
_USER_SNIPPET      = 150    # chars por mensaje de usuario en historial
_AI_SNIPPET        = 400    # chars por respuesta IA en historial
_MAX_OUTPUT_TOKENS = 3000   # tokens de salida — suficiente para menús completos con pizzas/precios
_TOPIC_ANCHOR_CHARS = 180   # chars del primer mensaje sustantivo como ancla de tema
_UMBRAL_DISTANCIA  = 1.4    # distancia L2² máx de un chunk relevante (embeddings normalizados: ≈ coseno 0.3)
_TEMPERATURE_TOOLS = 0.2    # temperatura máx durante tool-calling — argumentos deterministas
_MAX_STATIC_AMPLIA = 12_000 # techo del contexto estático completo en consultas amplias (Modo A)
_RESUMEN_CADA_N    = 6      # mensajes entre refrescos del resumen rodante (patrón backmanageria)
_RESUMEN_MAX_CHARS = 700    # techo del resumen rodante reinyectado al historial
_FAQ_MATCH_RATIO   = 0.92   # similitud mínima para responder una FAQ directa sin LLM

# La clasificación de mensajes (saludos/acks/consultas amplias) vive en
# consultor/clasificacion.py y el retrieval (cache FAISS, BM25, híbrida,
# recortes) en consultor/retrieval.py.

# ---------------------------------------------------------------------------
# AgenteConsultor
# ---------------------------------------------------------------------------

class AgenteConsultor:
    def __init__(
        self,
        vectorstore_path,
        vectorstore_enlaces_path,
        provider,
        apikey,
        model_name=None,
        conversacion=None,
        prompt_template_text='',
        contexto_estatico=None,
        detectar_fin: bool = False,
        perfil=None,
        agente=None,
        base_url=None,
    ):
        # Provider: acepta string ('gemini', 'openai') o int (2, 3) — ver providers/__init__.py
        self._provider_obj = get_provider(provider)
        self.provider = self._provider_obj.name  # mantiene API pública previa para compat
        self.apikey = apikey
        self.base_url = (base_url or '').strip() or None
        self.model_name = model_name or self.default_model()
        self.vectorstore_path = vectorstore_path
        self.vectorstore_enlaces_path = vectorstore_enlaces_path
        self.contexto_estatico: str | None = contexto_estatico or None
        self.detectar_fin = detectar_fin
        self.perfil = perfil  # PerfilNegocioIA — usado por herramientas de tool-calling
        self.agente = agente  # AgentesIA — usado para cargar HerramientaAgente dinámicas

        # Configuración avanzada — lee del agente si está seteado, sino usa el constante
        def _cfg(field, default):
            if agente is None:
                return default
            val = getattr(agente, field, None)
            return val if val else default

        self.cfg_faiss_k           = _cfg('cfg_faiss_k', _FAISS_K)
        self.cfg_faiss_fetch_k     = _cfg('cfg_faiss_fetch_k', _FAISS_FETCH_K)
        self.cfg_max_context_chars = _cfg('cfg_max_context_chars', _MAX_CONTEXT_CHARS)
        self.cfg_max_static_chars  = _cfg('cfg_max_static_chars', _MAX_STATIC_CHARS)
        self.cfg_history_turns     = _cfg('cfg_history_turns', _HISTORY_TURNS)
        self.cfg_user_snippet      = _cfg('cfg_user_snippet', _USER_SNIPPET)
        self.cfg_ai_snippet        = _cfg('cfg_ai_snippet', _AI_SNIPPET)
        self.cfg_max_output_tokens = _cfg('cfg_max_output_tokens', _MAX_OUTPUT_TOKENS)
        self.cfg_topic_anchor_chars = _cfg('cfg_topic_anchor_chars', _TOPIC_ANCHOR_CHARS)
        self.cfg_umbral_distancia  = _cfg('cfg_umbral_distancia', _UMBRAL_DISTANCIA)
        self.cfg_max_static_amplia = _cfg('cfg_max_static_amplia', _MAX_STATIC_AMPLIA)
        self.desglose_prompt = {}

        # Persona del bot — si el agente no tiene los campos (agentes viejos), defaults neutros.
        # Si el agente tiene un `personalidad_preset` distinto de 'personalizado',
        # los valores del preset mandan sobre los campos manuales (red de seguridad
        # en runtime para agentes guardados antes del preset o que se editaron por admin).
        _preset_key = _cfg('personalidad_preset', 'personalizado')
        _preset = None
        if _preset_key and _preset_key != 'personalizado':
            try:
                from core.constantes import PERSONALIDAD_PRESETS
                _preset = PERSONALIDAD_PRESETS.get(_preset_key)
            except Exception:
                _preset = None

        def _persona(campo, default):
            if _preset and _preset.get(campo):
                return _preset[campo]
            return _cfg(campo, default)

        self.cfg_nombre_bot       = _persona('nombre_bot', 'Asistente')
        self.cfg_personalidad     = _persona('personalidad', '')
        self.cfg_tono             = _persona('tono', 'amigable')
        self.cfg_estilo_escritura = _persona('estilo_escritura', '')
        # temperature — DecimalField, convertir a float para el provider.
        # Default subido a 0.75 para variabilidad humana sin alucinaciones.
        if _preset and _preset.get('temperature') is not None:
            _temp_raw = _preset['temperature']
        else:
            _temp_raw = _cfg('temperature', None)
        try:
            self.cfg_temperature = float(_temp_raw) if _temp_raw is not None else 0.75
        except (TypeError, ValueError):
            self.cfg_temperature = 0.75

        # Memoria RAG por agente — aprende de conversaciones previas (True salvo
        # que el agente la desactive explícitamente).
        self.cfg_memoria_activa = (
            agente is not None and bool(getattr(agente, 'memoria_rag_activa', True))
        )

        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.vectorstore = self._load_vectorstore()
        self.vectorstore_enlaces = self._load_vectorstore_enlaces()
        self._bm25 = _get_bm25_cached(self.vectorstore_path, self.vectorstore, self.cfg_faiss_k)
        self._bm25_enlaces = _get_bm25_cached(
            self.vectorstore_enlaces_path, self.vectorstore_enlaces, self.cfg_faiss_k
        )
        self.conversacion: ConversacionWhatsApp = conversacion

        # Historial — acceso directo, sin ConversationBufferMemory (era dead code)
        self._historia: DjangoChatMessageHistory | None = (
            DjangoChatMessageHistory(session_id=str(conversacion.id))
            if conversacion else None
        )

        # Pre-compilar PromptTemplate una sola vez (no en cada llamada)
        _VARS_REQUERIDAS = {
            'question', 'context', 'descripcion_agente', 'contexto_extra',
            # Persona (humanización) — opcionales en templates antiguos
            'nombre_bot', 'personalidad', 'tono', 'estilo_escritura',
            # Variables del contacto y del momento
            'contacto_nombre', 'hora_local', 'primera_vez_hoy',
            # Señal de ánimo detectada en el mensaje actual
            'estado_animo', 'guia_animo',
            # Memoria persistente cruzada (resúmenes de conversaciones anteriores)
            'historial_contacto',
            # Horario laboral + primer mensaje (agregadas para agentes que las usen)
            'fuera_horario', 'horario_atencion', 'es_primer_mensaje',
            # Canal de la conversación (whatsapp/instagram/tiktok/messenger)
            'canal',
        }
        _tpl_text = prompt_template_text
        if _tpl_text:
            _tpl_candidato = PromptTemplate.from_template(f'{_tpl_text}\n')
            _vars_extra = set(_tpl_candidato.input_variables) - _VARS_REQUERIDAS
            if _vars_extra:
                logger.warning(
                    "Prompt del agente tiene variables desconocidas %s — usando template por defecto",
                    _vars_extra,
                )
                from core.constantes import PROMPT_TEMPLATES
                _tpl_text = PROMPT_TEMPLATES.get('es', '')
        if detectar_fin:
            _tpl_text += _FIN_INSTRUCCION
        self._prompt_tpl = PromptTemplate.from_template(f'{_tpl_text}\n')

        self.listas_memoria: dict = {}
        self._listas_cargadas = False  # lazy — solo el flujo con tools las necesita
        self._faq_ids_usadas: list = []  # rellenado por _construir_contexto

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def default_model(self) -> str:
        return self._provider_obj.default_model()

    _PROVEEDORES_CON_EMBEDDINGS = (2, 3, 5)

    def _get_embeddings(self):
        # Providers sin API de embeddings (Claude, DeepSeek, Huawei) no bloquean
        # el chat: se busca otra API Key del agente que sí soporte embeddings
        # (Gemini/OpenAI/Ollama) para mantener FAISS y memoria; si no hay,
        # el agente sigue en Modo A (contexto estático + FAQs).
        try:
            return get_embeddings_cached(self._provider_obj, self.apikey, base_url=self.base_url)
        except NotImplementedError as exc:
            if self.agente is not None:
                try:
                    keys = self.agente.apikey.filter(
                        estado=True, status=True,
                        proveedor__in=self._PROVEEDORES_CON_EMBEDDINGS,
                    ).exclude(descripcion='')
                    for k in keys:
                        try:
                            return get_embeddings_cached(
                                get_provider(k.proveedor),
                                k.descripcion,
                                base_url=(getattr(k, 'base_url', '') or None),
                            )
                        except Exception:
                            continue
                except Exception:
                    pass
            logger.warning("Provider %s sin embeddings y sin key alternativa — se omite FAISS: %s",
                           self.provider, exc)
            return None

    def _get_llm(self):
        # Temperature configurable por agente. Default 0.75 = humano natural.
        # Cada preset puede pisar este valor (ej: formal=0.50, vendedor=0.90).
        return get_llm_cached(
            self._provider_obj,
            apikey=self.apikey,
            model_name=self.model_name,
            max_output_tokens=self.cfg_max_output_tokens,
            temperature=self.cfg_temperature,
            base_url=self.base_url,
        )

    def _load_vectorstore(self):
        if not self.vectorstore_path:
            return None
        if not os.path.exists(self.vectorstore_path):
            logger.warning("Vectorstore no encontrado en %s", self.vectorstore_path)
            return None
        try:
            return _get_vectorstore_cached(self.vectorstore_path, self.embeddings)
        except Exception as e:
            logger.error("Error cargando vectorstore %s: %s", self.vectorstore_path, e)
            return None

    def _load_vectorstore_enlaces(self):
        if not self.vectorstore_enlaces_path:
            return None
        if not os.path.exists(self.vectorstore_enlaces_path):
            logger.warning("Vectorstore de enlaces no encontrado en %s", self.vectorstore_enlaces_path)
            return None
        try:
            return _get_vectorstore_cached(self.vectorstore_enlaces_path, self.embeddings)
        except Exception as e:
            logger.error("Error cargando vectorstore de enlaces %s: %s", self.vectorstore_enlaces_path, e)
            return None

    # ------------------------------------------------------------------
    # Variables de contacto (humanización)
    # ------------------------------------------------------------------

    def _historial_persistente(self) -> str:
        """Devuelve el resumen persistente del contacto (PerfilContacto.resumen).

        Si no hay perfil o no hay resumen previo → string vacío. Se inyecta al
        prompt para que el bot reconozca al cliente recurrente sin releer cada
        mensaje de conversaciones anteriores.
        """
        if not (self.conversacion and self.conversacion.contacto_id):
            return ''
        try:
            perfil = getattr(self.conversacion.contacto, 'perfil_persistente', None)
            if perfil and perfil.resumen:
                return perfil.resumen.strip()
        except Exception:
            pass
        return ''

    def _vars_contacto(self) -> dict:
        """Devuelve variables relativas al contacto y al momento de la conversación:
        - contacto_nombre : primer nombre o 'cliente'
        - hora_local      : 'mañana (09:45)' / 'tarde (15:10)' / 'noche (22:30)'
        - primera_vez_hoy : 'sí' si no hay mensajes previos de hoy en esta conversación
        """
        from django.utils import timezone as _tz

        nombre = 'cliente'
        try:
            if self.conversacion and self.conversacion.contacto:
                raw = (self.conversacion.contacto.contacto_nombre or '').strip()
                if raw:
                    # Tomar primer token, capitalizar
                    nombre = raw.split()[0].strip().capitalize()
        except Exception:
            pass

        _now = _tz.now()
        ahora = _tz.localtime(_now) if _tz.is_aware(_now) else _now
        hora = ahora.hour
        if hora < 12:
            franja = 'mañana'
        elif hora < 19:
            franja = 'tarde'
        else:
            franja = 'noche'
        hora_local = f"{franja} ({ahora.strftime('%H:%M')})"

        primera_vez_hoy = 'sí'
        try:
            h = self._historia
            if h:
                # Últimos 2 mensajes humanos — si alguno fue hoy antes del actual, no es primera vez
                from .models import MessageStore
                hoy_ini = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
                hubo_hoy = (
                    MessageStore.objects
                    .filter(session_id=h.session_id, role='human', created_at__gte=hoy_ini)
                    .exists()
                )
                if hubo_hoy:
                    primera_vez_hoy = 'no'
        except Exception:
            pass

        return {
            'contacto_nombre': nombre,
            'hora_local': hora_local,
            'primera_vez_hoy': primera_vez_hoy,
        }

    def _canal_conversacion(self) -> str:
        """Canal por el que atiende esta conversación: whatsapp/instagram/tiktok/messenger.

        Los proveedores internos baileys y meta son ambos 'whatsapp' de cara al
        prompt — al agente le importa la red social, no el transporte.
        """
        try:
            sesion = self.conversacion.sesion if self.conversacion else None
            proveedor = (getattr(sesion, 'proveedor', '') or '').lower()
            if proveedor in ('instagram', 'tiktok', 'messenger'):
                return proveedor
        except Exception:
            pass
        return 'whatsapp'

    def _vars_horario(self) -> dict:
        fuera = 'false'
        etiqueta = '(no configurado)'
        try:
            sesion = self.conversacion.sesion if self.conversacion else None
            if sesion:
                from whatsapp.services_horarios import dentro_de_horario
                fuera = 'false' if dentro_de_horario(sesion) else 'true'
                try:
                    horarios = sesion.horarios.filter(status=True).order_by('dia_semana', 'hora_inicio')
                    if horarios.exists():
                        etiqueta = ' · '.join(str(h) for h in horarios[:7])
                except Exception:
                    pass
        except Exception:
            pass
        return {'fuera_horario': fuera, 'horario_atencion': etiqueta}

    # ------------------------------------------------------------------
    # Historial
    # ------------------------------------------------------------------

    def _chat_history(self) -> DjangoChatMessageHistory | None:
        return self._historia

    def _es_primer_mensaje(self) -> bool:
        h = self._historia
        return h is None or h.count() == 0

    def _contexto_previo(self) -> str:
        """
        Devuelve los últimos N turnos como texto compacto, precedidos por el
        resumen rodante de lo que ya salió de la ventana (continuidad barata).
        Trunca para minimizar tokens: usuario → _USER_SNIPPET chars, IA → _AI_SNIPPET chars.
        """
        h = self._historia
        if not h:
            return ""

        resumen = ""
        try:
            data = h.get_resumen_rodante()
            if data and (data.get('texto') or '').strip():
                resumen = f"Resumen de lo conversado antes: {data['texto'].strip()}\n"
        except Exception:
            resumen = ""

        mensajes = h.get_recent(self.cfg_history_turns * 2)
        if not mensajes:
            return resumen

        partes = []
        for msg in mensajes:
            if isinstance(msg, HumanMessage):
                t = msg.content[:self.cfg_user_snippet]
                partes.append(f"U: {t}{'…' if len(msg.content) > self.cfg_user_snippet else ''}")
            elif isinstance(msg, AIMessage):
                t = msg.content[:self.cfg_ai_snippet]
                partes.append(f"A: {t}{'…' if len(msg.content) > self.cfg_ai_snippet else ''}")

        return resumen + "Historial reciente:\n" + "\n".join(partes) + "\n\n"

    def _tema_inicial(self) -> str:
        """Primer mensaje sustantivo del usuario en esta conversación.

        Se usa como ancla de tema en FAISS cuando el historial reciente
        ya no incluye el contexto original (por rotación de turnos).
        """
        h = self._historia
        if not h:
            return ""
        try:
            from .models import MessageStore
            first = (
                MessageStore.objects
                .filter(session_id=h.session_id, role="human")
                .order_by("created_at")
                .values_list("content", flat=True)
                .first()
            )
            if first and len(first) >= 15 and not _es_ack_simple(first) and not _es_saludo(first):
                return first[:self.cfg_topic_anchor_chars]
        except Exception:
            pass
        return ""

    def _query_retrieval(self, pregunta: str, contexto_previo: str) -> str:
        """
        Enriquece el query FAISS para preguntas de seguimiento.

        Estrategia en capas:
        1. Pregunta actual
        2. Último mensaje del usuario (si aporta contexto semántico nuevo)
        3. Extracto de la última respuesta IA (para seguimientos implícitos cortos)
        4. Ancla de tema inicial (cuando el historial ya rotó y la pregunta es huérfana)
        """
        lineas = contexto_previo.splitlines() if contexto_previo else []
        user_lines = [l for l in lineas if l.startswith("U:")]
        ai_lines   = [l for l in lineas if l.startswith("A:")]
        ultimo_user = user_lines[-1].replace("U:", "").strip() if user_lines else ""
        ultimo_ai   = ai_lines[-1].replace("A:", "").strip()[:120] if ai_lines else ""

        ancla_parts = []
        pregunta_lower = pregunta.lower()

        # Capa 2: último mensaje del usuario con contenido semántico
        if ultimo_user and len(ultimo_user) >= 15:
            if ultimo_user.lower().strip('.,!?') not in _GREETING_WORDS:
                if ultimo_user.lower() not in pregunta_lower:
                    ancla_parts.append(ultimo_user[:120])

        # Capa 3: extracto IA para seguimientos cortos ("¿y el precio?")
        if ultimo_ai and len(pregunta.strip()) < 40 and ultimo_ai.lower() not in pregunta_lower:
            ancla_parts.append(ultimo_ai)

        # Capa 4: tema inicial como ancla de último recurso
        # Se activa cuando la pregunta es corta Y no hay ancla de capa 2/3
        if not ancla_parts and len(pregunta.strip()) < 50:
            tema = self._tema_inicial()
            if tema and tema.lower() not in pregunta_lower:
                ancla_parts.append(tema[:100])

        if not ancla_parts:
            return pregunta

        return f"{pregunta} {' '.join(ancla_parts)}"

    # ------------------------------------------------------------------
    # Listas en memoria
    # ------------------------------------------------------------------

    def _cargar_listas_desde_memoria(self):
        if self._listas_cargadas:
            return
        self._listas_cargadas = True
        h = self._historia
        if not h:
            return
        for mensaje in h.get_recent_lista_guardada(n=10):
            try:
                data = json.loads(mensaje.content.replace("LISTA_GUARDADA:", ""))
                self.listas_memoria.update(data)
            except Exception:
                pass

    def _guardar_listas_en_memoria(self):
        h = self._historia
        if not h or not self.listas_memoria:
            return
        data_json = json.dumps(self.listas_memoria, ensure_ascii=False)
        h.add_ai_message(f"LISTA_GUARDADA:{data_json}")

    # ------------------------------------------------------------------
    # Helpers compartidos (contexto, tokens, prompt)
    # ------------------------------------------------------------------

    def _construir_bloque_faq(self) -> tuple[str, list]:
        """Devuelve (bloque_texto, ids_faqs_usadas).

        Trae las top-N FAQs aprobadas del agente (según faqs_en_prompt, default 5)
        ordenadas por prioridad desc y las formatea como sección "## Preguntas
        frecuentes ##" que se inyecta al inicio del contexto. Devuelve "" si el
        agente no tiene agente asociado o no hay FAQs aprobadas.
        """
        if self.agente is None:
            return "", []
        try:
            top_n = max(0, int(getattr(self.agente, 'faqs_en_prompt', 10) or 0))
        except Exception:
            top_n = 10
        if top_n == 0:
            return "", []
        try:
            faqs = list(
                self.agente.faqs.filter(estado='aprobada', status=True)
                .order_by('-prioridad', '-fecha_registro')[:top_n]
                .values('id', 'pregunta', 'respuesta')
            )
        except Exception as exc:
            logger.debug("No se pudieron cargar FAQs del agente: %s", exc)
            return "", []
        if not faqs:
            return "", []
        lineas = ["## Preguntas frecuentes ##"]
        for f in faqs:
            p = (f['pregunta'] or '').strip().replace('\n', ' ')[:300]
            r = (f['respuesta'] or '').strip().replace('\n', ' ')[:500]
            if p and r:
                lineas.append(f"Q: {p}\nA: {r}")
        lineas.append("## fin FAQ ##")
        ids = [f['id'] for f in faqs]
        return "\n".join(lineas), ids

    def _construir_contexto(self, pregunta: str, contexto_previo: str) -> tuple[str, bool]:
        """Construye el contexto RAG combinando FAISS + BM25 + contexto_estatico.

        Retorna (contexto, sin_datos). sin_datos=True si no hay vectorstore ni
        contexto_estatico y el agente debe responder 'No tengo esa información.'
        """
        _sin_datos = False
        _es_ack = _es_ack_simple(pregunta) and not self._es_primer_mensaje()
        _presupuesto = self.cfg_max_context_chars
        _es_amplia = False
        _query_faiss = pregunta
        _query_vector = None

        if _es_ack:
            contexto = ""
            logger.debug("ACK simple — omitiendo FAISS")
        else:
            _query_faiss = self._query_retrieval(pregunta, contexto_previo)
            logger.debug("FAISS query: %r", _query_faiss)

            es_consulta_amplia = _es_consulta_amplia(pregunta)
            _es_amplia = es_consulta_amplia

            if es_consulta_amplia:
                _k = self.cfg_faiss_k * 4
                _lambda = 0.0
                _presupuesto = min(self.cfg_max_context_chars * 2, 8_000)
            else:
                _k = self.cfg_faiss_k
                _lambda = 0.65
                _presupuesto = self.cfg_max_context_chars

            # UNA sola llamada de embedding del query, compartida entre
            # documentos, enlaces y memoria (evita 2 roundtrips extra por mensaje).
            if self.embeddings is not None and (
                self.vectorstore is not None or self.vectorstore_enlaces is not None
                or self._memoria_disponible()
            ):
                try:
                    _query_vector = self.embeddings.embed_query(_query_faiss)
                except Exception as exc:
                    logger.debug("embed_query falló — búsqueda estándar: %s", exc)

            # Umbral solo en consultas específicas — en amplias (menú/catálogo)
            # se quiere TODO el corpus aunque la distancia sea alta.
            _umbral = None if es_consulta_amplia else self.cfg_umbral_distancia
            docs = _hybrid_search(
                self.vectorstore, self._bm25, _query_faiss, _k, _lambda,
                query_vector=_query_vector, umbral_distancia=_umbral,
            )
            docs_enlaces = _hybrid_search(
                self.vectorstore_enlaces, self._bm25_enlaces, _query_faiss, _k, _lambda,
                query_vector=_query_vector, umbral_distancia=_umbral,
            )
            logger.debug(
                "Hybrid: %d docs + %d enlaces (amplia=%s, bm25=%s)",
                len(docs), len(docs_enlaces), es_consulta_amplia, self._bm25 is not None
            )
            todos_docs = _dedup_preservando_orden(docs + docs_enlaces)
            contexto = _trim_contexto(todos_docs, _presupuesto)

            if not contexto and not self.contexto_estatico:
                _sin_datos = True
                contexto = (
                    "SIN_DATOS: No hay documentos de entrenamiento cargados. "
                    "Responde ÚNICAMENTE: \"No tengo esa información.\" "
                    "Prohibido usar conocimiento externo o inventar datos."
                )

        self.desglose_prompt = {'chars_docs': len(contexto) if not _sin_datos else 0}

        if self.contexto_estatico:
            sin_faiss = not contexto
            if sin_faiss:
                if _es_amplia:
                    contexto = self.contexto_estatico[:self.cfg_max_static_amplia]
                else:
                    contexto = _extraer_seccion_relevante(
                        self.contexto_estatico, _query_faiss, _presupuesto
                    )
                logger.debug(
                    "Contexto estático (Modo A): %d chars de %d disponibles (amplia=%s)",
                    len(contexto), len(self.contexto_estatico), _es_amplia,
                )
            else:
                estatico_trim = self.contexto_estatico[:self.cfg_max_static_chars]
                faiss_budget  = _presupuesto - len(estatico_trim)
                faiss_trim    = contexto[:max(faiss_budget, 0)]
                faiss_part    = ("\n\n---\n" + faiss_trim) if faiss_trim else ""
                contexto      = estatico_trim + faiss_part
                logger.debug(
                    "Contexto estático (%d chars) + FAISS (%d chars) = %d total (presupuesto=%d)",
                    len(estatico_trim), len(faiss_trim), len(contexto), _presupuesto,
                )

        self.desglose_prompt['chars_estatico'] = (
            len(contexto) - self.desglose_prompt['chars_docs']
            if self.contexto_estatico else 0
        )

        # ── FAQ top-N inyectadas al inicio del contexto ────────────────
        bloque_faq, faq_ids = self._construir_bloque_faq()
        self.desglose_prompt['chars_faq'] = len(bloque_faq)
        if bloque_faq:
            contexto = f"{bloque_faq}\n\n{contexto}" if contexto else bloque_faq
            # Incrementar hits en background (no bloquear respuesta)
            self._faq_ids_usadas = faq_ids
            if _sin_datos:
                _sin_datos = False  # Tenemos FAQ como respaldo

        # ── APIs externas (fuentes tipo=1 fetch en vivo, sin embeddings) ──
        bloque_apis = self._construir_bloque_apis()
        self.desglose_prompt['chars_apis'] = len(bloque_apis)
        if bloque_apis:
            contexto = f"{contexto}\n\n{bloque_apis}" if contexto else bloque_apis
            if _sin_datos:
                _sin_datos = False

        # ── Memoria RAG — respuestas aprendidas en conversaciones previas ──
        self.desglose_prompt['chars_memoria'] = 0
        if not _es_ack:
            bloque_memoria = self._construir_bloque_memoria(_query_faiss, _query_vector)
            self.desglose_prompt['chars_memoria'] = len(bloque_memoria or '')
            if bloque_memoria:
                contexto = f"{contexto}\n\n{bloque_memoria}" if contexto else bloque_memoria

        self.desglose_prompt['chars_contexto_total'] = len(contexto)
        return contexto, _sin_datos

    def _memoria_disponible(self) -> bool:
        if not (self.cfg_memoria_activa and self.agente is not None):
            return False
        try:
            from .memoria.rag_conversaciones import memoria_existe
            return memoria_existe(self.agente.id)
        except Exception:
            return False

    def _construir_bloque_memoria(self, query: str, query_vector=None) -> str:
        """Bloque compacto con pares pregunta→respuesta de conversaciones previas."""
        if not (self.cfg_memoria_activa and self.agente is not None and self.embeddings is not None):
            return ''
        try:
            from .memoria.rag_conversaciones import recuperar_memoria
            conv_id = str(self.conversacion.id) if self.conversacion else None
            return recuperar_memoria(
                self.agente.id, self.embeddings, query,
                excluir_conversacion=conv_id,
                query_vector=query_vector,
                umbral_distancia=self.cfg_umbral_distancia,
            )
        except Exception as exc:
            logger.debug("Memoria RAG no disponible: %s", exc)
            return ''

    def _memorizar_interaccion(self, pregunta: str, respuesta: str, sin_datos: bool) -> None:
        """Indexa el par pregunta→respuesta en la memoria del agente (background).

        Debounce por agente (cache 10s): en ráfagas de mensajes se descartan
        escrituras intermedias para no apilar hilos ni reescribir el índice
        en cada mensaje.
        """
        if sin_datos or not respuesta:
            return
        if not (self.cfg_memoria_activa and self.agente is not None and self.embeddings is not None):
            return
        # Solo conversaciones REALES de WhatsApp alimentan la memoria — los
        # chats de prueba/simulador/voz usan SimpleNamespace y quedan fuera
        # para no contaminar el conocimiento de producción.
        if not isinstance(self.conversacion, ConversacionWhatsApp):
            return
        try:
            from django.core.cache import cache
            if not cache.add(f'memoria_rag_write_{self.agente.id}_{self.conversacion.id}', 1, 10):
                return
            from .memoria.rag_conversaciones import guardar_interaccion_async
            conv_id = str(self.conversacion.id) if self.conversacion else None
            guardar_interaccion_async(
                self.agente.id, self.embeddings, pregunta, respuesta,
                conversacion_id=conv_id,
            )
        except Exception as exc:
            logger.debug("No se pudo memorizar la interacción: %s", exc)

    def _construir_bloque_apis(self) -> str:
        """Trae el texto de las fuentes API (tipo=1) sin recurrir a embeddings.
        Usa el cache configurado por fuente (`usar_cache`, `tiempo_cache_horas`).
        """
        if self.agente is None:
            return ''
        try:
            return self.agente.fetch_contexto_apis() or ''
        except Exception as exc:
            logger.debug("No se pudo obtener contexto de APIs: %s", exc)
            return ''

    def _formatear_prompt(
        self, pregunta: str, contexto: str, descripcion_agente: str, contexto_previo: str
    ) -> str:
        # Todas las variables posibles — el template solo consume las que declara.
        _vars_todas = {
            'question': pregunta,
            'context': contexto,
            'descripcion_agente': descripcion_agente,
            'contexto_extra': contexto_previo,
            'nombre_bot': self.cfg_nombre_bot,
            'personalidad': self.cfg_personalidad or '(sin personalidad definida)',
            'tono': self.cfg_tono,
            'estilo_escritura': self.cfg_estilo_escritura or '(estilo natural, mensajes cortos)',
        }
        # Variables del contacto (nombre, hora, primera vez hoy) — solo se computan
        # si el template las referencia, para ahorrar una query por mensaje.
        _input_vars = set(getattr(self._prompt_tpl, 'input_variables', []) or [])
        if _input_vars & {'contacto_nombre', 'hora_local', 'primera_vez_hoy'}:
            _vars_todas.update(self._vars_contacto())
        # Detección de ánimo — solo si el template la usa. Regex liviano, no LLM.
        if _input_vars & {'estado_animo', 'guia_animo'}:
            try:
                from .humanizacion import detectar_animo
                etiqueta, guia = detectar_animo(pregunta)
                _vars_todas['estado_animo'] = etiqueta
                _vars_todas['guia_animo'] = guia
            except Exception:
                _vars_todas['estado_animo'] = 'neutral'
                _vars_todas['guia_animo'] = 'tono natural'
        # Memoria persistente del contacto (resumen de conversaciones cerradas).
        # Solo si el template la referencia, para ahorrar una query.
        if 'historial_contacto' in _input_vars:
            _vars_todas['historial_contacto'] = self._historial_persistente()
        if _input_vars & {'fuera_horario', 'horario_atencion'}:
            _vars_todas.update(self._vars_horario())
        if 'canal' in _input_vars:
            _vars_todas['canal'] = self._canal_conversacion()
        if 'es_primer_mensaje' in _input_vars:
            es_primero = 'false'
            try:
                if self.conversacion is not None and hasattr(self.conversacion, 'mensajes'):
                    n = self.conversacion.mensajes.filter(status=True).count() if hasattr(self.conversacion.mensajes, 'filter') else self.conversacion.mensajes.count()
                    if n <= 1:
                        es_primero = 'true'
                else:
                    h = getattr(self, '_historia', None)
                    msgs = list(h.messages) if h else []
                    if len(msgs) <= 1:
                        es_primero = 'true'
            except Exception:
                pass
            _vars_todas['es_primer_mensaje'] = es_primero
        _kwargs = {k: v for k, v in _vars_todas.items() if k in _input_vars}
        try:
            return self._prompt_tpl.format(**_kwargs)
        except KeyError as _ke:
            logger.error("Variable faltante en prompt template: %s — usando fallback", _ke)
            from core.constantes import PROMPT_TEMPLATES
            _tpl_fallback = PromptTemplate.from_template(PROMPT_TEMPLATES.get('es', '') + '\n')
            _fb_vars = set(_tpl_fallback.input_variables)
            _fb_kwargs = {k: v for k, v in _vars_todas.items() if k in _fb_vars}
            return _tpl_fallback.format(**_fb_kwargs)

    @staticmethod
    def _extraer_texto(ai_message) -> str:
        # Gemini con tool-calling puede devolver content como list[dict|str]; .strip() sobre list explota.
        content = getattr(ai_message, 'content', '') if ai_message else ''
        if content is None:
            return ''
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            partes = []
            for parte in content:
                if isinstance(parte, str):
                    partes.append(parte)
                elif isinstance(parte, dict):
                    txt = parte.get('text') or parte.get('content') or ''
                    if isinstance(txt, str):
                        partes.append(txt)
            return '\n'.join(p for p in partes if p).strip()
        return str(content).strip()

    def _extraer_tokens(self, ai_message) -> tuple[int, int]:
        """(tokens_in, tokens_out) desde un AIMessage — delega al provider concreto."""
        return self._provider_obj.extract_tokens(ai_message)

    def _saludo_primer_mensaje(self, pregunta: str) -> str | None:
        """Si es el primer mensaje y es un saludo, devuelve la bienvenida. Sin LLM.

        Prioridad:
        1. mensaje_bienvenida del agente IA (config por agente, sin tokens).
        2. mensaje_bienvenida configurado a nivel sesión (admin).
        3. Saludo variado por franja horaria + nombre del contacto.
        """
        if not (self._es_primer_mensaje() and _es_saludo(pregunta)):
            return None
        bienvenida_agente = getattr(self.agente, 'mensaje_bienvenida', '') if self.agente else ''
        if bienvenida_agente and bienvenida_agente.strip():
            return bienvenida_agente.strip()
        bienvenida = (
            self.conversacion
            and self.conversacion.contacto
            and self.conversacion.contacto.sesion.mensaje_bienvenida
        )
        if bienvenida:
            return bienvenida
        # Saludo variado
        try:
            from .humanizacion import saludo_por_hora
            vc = self._vars_contacto()
            franja = vc['hora_local'].split(' ', 1)[0]  # "mañana (09:45)" → "mañana"
            return saludo_por_hora(franja, vc['contacto_nombre'])
        except Exception:
            return "Hola 👋, ¿en qué te puedo ayudar?"

    def _respuesta_faq_directa(self, pregunta: str) -> str | None:
        """Si la pregunta coincide casi exacta con una FAQ aprobada, devuelve su
        respuesta sin invocar al LLM (0 tokens). El match usa normalización sin
        tildes/mayúsculas y similitud de secuencia con umbral alto para no
        responder FAQs equivocadas."""
        if self.agente is None:
            return None
        q = normalizar_texto(pregunta).strip()
        if len(q) < 8 or _es_ack_simple(pregunta) or _es_saludo(pregunta):
            return None
        try:
            faqs = list(
                self.agente.faqs.filter(estado='aprobada', status=True)
                .values_list('id', 'pregunta', 'respuesta')[:150]
            )
        except Exception:
            return None
        from difflib import SequenceMatcher
        mejor_id, mejor_resp, mejor_ratio = None, None, 0.0
        for fid, fp, fr in faqs:
            fpn = normalizar_texto(fp or '').strip()
            if not fpn or not (fr or '').strip():
                continue
            if fpn == q:
                mejor_id, mejor_resp, mejor_ratio = fid, fr, 1.0
                break
            ratio = SequenceMatcher(None, q, fpn).ratio()
            if ratio > mejor_ratio:
                mejor_id, mejor_resp, mejor_ratio = fid, fr, ratio
        if mejor_resp and mejor_ratio >= _FAQ_MATCH_RATIO:
            try:
                from django.db.models import F
                from crm.models import FaqAgente
                FaqAgente.objects.filter(pk=mejor_id).update(hits=F('hits') + 1)
            except Exception as exc:
                logger.debug("No se pudo incrementar hit de FAQ directa: %s", exc)
            logger.debug("FAQ directa sin LLM (ratio=%.2f, faq=%s)", mejor_ratio, mejor_id)
            return mejor_resp.strip()
        return None

    def _actualizar_resumen_rodante(self) -> tuple[int, int]:
        """Mantiene un resumen compacto de los turnos que salieron de la ventana
        reciente (patrón backmanageria: refresco throttleado cada
        _RESUMEN_CADA_N mensajes, salida capada). Devuelve (tokens_in,
        tokens_out) del refresco, o (0, 0) si no tocó resumir."""
        h = self._historia
        if not h:
            return 0, 0
        try:
            total = h.count_conversacion()
            ventana = self.cfg_history_turns * 2
            if total <= ventana or total % _RESUMEN_CADA_N != 0:
                return 0, 0
            data = h.get_resumen_rodante() or {}
            hasta_previo = int(data.get('hasta') or 0)
            corte = total - ventana
            if corte <= hasta_previo:
                return 0, 0
            rotados = h.get_range(hasta_previo, corte)
            if not rotados:
                return 0, 0
            lineas = []
            for m in rotados:
                prefijo = 'U' if isinstance(m, HumanMessage) else 'A'
                lineas.append(f"{prefijo}: {m.content[:200]}")
            base = (data.get('texto') or '')[:_RESUMEN_MAX_CHARS]
            prompt = (
                "Resume en máximo 5 líneas los datos útiles para continuar esta "
                "conversación (nombres, pedidos, cantidades, decisiones, datos ya "
                "entregados). Sin saludos ni relleno.\n"
                + (f"Resumen previo: {base}\n" if base else "")
                + "Mensajes nuevos:\n" + "\n".join(lineas)
                + "\nResumen actualizado:"
            )
            ai_message = self.llm.invoke(prompt)
            texto = self._extraer_texto(ai_message)[:_RESUMEN_MAX_CHARS]
            if texto:
                h.set_resumen_rodante(texto, corte)
            return self._extraer_tokens(ai_message)
        except Exception as exc:
            logger.debug("Resumen rodante omitido: %s", exc)
            return 0, 0

    # ------------------------------------------------------------------
    # Consulta principal — 1 llamada LLM
    # ------------------------------------------------------------------

    def consultar(self, pregunta: str, descripcion_agente: str = '') -> ConsultaResultado:
        contexto_previo = self._contexto_previo()

        bienvenida = self._saludo_primer_mensaje(pregunta)
        if bienvenida is not None:
            h = self._chat_history()
            if h:
                h.add_user_message(pregunta)
                h.add_ai_message(bienvenida)
            return ConsultaResultado(respuesta=bienvenida)

        respuesta_faq = self._respuesta_faq_directa(pregunta)
        if respuesta_faq is not None:
            h = self._chat_history()
            if h:
                h.add_user_message(pregunta)
                h.add_ai_message(respuesta_faq)
            t_res_in, t_res_out = self._actualizar_resumen_rodante()
            return ConsultaResultado(
                respuesta=respuesta_faq,
                tokens_entrada=t_res_in, tokens_salida=t_res_out,
                tokens_total=t_res_in + t_res_out,
            )

        contexto, _sin_datos = self._construir_contexto(pregunta, contexto_previo)
        prompt_final = self._formatear_prompt(pregunta, contexto, descripcion_agente, contexto_previo)
        self.desglose_prompt['chars_historial'] = len(contexto_previo)
        self.desglose_prompt['chars_prompt_total'] = len(prompt_final)

        try:
            ai_message = self.llm.invoke(prompt_final)
            respuesta = self._extraer_texto(ai_message)
        except Exception as exc:
            logger.error("Error invocando LLM: %s", exc)
            raise

        t_in, t_out = self._extraer_tokens(ai_message)

        fin_detectado = FIN_SIGNAL in respuesta
        if fin_detectado:
            respuesta = respuesta.replace(FIN_SIGNAL, "").strip()

        h = self._chat_history()
        if h:
            h.add_user_message(pregunta)
            h.add_ai_message(respuesta)

        self._incrementar_hits_faqs()
        self._memorizar_interaccion(pregunta, respuesta, _sin_datos)
        t_res_in, t_res_out = self._actualizar_resumen_rodante()

        return ConsultaResultado(
            respuesta=respuesta, fin_detectado=fin_detectado,
            tokens_entrada=t_in + t_res_in, tokens_salida=t_out + t_res_out,
            tokens_total=t_in + t_out + t_res_in + t_res_out,
            sin_datos=_sin_datos,
        )

    # ------------------------------------------------------------------
    # Tool-calling (modo pedido)
    # ------------------------------------------------------------------

    def _build_tools(self) -> list:
        """Construye las herramientas que el LLM puede invocar vía function-calling.

        Las funciones se definen como closures para acceder a self.listas_memoria
        y self.perfil sin necesidad de parámetros ocultos.
        """
        agente_self = self

        @tool
        def agregar_al_pedido(item: str, cantidad: int = 1) -> str:
            """Agrega un producto al pedido del cliente actual.

            Usa esta herramienta cuando el usuario quiera comprar, pedir, reservar
            o añadir algo a su orden. No la uses para consultas o dudas.

            Args:
                item: Nombre del producto tal como lo pidió el usuario.
                cantidad: Cantidad del producto (entero >= 1). Por defecto 1.
            """
            if not item or not item.strip():
                return "Error: item vacío."
            if cantidad < 1:
                return "Error: la cantidad debe ser al menos 1."
            entrada = f"{item.strip()} x{cantidad}" if cantidad > 1 else item.strip()
            lista = agente_self.listas_memoria.setdefault('pedido', {'items': []})
            if entrada in lista['items']:
                return f"Ya estaba en el pedido: {entrada}."
            lista['items'].append(entrada)
            agente_self._guardar_listas_en_memoria()
            return f"OK — agregado '{entrada}'. Pedido actual: {len(lista['items'])} ítem(s)."

        @tool
        def consultar_producto(nombre: str) -> str:
            """Busca productos del catálogo del negocio por nombre o descripción.

            Devuelve hasta 5 coincidencias con precio. Usa esta herramienta antes
            de confirmar un pedido si no estás seguro del nombre exacto o del precio.

            Args:
                nombre: Término de búsqueda — nombre o palabra clave del producto.
            """
            if not agente_self.perfil:
                return "Catálogo no configurado para este agente."
            if not nombre or not nombre.strip():
                return "Error: término de búsqueda vacío."
            try:
                from django.db.models import Q
                qs = agente_self.perfil.get_productos().filter(
                    Q(nombre__icontains=nombre.strip())
                    | Q(descripcion__icontains=nombre.strip())
                )[:5]
                if not qs:
                    return f"No se encontraron productos que coincidan con '{nombre}'."
                lineas = []
                for p in qs:
                    desc = f" — {p.descripcion[:80]}" if p.descripcion else ""
                    lineas.append(f"- {p.nombre}: ${p.precio}{desc}")
                return "\n".join(lineas)
            except Exception as exc:
                logger.error("Error en consultar_producto: %s", exc)
                return "Error al consultar el catálogo."

        tools_estaticas = [agregar_al_pedido, consultar_producto]

        # Herramientas dinámicas configuradas por el cliente en HerramientaAgente
        tools_dinamicas = []
        if self.agente is not None:
            try:
                from agents_ai.tools_builder import build_tools_de_agente
                tools_dinamicas = build_tools_de_agente(self.agente, conversacion=self.conversacion)
            except Exception as exc:
                logger.warning("Error cargando herramientas dinámicas del agente: %s", exc)

        return tools_estaticas + tools_dinamicas

    def consultar_con_listas(self, pregunta: str, descripcion_agente: str = '') -> ConsultaResultado:
        """Variante de consultar() que habilita tool-calling (function calling).

        El LLM puede invocar herramientas como agregar_al_pedido o consultar_producto
        en un loop acotado a 3 iteraciones. Mantiene fallback al parseo JSON legacy
        para prompts de agentes antiguos que siguen emitiendo JSON en vez de tool calls.
        """
        self._cargar_listas_desde_memoria()
        contexto_previo = self._contexto_previo()

        bienvenida = self._saludo_primer_mensaje(pregunta)
        if bienvenida is not None:
            h = self._chat_history()
            if h:
                h.add_user_message(pregunta)
                h.add_ai_message(bienvenida)
            return ConsultaResultado(respuesta=bienvenida)

        contexto, _sin_datos = self._construir_contexto(pregunta, contexto_previo)
        prompt_final = self._formatear_prompt(pregunta, contexto, descripcion_agente, contexto_previo)

        tools = self._build_tools()
        tool_map = {t.name: t for t in tools}
        try:
            # Tool-calling con temperatura baja: los argumentos de las tools
            # (fechas, cantidades, ids de servicio) necesitan determinismo;
            # con la temperatura de charla el modelo inventa args y fuerza
            # iteraciones extra del loop (= llamadas LLM extra).
            _llm_tools = get_llm_cached(
                self._provider_obj,
                apikey=self.apikey,
                model_name=self.model_name,
                max_output_tokens=self.cfg_max_output_tokens,
                temperature=min(self.cfg_temperature, _TEMPERATURE_TOOLS),
                base_url=self.base_url,
            )
            llm_con_tools = _llm_tools.bind_tools(tools)
        except Exception as exc:
            logger.warning("bind_tools no soportado — fallback a consultar() estándar: %s", exc)
            return self._consultar_con_listas_legacy(pregunta, descripcion_agente)

        mensajes = [HumanMessage(content=prompt_final)]
        t_in_acc = t_out_acc = 0
        ai_message = None
        _MAX_ITER = 3

        for iteracion in range(_MAX_ITER):
            try:
                ai_message = llm_con_tools.invoke(mensajes)
            except Exception as exc:
                logger.error("Error invocando LLM con tools (iter=%d): %s", iteracion, exc)
                raise
            t_in, t_out = self._extraer_tokens(ai_message)
            t_in_acc += t_in
            t_out_acc += t_out
            mensajes.append(ai_message)

            tool_calls = getattr(ai_message, 'tool_calls', None) or []
            if not tool_calls:
                break

            for tc in tool_calls:
                fn = tool_map.get(tc.get('name'))
                if fn is None:
                    resultado_tool = f"Herramienta desconocida: {tc.get('name')}"
                else:
                    try:
                        resultado_tool = fn.invoke(tc.get('args') or {})
                    except Exception as exc:
                        logger.error("Error ejecutando tool %s: %s", tc.get('name'), exc)
                        resultado_tool = f"Error ejecutando la herramienta: {exc}"
                mensajes.append(ToolMessage(
                    content=str(resultado_tool),
                    tool_call_id=tc.get('id', ''),
                ))
        else:
            logger.warning("Loop tool-use alcanzó MAX_ITER=%d sin respuesta final", _MAX_ITER)

        respuesta = self._extraer_texto(ai_message)

        # Fallback backward-compat: si el modelo emitió JSON en vez de llamar tools
        # (p. ej. prompt antiguo con instrucción "emite {accion:...}"), aplicamos la
        # acción equivalente usando las mismas tools.
        if respuesta and respuesta.lstrip().startswith('{'):
            respuesta = self._aplicar_json_legacy(respuesta, tool_map) or respuesta

        fin_detectado = FIN_SIGNAL in respuesta
        if fin_detectado:
            respuesta = respuesta.replace(FIN_SIGNAL, "").strip()

        h = self._chat_history()
        if h:
            h.add_user_message(pregunta)
            h.add_ai_message(respuesta)

        self._incrementar_hits_faqs()
        self._memorizar_interaccion(pregunta, respuesta, _sin_datos)
        t_res_in, t_res_out = self._actualizar_resumen_rodante()

        return ConsultaResultado(
            respuesta=respuesta, fin_detectado=fin_detectado,
            tokens_entrada=t_in_acc + t_res_in, tokens_salida=t_out_acc + t_res_out,
            tokens_total=t_in_acc + t_out_acc + t_res_in + t_res_out,
            sin_datos=_sin_datos,
        )

    def _incrementar_hits_faqs(self) -> None:
        """Suma +1 al contador de uso de las FAQs inyectadas en este turno."""
        ids = getattr(self, '_faq_ids_usadas', None)
        if not ids:
            return
        try:
            from django.db.models import F
            from crm.models import FaqAgente
            FaqAgente.objects.filter(id__in=ids).update(hits=F('hits') + 1)
        except Exception as exc:
            logger.debug("No se pudo incrementar hits de FAQs: %s", exc)
        finally:
            self._faq_ids_usadas = []

    def _aplicar_json_legacy(self, respuesta_json: str, tool_map: dict) -> str:
        """Parseo JSON legacy para prompts antiguos que aún emiten {accion:...}."""
        try:
            data = json.loads(respuesta_json)
        except Exception:
            return ""
        accion = data.get("accion")
        item   = (data.get("item") or "").strip()
        if accion == "agregar_item" and item:
            fn = tool_map.get('agregar_al_pedido')
            if fn:
                return str(fn.invoke({'item': item, 'cantidad': int(data.get('cantidad') or 1)}))
        if accion == "mostrar_lista":
            items = self.listas_memoria.get(data.get("nombre_lista", "pedido"), {}).get("items", [])
            if not items:
                return "📝 Tu pedido está vacío."
            listado = "\n".join(f"{i+1}. {x}" for i, x in enumerate(items))
            return f"📋 Tu pedido:\n{listado}\n\nTotal: {len(items)} ítem(s)"
        return ""

    def _consultar_con_listas_legacy(self, pregunta: str, descripcion_agente: str = '') -> ConsultaResultado:
        """Ruta de fallback cuando bind_tools no está soportado por el proveedor."""
        self._cargar_listas_desde_memoria()
        resultado = self.consultar(pregunta, descripcion_agente)
        tools = self._build_tools()
        tool_map = {t.name: t for t in tools}
        reemplazo = self._aplicar_json_legacy(resultado.respuesta, tool_map)
        if reemplazo:
            h = self._chat_history()
            if h:
                h.update_last_ai_message(reemplazo)
            return ConsultaResultado(
                respuesta=reemplazo, fin_detectado=resultado.fin_detectado,
                tokens_entrada=resultado.tokens_entrada, tokens_salida=resultado.tokens_salida,
                tokens_total=resultado.tokens_total, sin_datos=resultado.sin_datos,
            )
        return resultado
