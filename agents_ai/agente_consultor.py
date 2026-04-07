import logging
import os
import re
import threading
import unicodedata
import json

from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import HumanMessage, AIMessage
from langchain.memory import ConversationBufferMemory

from whatsapp.models import ConversacionWhatsApp
from .memoria_django import DjangoChatMessageHistory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parámetros de control de tokens
# ---------------------------------------------------------------------------
_FAISS_K = 8                  # chunks a recuperar — 8 × ~1000 chars ≈ 8k chars máx
_FAISS_FETCH_K = 40           # candidatos pre-MMR — pool más grande = mejor recall
_MAX_CONTEXT_CHARS = 4_000    # techo del bloque de contexto enviado al LLM
_HISTORY_TURNS = 4            # turnos de historial a incluir en el prompt
_USER_SNIPPET = 200           # chars del mensaje del usuario en el contexto previo
_AI_SNIPPET   = 600           # chars de la respuesta IA en el contexto previo

# Palabras que NO deben agregarse como ancla semántica al query FAISS
_GREETING_WORDS = frozenset({
    'hola', 'hi', 'hello', 'hey', 'buenas', 'buenos', 'saludos',
    'ok', 'okay', 'si', 'sí', 'no', 'gracias', 'thanks',
})

# ---------------------------------------------------------------------------
# FAISS in-memory cache — keyed by path, invalidated when index.faiss changes
# ---------------------------------------------------------------------------
_faiss_cache: dict[str, tuple[float, object]] = {}  # path → (mtime, vectorstore)
_cache_lock = threading.Lock()


def _get_vectorstore_cached(path: str, embeddings) -> object | None:
    """Carga FAISS desde disco con cache basado en mtime.

    Evita recargar el índice en cada mensaje; recarga automáticamente
    cuando el archivo cambia después de reentrenar.
    """
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
# Greeting detection — sin llamada al LLM
# ---------------------------------------------------------------------------
_GREETING_RE = re.compile(
    r'^(hola+|hi+|hello+|hey+|ey+|buenas?|buenos\s+d[ií]as?|buenas?\s+tardes?'
    r'|buenas?\s+noches?|buen\s+d[ií]a|saludos?|qu[eé]\s+tal|c[oó]mo\s+est[aá]s?'
    r'|good\s+morning|good\s+afternoon|good\s+evening)\W*$',
    re.IGNORECASE | re.UNICODE,
)


def _es_saludo(texto: str) -> bool:
    return bool(_GREETING_RE.match(texto.strip()))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def normalizar_texto(texto: str) -> str:
    """Normaliza para comparaciones textuales — NO usar para queries de FAISS."""
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


