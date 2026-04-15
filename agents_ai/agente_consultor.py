import logging
import os
import re
import threading
import unicodedata
import json
from dataclasses import dataclass

from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

from whatsapp.models import ConversacionWhatsApp
from .memoria_django import DjangoChatMessageHistory

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
_MAX_STATIC_CHARS  = 2_000  # máx chars del contexto estático en Modo B (suplemento)
_HISTORY_TURNS     = 4      # turnos de historial (4 turnos = 8 mensajes)
_USER_SNIPPET      = 160    # chars por mensaje de usuario en historial
_AI_SNIPPET        = 240    # chars por respuesta IA en historial
_MAX_OUTPUT_TOKENS = 3000   # tokens de salida — suficiente para menús completos con pizzas/precios
_TOPIC_ANCHOR_CHARS = 180   # chars del primer mensaje sustantivo como ancla de tema
# Para consultas amplias en Modo A (sin FAISS) se envía el contexto_estatico completo sin cap

# Palabras que NO se añaden como ancla semántica al query FAISS
_GREETING_WORDS = frozenset({
    'hola', 'hi', 'hello', 'hey', 'buenas', 'buenos', 'saludos',
    'ok', 'okay', 'si', 'sí', 'no', 'gracias', 'thanks',
})

# Mensajes de confirmación breve — se salta FAISS, solo historial
_ACK_RE = re.compile(
    r'^(ok|okay|okey|entendido|perfecto|excelente|bien|claro|ya|dale|listo|genial|'
    r'super|chévere|chevere|gracias|thanks|de acuerdo|muy bien|está bien|👍|'
    r'de acuerdo|eso es todo|nada más|nada mas)[\s!.,]*$',
    re.IGNORECASE | re.UNICODE,
)

# ---------------------------------------------------------------------------
# FAISS in-memory cache — keyed by path, invalidated cuando index.faiss cambia
# ---------------------------------------------------------------------------
_faiss_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _get_vectorstore_cached(path: str, embeddings) -> object | None:
    """Carga FAISS desde disco con cache basado en mtime."""
    index_file = os.path.join(path, 'index.faiss')
    try:
        mtime = os.path.getmtime(index_file)
    except OSError:
        return None

    with _cache_lock:
        cached = _faiss_cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        vs = FAISS.load_local(path, embeddings, allow_dangerous_deserialization=True)
        _faiss_cache[path] = (mtime, vs)
        return vs


def invalidate_vectorstore_cache(path: str) -> None:
    """Llamar después de reconstruir un vectorstore para forzar recarga."""
    with _cache_lock:
        _faiss_cache.pop(path, None)


# ---------------------------------------------------------------------------
# Detección de saludos y acks — sin llamada al LLM
# ---------------------------------------------------------------------------
_GREETING_RE = re.compile(
    r'^(hola+|hi+|hello+|hey+|ey+|buenas?|buenos\s+d[ií]as?|buenas?\s+tardes?'
    r'|buenas?\s+noches?|buen\s+d[ií]a|saludos?|qu[eé]\s+tal|c[oó]mo\s+est[aá]s?'
    r'|good\s+morning|good\s+afternoon|good\s+evening)\W*$',
    re.IGNORECASE | re.UNICODE,
)


def _es_saludo(texto: str) -> bool:
    return bool(_GREETING_RE.match(texto.strip()))


def _es_ack_simple(texto: str) -> bool:
    """True si el mensaje es una confirmación breve que no necesita buscar en FAISS."""
    t = texto.strip()
    return len(t) <= 30 and bool(_ACK_RE.match(t))


_AMPLIA_RE = re.compile(
    r'(men[uú]|carta|qu[eé]\s+tiene[sn]?|qu[eé]\s+ofrecen?|lista\s+de|cat[aá]logo'
    r'|todas?\s+(las?|los?)\s+opciones?|todo\s+lo\s+que|todos?\s+(los?|las?)\s+platos?'
    r'|qu[eé]\s+hay|productos?|servicios?|precios?\s+de\s+todo|todo\s+el\s+men[uú]'
    r'|qu[eé]\s+venden?|qu[eé]\s+sirven?|qu[eé]\s+tienen\s+disponible)',
    re.IGNORECASE | re.UNICODE,
)


def _es_consulta_amplia(texto: str) -> bool:
    """True si el usuario pide información amplia (menú completo, catálogo, lista de productos)."""
    return bool(_AMPLIA_RE.search(texto.strip()))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    texto = re.sub(r'[^a-zA-Z0-9\s]', '', texto)
    return texto.lower()


def _dedup_preservando_orden(docs) -> list:
    """Elimina chunks duplicados respetando el ranking MMR."""
    seen = set()
    result = []
    for d in docs:
        key = d.page_content
        if key not in seen:
            seen.add(key)
            result.append(d)
    return result


