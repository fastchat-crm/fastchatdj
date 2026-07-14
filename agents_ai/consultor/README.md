# agents_ai/consultor — piezas del motor conversacional

La clase `AgenteConsultor` vive en `agents_ai/agente_consultor.py`; este paquete
contiene sus piezas reutilizables.

| Archivo | Para qué es |
|---|---|
| `clasificacion.py` | Clasificación liviana del mensaje entrante SIN llamar al LLM: ¿es un saludo? (`_es_saludo`), ¿una confirmación breve o smalltalk tipo "ok/gracias/hasta luego/jaja"? (`_es_ack_simple` — se salta FAISS y memoria; cubre acks, agradecimientos, despedidas, risas y emojis sueltos), ¿una consulta amplia tipo "el menú completo"? (`_es_consulta_amplia` — amplía el retrieval). También `normalizar_texto` y las listas de palabras (`_GREETING_WORDS`). |
| `retrieval.py` | Todo el retrieval: cache de índices FAISS en RAM por mtime (`_get_vectorstore_cached` / `invalidate_vectorstore_cache`), búsqueda híbrida BM25 + FAISS MMR (`_hybrid_search`, acepta `query_vector` pre-calculado para no re-embeder y `umbral_distancia` para descartar chunks irrelevantes — ver abajo), filtro de relevancia (`_filtrar_por_umbral` — descarta chunks semánticos con distancia L2² > umbral; con embeddings normalizados 1.4 ≈ coseno 0.3; BM25 no se filtra porque keyword exacta es señal fuerte), índice BM25 (`_build_bm25`) con cache por path+mtime (`_get_bm25_cached` — antes se re-tokenizaba todo el docstore en cada mensaje; se invalida junto al cache FAISS en `invalidate_vectorstore_cache`), recorte de contexto al presupuesto de chars (`_trim_contexto`) y extracción de la sección relevante del contexto estático en Modo A (`_extraer_seccion_relevante`). |

Regla de oro: el query se embebe UNA sola vez por mensaje (en
`AgenteConsultor._construir_contexto`) y el mismo vector se comparte entre
documentos, enlaces y memoria vía `query_vector`.

Umbral de relevancia: en consultas específicas los chunks con distancia mayor a
`cfg_umbral_distancia` (default 1.4, constante `_UMBRAL_DISTANCIA` en
`agente_consultor.py`) se descartan en vez de inyectarse al prompt — menos tokens
y menos alucinación. En consultas amplias (menú/catálogo) el umbral se desactiva
porque ahí se quiere todo el corpus.