def _trim_contexto(docs, max_chars: int = _MAX_CONTEXT_CHARS) -> str:
    """Une los chunks más relevantes hasta el techo de caracteres permitido."""
    partes = []
    total = 0
    for d in docs:
        chunk = d.page_content.strip()
        if not chunk:
            continue
        if total + len(chunk) > max_chars:
            # Incluir recorte del último chunk si cabe algo útil
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
    ):
        self.provider = 'gemini' if provider == 2 else 'openai'
        self.apikey = apikey
        self.model_name = model_name or self.default_model()
        self.vectorstore_path = vectorstore_path
        self.vectorstore_enlaces_path = vectorstore_enlaces_path
        # Texto completo precargado — si está presente, se usa en lugar de FAISS
        self.contexto_estatico: str | None = contexto_estatico or None
        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.vectorstore = self._load_vectorstore()
        self.vectorstore_enlaces = self._load_vectorstore_enlaces()
        self.retriever = (
            self.vectorstore
            and self.vectorstore.as_retriever(
                search_type="mmr",
                search_kwargs={"k": _FAISS_K, "fetch_k": _FAISS_FETCH_K, "lambda_mult": 0.6},
            )
        )
        self.retriever_enlaces = (
            self.vectorstore_enlaces
            and self.vectorstore_enlaces.as_retriever(
                search_type="mmr",
                search_kwargs={"k": _FAISS_K, "fetch_k": _FAISS_FETCH_K, "lambda_mult": 0.6},
            )
        )
        self.conversacion: ConversacionWhatsApp = conversacion
        self.memory = self._get_memory()
        self.prompt_template_text = prompt_template_text
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
                model="models/embedding-001", google_api_key=self.apikey
            )
        elif self.provider == "openai":
            return OpenAIEmbeddings(openai_api_key=self.apikey)
        raise ValueError("Proveedor de embedding no soportado")

    def _get_llm(self):
        if self.provider == "gemini":
            return ChatGoogleGenerativeAI(model=self.model_name, google_api_key=self.apikey)
        elif self.provider == "openai":
            from langchain_community.chat_models import ChatOpenAI
            return ChatOpenAI(model_name=self.model_name, openai_api_key=self.apikey)
        raise ValueError("Proveedor de LLM no soportado")

    def _load_vectorstore(self):
        if not self.vectorstore_path:
            return None
        if not os.path.exists(self.vectorstore_path):
            logger.warning(
                "Vectorstore no encontrado en %s — agente responde sin contexto de documentos.",
                self.vectorstore_path,
            )
            return None
        return _get_vectorstore_cached(self.vectorstore_path, self.embeddings)

    def _load_vectorstore_enlaces(self):
        if not self.vectorstore_enlaces_path:
            return None
        if not os.path.exists(self.vectorstore_enlaces_path):
            logger.warning(
                "Vectorstore de enlaces no encontrado en %s — se omite contexto de APIs.",
                self.vectorstore_enlaces_path,
            )
            return None
        return _get_vectorstore_cached(self.vectorstore_enlaces_path, self.embeddings)

    def _get_memory(self):
        if not self.conversacion:
            return None
        return ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
            chat_memory=DjangoChatMessageHistory(session_id=str(self.conversacion.id)),
        )

    # ------------------------------------------------------------------
    # Historial — eficiente
    # ------------------------------------------------------------------

    def _chat_history(self) -> DjangoChatMessageHistory | None:
        return self.memory.chat_memory if self.memory else None

    def _es_primer_mensaje(self) -> bool:
        """Comprueba si es el primer mensaje con COUNT(*) — sin cargar registros."""
        h = self._chat_history()
        return h is None or h.count() == 0

    def _contexto_previo(self) -> str:
        """
        Devuelve un resumen compacto de los últimos N turnos.

        - Consulta solo `_HISTORY_TURNS * 2` filas con LIMIT en DB.
        - Los mensajes LISTA_GUARDADA ya están filtrados en get_recent().
        - Trunca usuario a _USER_SNIPPET y IA a _AI_SNIPPET chars para no
          consumir tokens innecesarios.
        """
        h = self._chat_history()
        if not h:
            return ""

        mensajes = h.get_recent(_HISTORY_TURNS * 2)
        if not mensajes:
            return ""

        partes = []
        for msg in mensajes:
            if isinstance(msg, HumanMessage):
                texto = msg.content[:_USER_SNIPPET]
                partes.append(f"Usuario: {texto}{'…' if len(msg.content) > _USER_SNIPPET else ''}")
            elif isinstance(msg, AIMessage):
                texto = msg.content[:_AI_SNIPPET]
                partes.append(f"Asistente: {texto}{'…' if len(msg.content) > _AI_SNIPPET else ''}")

        return "Conversación previa:\n" + "\n".join(partes) + "\n\n"

    def _query_retrieval(self, pregunta: str, contexto_previo: str) -> str:
        """
        Enriquece el query FAISS con el último mensaje del usuario para resolver
        preguntas de seguimiento ("¿y el precio?" → sabe el tema anterior).

        Reglas:
        - Solo añade el ancla si tiene al menos 15 chars (evita saludos / "ok" / "sí").
        - No añade si el ancla es puro saludo (_GREETING_WORDS).
        - No añade si la pregunta actual ya contiene el texto del ancla.
        """
        if not contexto_previo:
            return pregunta

        lineas = [l for l in contexto_previo.splitlines() if l.startswith("Usuario:")]
        ultimo_user = lineas[-1].replace("Usuario:", "").strip() if lineas else ""

        # Ignorar anclas triviales
        if not ultimo_user or len(ultimo_user) < 15:
            return pregunta
        if ultimo_user.lower().strip('.,!?') in _GREETING_WORDS:
            return pregunta
        if ultimo_user.lower() in pregunta.lower():
            return pregunta

        return f"{pregunta} {ultimo_user}"

    # ------------------------------------------------------------------
    # Listas en memoria
    # ------------------------------------------------------------------

    def _cargar_listas_desde_memoria(self):
        """
        Carga el estado de listas usando solo los últimos mensajes LISTA_GUARDADA.
        Evita escanear todo el historial.
        """
        h = self._chat_history()
        if not h:
            return
        for mensaje in h.get_recent_lista_guardada(n=10):
            try:
                data = json.loads(mensaje.content.replace("LISTA_GUARDADA:", ""))
                self.listas_memoria.update(data)
            except Exception:
                pass

    def _guardar_listas_en_memoria(self):
        h = self._chat_history()
        if not h or not self.listas_memoria:
            return
        data_json = json.dumps(self.listas_memoria, ensure_ascii=False)
        h.add_ai_message(f"LISTA_GUARDADA:{data_json}")

    # ------------------------------------------------------------------
    # Consulta principal — 1 llamada LLM
    # ------------------------------------------------------------------

    def consultar(self, pregunta: str, descripcion_agente: str = '') -> str:
        # Historial compacto (solo N turnos, LIMIT en DB)
        contexto_previo = self._contexto_previo()

        # Saludo en primer mensaje — sin LLM
        if self._es_primer_mensaje() and _es_saludo(pregunta):
            bienvenida = (
                self.conversacion
                and self.conversacion.contacto
                and self.conversacion.contacto.sesion.mensaje_bienvenida
            ) or "Hola 👋, ¿en qué puedo ayudarte?"
            h = self._chat_history()
            if h:
                h.add_user_message(pregunta)
                h.add_ai_message(bienvenida)
            return bienvenida

        # ------------------------------------------------------------------
        # Contexto: estático (inyección directa) o RAG (FAISS)
        # ------------------------------------------------------------------
        if self.contexto_estatico:
            # Documento pequeño: el texto completo está precargado.
            # Sin llamadas de embedding — contexto completo, respuesta rápida.
            contexto = self.contexto_estatico
            logger.debug("Usando contexto estático (%d chars)", len(contexto))
        else:
            # Documento grande: recuperar chunks relevantes con FAISS.
            query_faiss = self._query_retrieval(pregunta, contexto_previo)
            logger.debug("FAISS query: %r", query_faiss)

            docs = self.retriever.get_relevant_documents(query_faiss) if self.retriever else []
            docs_enlaces = (
                self.retriever_enlaces.get_relevant_documents(query_faiss)
                if self.retriever_enlaces else []
            )
            logger.debug(
                "FAISS recuperó %d chunks (docs=%d, enlaces=%d)",
                len(docs) + len(docs_enlaces), len(docs), len(docs_enlaces),
            )
            todos_docs = _dedup_preservando_orden(docs + docs_enlaces)
            contexto = _trim_contexto(todos_docs, _MAX_CONTEXT_CHARS)
            if not contexto:
                contexto = "(Sin documentos de entrenamiento disponibles)"

        # ------------------------------------------------------------------
        # Construir y enviar prompt
        # ------------------------------------------------------------------
        prompt_template = PromptTemplate.from_template(f'{self.prompt_template_text}\n')
        prompt_final = prompt_template.format(
            question=pregunta,
            context=contexto,
            descripcion_agente=descripcion_agente,
            contexto_extra=contexto_previo,
        )

        try:
            respuesta = self.llm.invoke(prompt_final).content
        except Exception as exc:
            logger.error("Error invocando LLM: %s", exc)
            # Re-raise para que el webhook pueda desactivar la API key y probar la siguiente
            raise

        # Guardar en historial
        h = self._chat_history()
        if h:
            h.add_user_message(pregunta)
            h.add_ai_message(respuesta)

        return respuesta

    # ------------------------------------------------------------------
    # Consulta con listas (modo pedido)
    # ------------------------------------------------------------------

    def consultar_con_listas(self, pregunta: str, descripcion_agente: str = '') -> str:
        consulta = self.consultar(pregunta, descripcion_agente)
        resultado_lista = ''
        try:
            comando_data = json.loads(consulta)
            accion = comando_data.get("accion")
            lista = comando_data.get("nombre_lista", "pedido")
            item = comando_data.get("item", "")

            if accion == "agregar_item":
                if lista not in self.listas_memoria:
                    self.listas_memoria[lista] = {"items": []}
                if item not in self.listas_memoria[lista]["items"]:
                    self.listas_memoria[lista]["items"].append(item)
                    self._guardar_listas_en_memoria()
                    resultado_lista = f"📝 Agregado a tu pedido: {item}"
                else:
                    resultado_lista = f"ℹ️ Ya está en tu pedido: {item}"

            elif accion == "mostrar_lista":
                items = self.listas_memoria.get(lista, {}).get("items", [])
                if not items:
                    resultado_lista = "📝 Tu pedido está vacío."
                else:
                    listado = "\n".join(f"{i+1}. {x}" for i, x in enumerate(items))
                    resultado_lista = f"📋 Tu pedido:\n{listado}\n\nTotal: {len(items)} ítems"

        except Exception:
            pass

        if resultado_lista:
            h = self._chat_history()
            if h:
                h.add_user_message(pregunta)
                h.add_ai_message(resultado_lista)

        return resultado_lista or consulta