_STOP_WORDS_ES = frozenset({
    'dame', 'quiero', 'tienes', 'tiene', 'puedo', 'como', 'para', 'cual',
    'que', 'del', 'los', 'las', 'una', 'uno', 'con', 'sin', 'por', 'pero',
    'hay', 'hay', 'este', 'esta', 'ese', 'esa', 'algo', 'todo',
})


def _extraer_seccion_relevante(texto: str, query: str, max_chars: int) -> str:
    """
    Mode A (sin FAISS): extrae la sección del documento más relevante al query.
    Busca keywords del query en el texto, retrocede al encabezado de sección más
    cercano (===, ---, ###) e incluye prefijo del documento + sección encontrada.
    Si no hay match, devuelve los primeros max_chars.
    """
    palabras = [
        w for w in re.findall(r'\w+', query.lower())
        if len(w) > 3 and w not in _STOP_WORDS_ES
    ]
    if not palabras:
        return texto[:max_chars]

    # Posición del primer keyword encontrado en el documento
    mejor_pos = len(texto)
    for palabra in palabras:
        pos = texto.lower().find(palabra)
        if 0 <= pos < mejor_pos:
            mejor_pos = pos

    if mejor_pos == len(texto):
        return texto[:max_chars]

    # Retroceder al inicio de sección más cercano (=== o ---) antes del match
    _SEPARADORES = re.compile(r'(?m)^(?:===|---|###|\*\*\*)')
    seccion_inicio = 0
    for m in _SEPARADORES.finditer(texto):
        if m.start() <= mejor_pos:
            seccion_inicio = m.start()
        else:
            break

    # Prefijo del documento (primeras líneas con el nombre/encabezado)
    prefijo_fin = min(300, seccion_inicio)
    prefijo = texto[:prefijo_fin].strip()
    presupuesto_seccion = max_chars - len(prefijo) - 10  # margen para "\n...\n"
    seccion = texto[seccion_inicio: seccion_inicio + presupuesto_seccion]

    if prefijo and not seccion.startswith(prefijo):
        return f"{prefijo}\n...\n{seccion}"
    return seccion


def _build_bm25(vs):
    """
    Construye un índice BM25 desde los documentos almacenados en el docstore FAISS.
    BM25 busca por keywords exactas; complementa la búsqueda semántica de FAISS.
    Devuelve None si rank_bm25 no está instalado o el vectorstore está vacío.
    """
    if not vs:
        return None
    try:
        from langchain_community.retrievers import BM25Retriever
        docs = [d for d in vs.docstore._dict.values() if getattr(d, 'page_content', '').strip()]
        if not docs:
            return None
        retriever = BM25Retriever.from_documents(docs)
        retriever.k = _FAISS_K
        return retriever
    except Exception as e:
        logger.debug("BM25 no disponible (rank_bm25 no instalado?): %s", e)
        return None


def _hybrid_search(vs, bm25, query: str, k: int, lambda_mult: float) -> list:
    """
    Búsqueda híbrida BM25 + FAISS MMR.
    - BM25 : recupera por keywords exactas (nombres de productos, términos específicos)
    - FAISS: recupera por similitud semántica
    Los resultados BM25 van primero (mayor precisión exacta), luego FAISS.
    Duplicados eliminados por contenido.
    """
    docs_kw  = []
    docs_sem = []

    if bm25:
        try:
            bm25.k = k
            docs_kw = bm25.get_relevant_documents(query)
        except Exception as e:
            logger.debug("BM25 search error: %s", e)

    if vs:
        try:
            docs_sem = vs.max_marginal_relevance_search(
                query, k=k, fetch_k=k * 3, lambda_mult=lambda_mult
            )
        except Exception as e:
            logger.debug("FAISS MMR search error: %s", e)

    return _dedup_preservando_orden(docs_kw + docs_sem)


