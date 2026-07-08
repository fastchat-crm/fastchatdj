# agents_ai/consultor — piezas del motor conversacional

La clase `AgenteConsultor` vive en `agents_ai/agente_consultor.py`; este paquete
contiene sus piezas reutilizables.

| Archivo | Para qué es |
|---|---|
| `clasificacion.py` | Clasificación liviana del mensaje entrante SIN llamar al LLM: ¿es un saludo? (`_es_saludo`), ¿una confirmación breve tipo "ok/gracias"? (`_es_ack_simple` — se salta FAISS), ¿una consulta amplia tipo "el menú completo"? (`_es_consulta_amplia` — amplía el retrieval). También `normalizar_texto` y las listas de palabras (`_GREETING_WORDS`). |
| `retrieval.py` | Todo el retrieval: cache de índices FAISS en RAM por mtime (`_get_vectorstore_cached` / `invalidate_vectorstore_cache`), búsqueda híbrida BM25 + FAISS MMR (`_hybrid_search`, acepta `query_vector` pre-calculado para no re-embeder), índice BM25 (`_build_bm25`) con cache por path+mtime (`_get_bm25_cached` — antes se re-tokenizaba todo el docstore en cada mensaje; se invalida junto al cache FAISS en `invalidate_vectorstore_cache`), recorte de contexto al presupuesto de chars (`_trim_contexto`) y extracción de la sección relevante del contexto estático en Modo A (`_extraer_seccion_relevante`). |

Regla de oro: el query se embebe UNA sola vez por mensaje (en
`AgenteConsultor._construir_contexto`) y el mismo vector se comparte entre
documentos, enlaces y memoria vía `query_vector`.
