"""Retrieval — cache de FAISS en memoria, búsqueda híbrida BM25+MMR y recortes de contexto."""
import logging
import os
import re
import threading

from langchain_community.vectorstores import FAISS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FAISS in-memory cache — keyed by path, invalidado cuando index.faiss cambia
# ---------------------------------------------------------------------------
_faiss_cache: dict[str, tuple[float, object]] = {}
_bm25_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _ruta_vectorstore_permitida(path: str) -> bool:
    """FAISS.load_local deserializa pickle (ejecución de código si el índice es
    malicioso). Solo permitimos rutas DENTRO de las carpetas propias de la app
    (MEDIA_ROOT / BASE_DIR) para que no se cargue un índice colocado en otro
    lugar del disco."""
    try:
        from django.conf import settings
        real = os.path.realpath(path)
        permitidas = []
        for attr in ('MEDIA_ROOT', 'BASE_DIR'):
            base = getattr(settings, attr, None)
            if base:
                permitidas.append(os.path.realpath(str(base)))
        return any(real == b or real.startswith(b + os.sep) for b in permitidas)
    except Exception:
        return False


def _get_vectorstore_cached(path: str, embeddings) -> object | None:
    """Carga FAISS desde disco con cache basado en mtime."""
    if not _ruta_vectorstore_permitida(path):
        logger.error("Ruta de vectorstore fuera del área permitida, no se carga: %s", path)
        return None
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
        _bm25_cache.pop(path, None)


# ---------------------------------------------------------------------------
# Búsqueda híbrida
# ---------------------------------------------------------------------------

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


def _build_bm25(vs, k: int = 5):
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
        retriever.k = k
        return retriever
    except Exception as e:
        logger.debug("BM25 no disponible (rank_bm25 no instalado?): %s", e)
        return None


def _get_bm25_cached(path: str, vs, k: int = 5):
    """BM25 cacheado por path+mtime — evita re-tokenizar todo el docstore en cada mensaje.

    Tokenizar el corpus completo es O(N docs) y antes ocurría en cada construcción
    de AgenteConsultor (= cada mensaje entrante). Ahora se construye una vez por
    versión del índice y se invalida junto al cache FAISS.
    """
    if vs is None:
        return None
    if not path:
        return _build_bm25(vs, k)
    index_file = os.path.join(path, 'index.faiss')
    try:
        mtime = os.path.getmtime(index_file)
    except OSError:
        return _build_bm25(vs, k)

    with _cache_lock:
        cached = _bm25_cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    retriever = _build_bm25(vs, k)
    with _cache_lock:
        _bm25_cache[path] = (mtime, retriever)
    return retriever


def _filtrar_por_umbral(vs, query_vector, docs_sem: list, fetch_k: int, umbral_distancia: float) -> list:
    """Descarta chunks semánticos cuya distancia L2² al query supera el umbral.

    FAISS con embeddings normalizados: distancia² = 2·(1 - coseno), o sea
    umbral 1.4 ≈ coseno 0.3. Chunks por encima del umbral son ruido que
    gasta tokens y empuja al modelo a alucinar. Los resultados BM25 no se
    filtran (keyword exacta = señal fuerte por sí sola).
    """
    if not docs_sem or query_vector is None or umbral_distancia is None:
        return docs_sem
    try:
        scored = vs.similarity_search_with_score_by_vector(query_vector, k=fetch_k)
    except Exception as e:
        logger.debug("Score filter error: %s", e)
        return docs_sem
    permitidos = {doc.page_content for doc, score in scored if score <= umbral_distancia}
    filtrados = [d for d in docs_sem if d.page_content in permitidos]
    if len(filtrados) < len(docs_sem):
        logger.debug(
            "Umbral %.2f descartó %d/%d chunks semánticos",
            umbral_distancia, len(docs_sem) - len(filtrados), len(docs_sem),
        )
    return filtrados


def _hybrid_search(vs, bm25, query: str, k: int, lambda_mult: float, query_vector=None,
                   umbral_distancia: float = None) -> list:
    """
    Búsqueda híbrida BM25 + FAISS MMR.
    - BM25 : recupera por keywords exactas (nombres de productos, términos específicos)
    - FAISS: recupera por similitud semántica
    Los resultados BM25 van primero (mayor precisión exacta), luego FAISS.
    Duplicados eliminados por contenido.

    `query_vector`: embedding pre-calculado del query. Cuando se pasa, la
    búsqueda usa *_by_vector y NO re-embebe — permite compartir UNA sola
    llamada de embedding entre documentos, enlaces y memoria.

    `umbral_distancia`: si se pasa junto con `query_vector`, los chunks
    semánticos con distancia mayor al umbral se descartan (ver
    _filtrar_por_umbral). None = sin filtro (comportamiento previo).
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
            if query_vector is not None:
                docs_sem = vs.max_marginal_relevance_search_by_vector(
                    query_vector, k=k, fetch_k=k * 3, lambda_mult=lambda_mult
                )
                docs_sem = _filtrar_por_umbral(vs, query_vector, docs_sem, k * 3, umbral_distancia)
            else:
                docs_sem = vs.max_marginal_relevance_search(
                    query, k=k, fetch_k=k * 3, lambda_mult=lambda_mult
                )
        except Exception as e:
            logger.debug("FAISS MMR search error: %s", e)

    return _dedup_preservando_orden(docs_kw + docs_sem)


def _trim_contexto(docs, max_chars: int = 4_000) -> str:
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
# Extracción de sección relevante (Modo A — contexto estático sin FAISS)
# ---------------------------------------------------------------------------

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