def _trim_contexto(docs, max_chars: int = _MAX_CONTEXT_CHARS) -> str:
    """Une los chunks más relevantes hasta el techo de caracteres."""
    partes = []
    total = 0
    for d in docs:
        chunk = d.page_content.strip()
        if not chunk:
            continue
        if total + len(chunk) > max_chars:
            restante = max_chars - total
            if restante > 200:
                partes.append(chunk[:restante])
            break
        partes.append(chunk)
        total += len(chunk)
    return "\n\n".join(partes)


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
    ):
        self.provider = 'gemini' if provider == 2 else 'openai'
        self.apikey = apikey
        self.model_name = model_name or self.default_model()
        self.vectorstore_path = vectorstore_path
        self.vectorstore_enlaces_path = vectorstore_enlaces_path
        self.contexto_estatico: str | None = contexto_estatico or None
        self.detectar_fin = detectar_fin
        self.perfil = perfil  # PerfilNegocioIA — usado por herramientas de tool-calling
        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.vectorstore = self._load_vectorstore()
        self.vectorstore_enlaces = self._load_vectorstore_enlaces()
        self._bm25 = _build_bm25(self.vectorstore)
        self._bm25_enlaces = _build_bm25(self.vectorstore_enlaces)
        self.conversacion: ConversacionWhatsApp = conversacion

        # Historial — acceso directo, sin ConversationBufferMemory (era dead code)
        self._historia: DjangoChatMessageHistory | None = (
            DjangoChatMessageHistory(session_id=str(conversacion.id))
            if conversacion else None
        )

        # Pre-compilar PromptTemplate una sola vez (no en cada llamada)
        _VARS_REQUERIDAS = {'question', 'context', 'descripcion_agente', 'contexto_extra'}
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
        self._cargar_listas_desde_memoria()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def default_model(self) -> str:
        return "gemini-2.5-flash" if self.provider == "gemini" else "gpt-4o-mini"

    def _get_embeddings(self):
        if self.provider == "gemini":
            return GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004", google_api_key=self.apikey
            )
        elif self.provider == "openai":
            return OpenAIEmbeddings(openai_api_key=self.apikey)
        raise ValueError("Proveedor de embedding no soportado")

    def _get_llm(self):
        if self.provider == "gemini":
            return ChatGoogleGenerativeAI(
                model=self.model_name, google_api_key=self.apikey,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                temperature=0.1,  # Baja temperatura → reproduce contexto fielmente, sin inventar
            )
        elif self.provider == "openai":
            from langchain_community.chat_models import ChatOpenAI
            return ChatOpenAI(
                model_name=self.model_name, openai_api_key=self.apikey,
                max_tokens=_MAX_OUTPUT_TOKENS,
                temperature=0.1,
            )
        raise ValueError("Proveedor de LLM no soportado")

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
    # Historial
    # ------------------------------------------------------------------

    def _chat_history(self) -> DjangoChatMessageHistory | None:
        return self._historia

    def _es_primer_mensaje(self) -> bool:
        h = self._historia
        return h is None or h.count() == 0

    def _contexto_previo(self) -> str:
        """
        Devuelve los últimos N turnos como texto compacto.
        Trunca para minimizar tokens: usuario → _USER_SNIPPET chars, IA → _AI_SNIPPET chars.
        """
        h = self._historia
        if not h:
            return ""

        mensajes = h.get_recent(_HISTORY_TURNS * 2)
        if not mensajes:
            return ""

        partes = []
        for msg in mensajes:
            if isinstance(msg, HumanMessage):
                t = msg.content[:_USER_SNIPPET]
                partes.append(f"U: {t}{'…' if len(msg.content) > _USER_SNIPPET else ''}")
            elif isinstance(msg, AIMessage):
                t = msg.content[:_AI_SNIPPET]
                partes.append(f"A: {t}{'…' if len(msg.content) > _AI_SNIPPET else ''}")

        return "Historial reciente:\n" + "\n".join(partes) + "\n\n"

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
                return first[:_TOPIC_ANCHOR_CHARS]
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

    def _construir_contexto(self, pregunta: str, contexto_previo: str) -> tuple[str, bool]:
        """Construye el contexto RAG combinando FAISS + BM25 + contexto_estatico.

        Retorna (contexto, sin_datos). sin_datos=True si no hay vectorstore ni
        contexto_estatico y el agente debe responder 'No tengo esa información.'
        """
        _sin_datos = False
        _es_ack = _es_ack_simple(pregunta) and not self._es_primer_mensaje()
        _presupuesto = _MAX_CONTEXT_CHARS
        _es_amplia = False
        _query_faiss = pregunta

        if _es_ack:
            contexto = ""
            logger.debug("ACK simple — omitiendo FAISS")
        else:
            _query_faiss = self._query_retrieval(pregunta, contexto_previo)
            logger.debug("FAISS query: %r", _query_faiss)

            es_consulta_amplia = _es_consulta_amplia(pregunta)
            _es_amplia = es_consulta_amplia

            if es_consulta_amplia:
                _k = _FAISS_K * 4
                _lambda = 0.0
                _presupuesto = min(_MAX_CONTEXT_CHARS * 2, 8_000)
            else:
                _k = _FAISS_K
                _lambda = 0.65
                _presupuesto = _MAX_CONTEXT_CHARS

            docs = _hybrid_search(self.vectorstore, self._bm25, _query_faiss, _k, _lambda)
            docs_enlaces = _hybrid_search(
                self.vectorstore_enlaces, self._bm25_enlaces, _query_faiss, _k, _lambda
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

        if self.contexto_estatico:
            sin_faiss = not contexto
            if sin_faiss:
                if _es_amplia:
                    contexto = self.contexto_estatico
                else:
                    contexto = _extraer_seccion_relevante(
                        self.contexto_estatico, _query_faiss, _presupuesto
                    )
                logger.debug(
                    "Contexto estático (Modo A): %d chars de %d disponibles (amplia=%s)",
                    len(contexto), len(self.contexto_estatico), _es_amplia,
                )
            else:
                estatico_trim = self.contexto_estatico[:_MAX_STATIC_CHARS]
                faiss_budget  = _presupuesto - len(estatico_trim)
                faiss_trim    = contexto[:max(faiss_budget, 0)]
                faiss_part    = ("\n\n---\n" + faiss_trim) if faiss_trim else ""
                contexto      = estatico_trim + faiss_part
                logger.debug(
                    "Contexto estático (%d chars) + FAISS (%d chars) = %d total (presupuesto=%d)",
                    len(estatico_trim), len(faiss_trim), len(contexto), _presupuesto,
                )

        return contexto, _sin_datos

    def _formatear_prompt(
        self, pregunta: str, contexto: str, descripcion_agente: str, contexto_previo: str
    ) -> str:
        try:
            return self._prompt_tpl.format(
                question=pregunta, context=contexto,
                descripcion_agente=descripcion_agente, contexto_extra=contexto_previo,
            )
        except KeyError as _ke:
            logger.error("Variable faltante en prompt template: %s — usando fallback", _ke)
            from core.constantes import PROMPT_TEMPLATES
            _tpl_fallback = PromptTemplate.from_template(PROMPT_TEMPLATES.get('es', '') + '\n')
            return _tpl_fallback.format(
                question=pregunta, context=contexto,
                descripcion_agente=descripcion_agente, contexto_extra=contexto_previo,
            )

    def _extraer_tokens(self, ai_message) -> tuple[int, int]:
        """(tokens_in, tokens_out) desde un AIMessage — compatible Gemini y OpenAI."""
        t_in = t_out = 0
        usage_std = getattr(ai_message, 'usage_metadata', None) or {}
        if usage_std:
            t_in  = usage_std.get('input_tokens', 0) or 0
            t_out = usage_std.get('output_tokens', 0) or 0
        if not (t_in or t_out):
            meta = getattr(ai_message, 'response_metadata', {}) or {}
            if self.provider == 'gemini':
                usage = meta.get('usage_metadata', {}) or {}
                t_in  = usage.get('prompt_token_count', 0) or 0
                t_out = usage.get('candidates_token_count', 0) or 0
            else:
                usage = meta.get('token_usage', {}) or {}
                t_in  = usage.get('prompt_tokens', 0) or 0
                t_out = usage.get('completion_tokens', 0) or 0
        return t_in, t_out

    def _saludo_primer_mensaje(self, pregunta: str) -> str | None:
        """Si es el primer mensaje y es un saludo, devuelve la bienvenida. Sin LLM."""
        if not (self._es_primer_mensaje() and _es_saludo(pregunta)):
            return None
        return (
            self.conversacion
            and self.conversacion.contacto
            and self.conversacion.contacto.sesion.mensaje_bienvenida
        ) or "Hola 👋, ¿en qué puedo ayudarte?"

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

        contexto, _sin_datos = self._construir_contexto(pregunta, contexto_previo)
        prompt_final = self._formatear_prompt(pregunta, contexto, descripcion_agente, contexto_previo)

        try:
            ai_message = self.llm.invoke(prompt_final)
            respuesta = ai_message.content
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

        return ConsultaResultado(
            respuesta=respuesta, fin_detectado=fin_detectado,
            tokens_entrada=t_in, tokens_salida=t_out, tokens_total=t_in + t_out,
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

        return [agregar_al_pedido, consultar_producto]

    def consultar_con_listas(self, pregunta: str, descripcion_agente: str = '') -> ConsultaResultado:
        """Variante de consultar() que habilita tool-calling (function calling).

        El LLM puede invocar herramientas como agregar_al_pedido o consultar_producto
        en un loop acotado a 3 iteraciones. Mantiene fallback al parseo JSON legacy
        para prompts de agentes antiguos que siguen emitiendo JSON en vez de tool calls.
        """
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
            llm_con_tools = self.llm.bind_tools(tools)
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

        respuesta = (ai_message.content or "").strip() if ai_message else ""

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

        return ConsultaResultado(
            respuesta=respuesta, fin_detectado=fin_detectado,
            tokens_entrada=t_in_acc, tokens_salida=t_out_acc,
            tokens_total=t_in_acc + t_out_acc, sin_datos=_sin_datos,
        )

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
