# agents_ai — motor de IA de FastChat

Todo lo relacionado con IA vive aquí: providers LLM, RAG, memoria, prompts,
consumo y acciones generativas. La configuración (agentes, API keys) vive en
`crm/models.py`; este paquete es el motor.

## Archivos raíz

| Archivo | Para qué es |
|---|---|
| `agente_consultor.py` | La clase `AgenteConsultor` — el bot conversacional: arma contexto (FAISS híbrido + estático + FAQs + APIs + memoria, con umbral de relevancia `cfg_umbral_distancia` en consultas específicas), formatea el prompt con persona/humanización, invoca el LLM (con o sin tool-calling) y memoriza la interacción. En el loop de tool-calling usa temperatura reducida (`_TEMPERATURE_TOOLS = 0.2`, o la del agente si es menor) — los argumentos de tools (fechas, ids, cantidades) necesitan determinismo; la temperatura de charla del agente aplica solo al camino sin tools. Se construye por mensaje pero lo pesado está cacheado entre mensajes: cliente LLM/embeddings (`providers.get_llm_cached`/`get_embeddings_cached`), índice FAISS y BM25 (`consultor/retrieval.py`); las listas de pedido (`listas_memoria`) se cargan lazy solo en el flujo con tools. |
| `agente_resumidor.py` | `AgenteResumidor` — resume conversaciones y analiza sentimiento al cierre. Usa el registry de providers (todos los proveedores). |
| `auditor_agente.py` | Auditor IA de la configuración de un agente: propone mejoras de prompt, contexto estático y FAQs a partir de métricas y conversaciones reales. |
| `humanizacion.py` | División en burbujas, delays de lectura/escritura, detección de ánimo, saludos por franja horaria — hace que el bot escriba como persona. |
| `tools_builder.py` | Convierte `HerramientaAgente` (tools HTTP configuradas por el cliente) en tools LangChain invocables por function-calling. |
| `consumo.py` | Tabla `PRECIO_USD_POR_1K_TOKENS` y `costo_usd()` — calculadora de costo estimado en dinero para el dashboard de consumo. |
| `models.py` | `MessageStore` — tabla del historial de mensajes por conversación (única tabla propia del paquete). |
| `memoria_django.py` | SHIM de compatibilidad → `memoria/historial.py`. No agregar código aquí. |
| `vectorstore_manager.py` | SHIM de compatibilidad → `rag/vectorstore.py`. No agregar código aquí. |
| `sample.py` | Código de ejemplo/legado, sin uso en producción. |

## Subpaquetes

- [`providers/`](providers/README.md) — abstracción de proveedores LLM (Gemini, OpenAI, Claude, Ollama, DeepSeek, Huawei MaaS).
- [`consultor/`](consultor/README.md) — piezas del motor conversacional (clasificación de mensajes, retrieval).
- [`memoria/`](memoria/README.md) — memoria conversacional + memoria RAG por agente.
- [`rag/`](rag/README.md) — ingesta de documentos (Tika/OCR), extracción de texto y vectorstores FAISS.
- [`prompts/`](prompts/README.md) — prompts centralizados del sistema.
- [`ai_actions/`](ai_actions/README.md) — acciones IA one-shot fuera del chat (generar plantillas, campañas, horarios, etc.).

Referencia técnica completa: `.ai/docs/agents_ai_entrenamiento.md`.

## Optimización de tokens y continuidad (2026-07-15, patrones de backmanageria)

Cuatro mejoras aplicadas al `AgenteConsultor` tras estudiar el motor de
`backmanageria` (ver informe en la sesión y `.ai/docs/agents_ai_entrenamiento.md`):

1. **Resumen rodante intra-conversación** — `_actualizar_resumen_rodante()`
   (`agente_consultor.py`): cada `_RESUMEN_CADA_N=6` mensajes, un refresco LLM
   resume los turnos que rotaron fuera de la ventana reciente (≤700 chars,
   incremental sobre el resumen previo). Se guarda como fila `system` interna
   en `message_store` con prefijo `RESUMEN_RODANTE:` (helpers
   `get_resumen_rodante`/`set_resumen_rodante`/`get_range`/`count_conversacion`
   en `memoria/historial.py`) y se reinyecta al inicio de `_contexto_previo()`
   como "Resumen de lo conversado antes: …". Los tokens del refresco se suman
   al `ConsultaResultado` para que el consumo quede facturado. Las filas
   internas (system) ya no consumen lugares de la ventana `get_recent`.
2. **Techo del contexto estático en consultas amplias** — Modo A amplio ya no
   manda el `contexto_estatico` completo: se capa a
   `cfg_max_static_amplia` (default `_MAX_STATIC_AMPLIA=12000` chars,
   overrideable por campo del agente si se agrega).
3. **FAQ directa sin LLM** — `_respuesta_faq_directa()`: si la pregunta
   normalizada coincide casi exacta con una FAQ aprobada
   (`SequenceMatcher ratio ≥ 0.92` o igualdad), responde la FAQ con 0 tokens,
   registra el hit y corta antes del retrieval. Activa en `consultar()` y
   `consultar_con_listas()`.
4. **Desglose del peso del prompt** — `self.desglose_prompt` (chars por bloque:
   docs, estático, FAQ, APIs, memoria, historial, total) se registra en la
   traza `llm_respondio` (`procesar_mensaje.py`, clave `pesos_prompt`) para
   detectar qué sección engorda el prompt por agente.

Pendiente del developer: ninguno (sin migraciones — el resumen usa
`message_store` existente).
