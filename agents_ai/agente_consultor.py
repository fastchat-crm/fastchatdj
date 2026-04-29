import logging
import os
import re
import threading
import unicodedata
import json
from dataclasses import dataclass

from langchain_core.prompts import PromptTemplate
from .providers import get_provider
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
_MAX_STATIC_CHARS  = 1_200  # máx chars del contexto estático en Modo B (suplemento)
_HISTORY_TURNS     = 5      # turnos de historial (5 turnos = 10 mensajes) — suficiente para continuidad típica
_USER_SNIPPET      = 150    # chars por mensaje de usuario en historial
_AI_SNIPPET        = 400    # chars por respuesta IA en historial
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
        agente=None,
    ):
        # Provider: acepta string ('gemini', 'openai') o int (2, 3) — ver providers/__init__.py
        self._provider_obj = get_provider(provider)
        self.provider = self._provider_obj.name  # mantiene API pública previa para compat
        self.apikey = apikey
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
        self._faq_ids_usadas: list = []  # rellenado por _construir_contexto
        self._cargar_listas_desde_memoria()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def default_model(self) -> str:
        return self._provider_obj.default_model()

    def _get_embeddings(self):
        return self._provider_obj.get_embeddings(self.apikey)

    def _get_llm(self):
        # Temperature configurable por agente. Default 0.75 = humano natural.
        # Cada preset puede pisar este valor (ej: formal=0.50, vendedor=0.90).
        return self._provider_obj.get_llm(
            apikey=self.apikey,
            model_name=self.model_name,
            max_output_tokens=self.cfg_max_output_tokens,
            temperature=self.cfg_temperature,
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

        mensajes = h.get_recent(self.cfg_history_turns * 2)
        if not mensajes:
            return ""

        partes = []
        for msg in mensajes:
            if isinstance(msg, HumanMessage):
                t = msg.content[:self.cfg_user_snippet]
                partes.append(f"U: {t}{'…' if len(msg.content) > self.cfg_user_snippet else ''}")
            elif isinstance(msg, AIMessage):
                t = msg.content[:self.cfg_ai_snippet]
                partes.append(f"A: {t}{'…' if len(msg.content) > self.cfg_ai_snippet else ''}")

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
                estatico_trim = self.contexto_estatico[:self.cfg_max_static_chars]
                faiss_budget  = _presupuesto - len(estatico_trim)
                faiss_trim    = contexto[:max(faiss_budget, 0)]
                faiss_part    = ("\n\n---\n" + faiss_trim) if faiss_trim else ""
                contexto      = estatico_trim + faiss_part
                logger.debug(
                    "Contexto estático (%d chars) + FAISS (%d chars) = %d total (presupuesto=%d)",
                    len(estatico_trim), len(faiss_trim), len(contexto), _presupuesto,
                )

        # ── FAQ top-N inyectadas al inicio del contexto ────────────────
        bloque_faq, faq_ids = self._construir_bloque_faq()
        if bloque_faq:
            contexto = f"{bloque_faq}\n\n{contexto}" if contexto else bloque_faq
            # Incrementar hits en background (no bloquear respuesta)
            self._faq_ids_usadas = faq_ids
            if _sin_datos:
                _sin_datos = False  # Tenemos FAQ como respaldo

        # ── APIs externas (fuentes tipo=1 fetch en vivo, sin embeddings) ──
        bloque_apis = self._construir_bloque_apis()
        if bloque_apis:
            contexto = f"{contexto}\n\n{bloque_apis}" if contexto else bloque_apis
            if _sin_datos:
                _sin_datos = False

        return contexto, _sin_datos

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
        1. mensaje_bienvenida configurado a nivel sesión (admin).
        2. Saludo variado por franja horaria + nombre del contacto.
        """
        if not (self._es_primer_mensaje() and _es_saludo(pregunta)):
            return None
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

        return ConsultaResultado(
            respuesta=respuesta, fin_detectado=fin_detectado,
            tokens_entrada=t_in_acc, tokens_salida=t_out_acc,
            tokens_total=t_in_acc + t_out_acc, sin_datos=_sin_datos,
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
