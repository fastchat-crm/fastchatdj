"""Memoria RAG por agente — el agente aprende de sus conversaciones.

Cada agente tiene un FAISS de memoria separado del de entrenamiento
({MEDIA_ROOT}/vectorstores/agente_<id>_memoria/). Se alimenta de dos vías:

  1. En vivo: cada par pregunta→respuesta válido se indexa en background
     (guardar_interaccion_async — con debounce en el caller).
  2. Al cierre: el resumen de la conversación terminada se indexa como
     conocimiento consolidado (guardar_conocimiento), reutilizando el resumen
     que el sistema ya genera — cero tokens LLM extra.

Costo por escritura: UNA llamada de embedding (el mismo vector sirve para el
chequeo de duplicados y para indexar). Lectura: si el caller pasa
`query_vector` no se re-embebe nada.
"""
import logging
import os
import threading

from langchain_community.vectorstores import FAISS

logger = logging.getLogger(__name__)

_MAX_PREGUNTA_CHARS = 400
_MAX_RESPUESTA_CHARS = 1200
_MIN_RESPUESTA_CHARS = 20
_MAX_DOCS_MEMORIA = 4000
_UMBRAL_DUPLICADO = 0.05
_UMBRAL_RELEVANCIA = 1.4
_MEMORIA_K = 3
_MAX_CHARS_BLOQUE = 900

_lock = threading.Lock()


def ruta_memoria_agente(agente_id) -> str:
    from django.conf import settings
    return os.path.join(settings.MEDIA_ROOT, 'vectorstores', f'agente_{agente_id}_memoria')


def memoria_existe(agente_id) -> bool:
    return os.path.exists(os.path.join(ruta_memoria_agente(agente_id), 'index.faiss'))


def _indexar_texto(agente_id, embeddings, texto: str, metadata: dict) -> bool:
    """Indexa un texto en la memoria del agente con UNA sola llamada de embedding."""
    if embeddings is None or not (texto or '').strip():
        return False
    try:
        vector = embeddings.embed_documents([texto])[0]
    except Exception as exc:
        logger.warning("Embedding de memoria falló para el agente %s: %s", agente_id, exc)
        return False

    path = ruta_memoria_agente(agente_id)
    index_file = os.path.join(path, 'index.faiss')
    try:
        with _lock:
            if os.path.exists(index_file):
                vs = FAISS.load_local(path, embeddings, allow_dangerous_deserialization=True)
                try:
                    if len(vs.docstore._dict) >= _MAX_DOCS_MEMORIA:
                        logger.debug("Memoria del agente %s llena (%d docs)", agente_id, _MAX_DOCS_MEMORIA)
                        return False
                    similares = vs.similarity_search_with_score_by_vector(vector, k=1)
                    if similares and similares[0][1] <= _UMBRAL_DUPLICADO:
                        return False
                except Exception:
                    pass
                vs.add_embeddings([(texto, vector)], metadatas=[metadata])
            else:
                os.makedirs(path, exist_ok=True)
                vs = FAISS.from_embeddings(
                    text_embeddings=[(texto, vector)],
                    embedding=embeddings,
                    metadatas=[metadata],
                )
            vs.save_local(path)
        from ..consultor.retrieval import invalidate_vectorstore_cache
        invalidate_vectorstore_cache(path)
        return True
    except Exception as exc:
        logger.warning("No se pudo guardar memoria del agente %s: %s", agente_id, exc)
        return False


def guardar_interaccion(agente_id, embeddings, pregunta: str, respuesta: str,
                        conversacion_id: str = None) -> bool:
    """Indexa un par pregunta→respuesta en la memoria del agente."""
    pregunta = (pregunta or '').strip()
    respuesta = (respuesta or '').strip()
    if not pregunta or len(respuesta) < _MIN_RESPUESTA_CHARS:
        return False
    texto = (
        f"Cliente: {pregunta[:_MAX_PREGUNTA_CHARS]}\n"
        f"Asistente: {respuesta[:_MAX_RESPUESTA_CHARS]}"
    )
    return _indexar_texto(
        agente_id, embeddings, texto,
        {'origen': 'memoria_conversacion', 'conversacion_id': conversacion_id or ''},
    )


def guardar_interaccion_async(agente_id, embeddings, pregunta: str, respuesta: str,
                              conversacion_id: str = None) -> None:
    """Versión en background — no agrega latencia a la respuesta del chat."""
    hilo = threading.Thread(
        target=guardar_interaccion,
        args=(agente_id, embeddings, pregunta, respuesta),
        kwargs={'conversacion_id': conversacion_id},
        daemon=True,
    )
    hilo.start()


def guardar_conocimiento(agente_id, embeddings, texto: str, origen: str = 'resumen_conversacion',
                         conversacion_id: str = None) -> bool:
    """Indexa conocimiento consolidado (ej. el resumen de una conversación cerrada)."""
    texto = (texto or '').strip()
    if len(texto) < _MIN_RESPUESTA_CHARS:
        return False
    return _indexar_texto(
        agente_id, embeddings, texto[:2000],
        {'origen': origen, 'conversacion_id': conversacion_id or ''},
    )


def recuperar_memoria(agente_id, embeddings, query: str, k: int = _MEMORIA_K,
                      max_chars: int = _MAX_CHARS_BLOQUE,
                      excluir_conversacion: str = None,
                      query_vector=None,
                      umbral_distancia: float = _UMBRAL_RELEVANCIA) -> str:
    """Recupera los aprendizajes más afines como bloque compacto de contexto.

    Con `query_vector` no se re-embebe el query (el caller ya lo calculó para
    la búsqueda principal). Excluye lo aprendido en la conversación actual y
    corta al presupuesto de chars. Devuelve '' si no hay nada relevante.

    `umbral_distancia`: distancia L2² máxima para considerar un recuerdo
    relevante (embeddings normalizados: 1.4 ≈ coseno 0.3). Recuerdos más
    lejanos se descartan — antes se inyectaba el top-k aunque no tuviera
    relación con la pregunta, gastando tokens. None = sin filtro.
    """
    if embeddings is None or not (query or '').strip():
        return ''
    path = ruta_memoria_agente(agente_id)
    if not os.path.exists(os.path.join(path, 'index.faiss')):
        return ''
    try:
        from ..consultor.retrieval import _get_vectorstore_cached
        vs = _get_vectorstore_cached(path, embeddings)
        if vs is None:
            return ''
        if query_vector is not None:
            docs_scored = vs.similarity_search_with_score_by_vector(query_vector, k=max(k * 2, k))
        else:
            docs_scored = vs.similarity_search_with_score(query, k=max(k * 2, k))
        if umbral_distancia is not None:
            docs = [d for d, score in docs_scored if score <= umbral_distancia]
        else:
            docs = [d for d, _ in docs_scored]
    except Exception as exc:
        logger.debug("Memoria RAG del agente %s no disponible: %s", agente_id, exc)
        return ''

    partes, total, usados = [], 0, 0
    for d in docs:
        if usados >= k:
            break
        if excluir_conversacion and d.metadata.get('conversacion_id') == excluir_conversacion:
            continue
        contenido = (d.page_content or '').strip()
        if not contenido or contenido in partes:
            continue
        if total + len(contenido) > max_chars:
            continue
        partes.append(contenido)
        total += len(contenido)
        usados += 1

    if not partes:
        return ''
    return (
        "## Memoria de conversaciones previas (respuestas que ya diste a otros clientes) ##\n"
        + "\n---\n".join(partes)
        + "\n## fin memoria ##"
    )
