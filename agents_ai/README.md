# agents_ai — motor de IA de FastChat

Todo lo relacionado con IA vive aquí: providers LLM, RAG, memoria, prompts,
consumo y acciones generativas. La configuración (agentes, API keys) vive en
`crm/models.py`; este paquete es el motor.

## Centro de IA — de dónde salen las keys y los parámetros

**No leer `agente.cfg_*` ni filtrar `ApiKeyIA` por `proveedor=2` a mano.** Ambas
cosas se resuelven en `crm/ia_config.py`, que aplica una cascada de tres niveles:

```
agente (valor propio)  →  perfil (ConfiguracionIA)  →  plataforma  →  default de código
```

| Necesitás | Usá |
|---|---|
| El valor real de un parámetro para un agente | `parametros_efectivos(agente)` / `parametro('cfg_faiss_k', agente=…)` |
| Saber si el agente hereda o sobreescribe un campo | `origen_parametros(agente)` |
| La key con la que se vectoriza | `resolver_key_embeddings(perfil_id)` (objeto) o `resolver_key_embeddings_str(perfil_id)` |
| La key por defecto de un proveedor | `resolver_key_default(perfil_id, proveedor)` |

**Los `cfg_*` de `AgentesIA` admiten NULL, y NULL significa "heredar", no "cero".**
Ese es el error fácil de cometer: `getattr(agente, 'memoria_rag_activa', True)`
devuelve `None` para un agente que hereda, y `None` es falsy — apagaría la
memoria RAG sin que nadie lo pidiera. Lo mismo con `int(x or 0)` sobre
`faqs_en_prompt`. Siempre pasar por el resolver.

`resolver_key_embeddings` respeta, en orden: la key marcada `usar_para_embeddings`
en el perfil → la `es_default` de un proveedor con embeddings → cualquier key
activa de un proveedor con embeddings → la key `es_global` de la plataforma.
Antes esto era el mismo bloque copiado en cinco archivos, todos con `proveedor=2`
clavado y `order_by('-id').first()`.

La UI que edita todo esto es **`/crm/centro-ia/`** (`crm/view_centro_ia.py`):
marca qué key vectoriza, edita los parámetros generales del perfil y revectoriza
agentes en lote. `indexador_conocimiento.reindexar_agente(agente, api_key='')`
acepta una key explícita justamente para ese lote; vacío = la que resuelva el
Centro de IA.

## Archivos raíz

| Archivo | Para qué es |
|---|---|
| `agente_consultor.py` | La clase `AgenteConsultor` — el bot conversacional: arma contexto (FAISS híbrido + estático + FAQs + APIs + memoria, con umbral de relevancia `cfg_umbral_distancia` en consultas específicas), formatea el prompt con persona/humanización, invoca el LLM (con o sin tool-calling) y memoriza la interacción. En el loop de tool-calling usa temperatura reducida (`_TEMPERATURE_TOOLS = 0.2`, o la del agente si es menor) — los argumentos de tools (fechas, ids, cantidades) necesitan determinismo; la temperatura de charla del agente aplica solo al camino sin tools. Se construye por mensaje pero lo pesado está cacheado entre mensajes: cliente LLM/embeddings (`providers.get_llm_cached`/`get_embeddings_cached`), índice FAISS y BM25 (`consultor/retrieval.py`); las listas de pedido (`listas_memoria`) se cargan lazy solo en el flujo con tools. |
| `consumo.py` | Tabla `PRECIO_USD_POR_1K_TOKENS` y `costo_usd()` — calculadora de costo estimado en dinero para el dashboard de consumo. |
| `models.py` | `MessageStore` — tabla del historial de mensajes por conversación (única tabla propia del paquete). |
| `memoria_django.py` | SHIM de compatibilidad → `memoria/historial.py`. No agregar código aquí. |
| `vectorstore_manager.py` | SHIM de compatibilidad → `rag/vectorstore.py`. No agregar código aquí. |
| `tools_builder.py` | SHIM de compatibilidad → `herramientas/builder.py`. No agregar código aquí. |
| `weaviate_rag.py` | SHIM de compatibilidad → `rag/weaviate.py`. No agregar código aquí. |
| `indexador_conocimiento.py` | SHIM de compatibilidad → `rag/indexador.py`. No agregar código aquí. |
| `prompts_recomendados.py` | SHIM de compatibilidad → `prompts/recomendados.py`. No agregar código aquí. |
| `agente_resumidor.py` | SHIM de compatibilidad → `agentes/resumidor.py`. No agregar código aquí. |
| `auditor_agente.py` | SHIM de compatibilidad → `agentes/auditor.py`. No agregar código aquí. |
| `humanizacion.py` | SHIM de compatibilidad → `agentes/humanizacion.py`. No agregar código aquí. |
| `sample.py` | Código de ejemplo/legado, sin uso en producción. |

## Subpaquetes

- [`agentes/`](agentes/__init__.py) — bots que hablan con un LLM: `resumidor.py`, `auditor.py`, `humanizacion.py` (y a futuro el consultor como fachada del grafo).
- [`herramientas/`](herramientas/__init__.py) — `builder.py`: tools LangChain dinámicas desde `HerramientaAgente`.
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

## Cap de salida por tipo de consulta (2026-08-02)

`_llm_para_pregunta(pregunta)` (`agente_consultor.py`) elige el techo de tokens
de salida según el tipo de mensaje, usado en la invocación principal de
`consultar()`:

- **Consulta amplia** (menú/catálogo/lista, detectada por `_es_consulta_amplia`)
  → conserva `cfg_max_output_tokens` (`_MAX_OUTPUT_TOKENS=3000`), porque un menú
  completo con precios necesita espacio.
- **Consulta específica** (el caso común) → `cfg_max_output_tokens_corto`
  (`_MAX_OUTPUT_TOKENS_CORTO=1200`), suficiente para una respuesta de WhatsApp y
  evita que el modelo sobre-genere (costo de salida + latencia).

Ambos valores son heredables (cascada agente → Centro de IA → constante).
`get_llm_cached` cachea por config, así que solo se instancian dos clientes por
agente. No toca el tool-loop (`consultar_con_listas` sigue con el techo por
defecto, porque las confirmaciones de pedido ya son cortas). Sin migraciones.

## Próximo lever de tokens (pendiente, requiere revisión del developer)

El mayor ahorro de **input** restante es **prompt caching de proveedor** sobre
los bloques estables (system + `contexto_estatico` + FAQ + perfil), que hoy se
reenvían íntegros como string plano en cada turno (`_formatear_prompt` →
`self.llm.invoke(prompt_final)`). Requiere reestructurar el ensamblado del
prompt en bloques (SystemMessage cacheable + HumanMessage volátil) y marcar
`cache_control` para Claude (los demás proveedores cachean el prefijo estable
automáticamente). Cambia la forma de armar el prompt para todos los proveedores,
por eso se deja para una fase revisada/probada aparte. Instrumento para medir el
antes/después: `desglose_prompt` → traza `llm_respondio.pesos_prompt`.
