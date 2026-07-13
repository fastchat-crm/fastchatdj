# agents_ai/rag — ingesta de documentos y vectorstores

Convierte los archivos/textos del entrenamiento en conocimiento consultable
(FAISS o contexto estático). Extraer texto NO gasta tokens LLM — el único
costo posterior es el embedding.

| Archivo | Para qué es |
|---|---|
| `tika_client.py` | Cliente HTTP de Apache Tika: `extraer_texto_tika` (PUT /tika con OCR `spa+eng`; reintento OCR automático para PDFs escaneados), `ping_tika` (badge de estado del panel Configuración), `extensiones_soportadas()` (la lista crece si Tika está activo). La URL y el switch viven en `seguridad.Configuracion.tika_url/tika_activo` (cacheados 60 s). |
| `extraccion.py` | Tubería única `extraer_texto_archivo`: txt/md directo → csv/json/xlsx con loader local (conserva estructura) y Tika de respaldo → todo lo demás (pdf, doc, docx, ppt, imágenes...) Tika primero y loader local de respaldo. |
| `vectorstore.py` | `VectorStoreManager`: chunking (`RecursiveCharacterTextSplitter` 2000/200), embeddings del provider (con `base_url` opcional), construir/guardar/cargar FAISS, `add_correction` (feedback humano al índice) y `_extract_raw_text` (delegado a la tubería de extracción). |
| `reproceso.py` | `reprocesar_agente`: pipeline por etapas (extracción → chunking+embeddings → verificación → resumen precomputado del negocio con 1 llamada LLM) con traza de errores por fuente para la UI. Botón "Reprocesar" en la card del agente (acción `reprocesar_rag`). |
| `colecciones.py` | RAG por SESIÓN (fase 1, 2026-07): `indexar_coleccion(crm.RagColeccion)` extrae texto de fuentes enlace/archivo/texto (Tika/OCR vía tubería única), chunkea+embebe con `VectorStoreManager` y guarda FAISS en `media/vectorstores/rag_col_<id>/` (incremental por defecto, `solo_pendientes=False` = rebuild). `consultar_coleccion` = retrieve top-k con umbral relativo — lo consumirá el grafo de consulta (fase 2). UI en `/crm/rag/` (`crm/view_rag.py`); vínculo a sesión vía `SesionWhatsApp.rag_coleccion`. |

Rutas en disco: `media/vectorstores/agente_<id>/` (conocimiento),
`agente_api_<id>/` (fuentes API) y `agente_<id>_memoria/` (memoria RAG).
