# Módulo agents_ai + crm/entrenamiento

Referencia técnica del subsistema de IA: motor RAG (`agents_ai/`), gestor de
entrenamiento (`crm/entrenamiento/`), proveedores LLM, contabilidad de tokens y
todos los call sites externos que disparan inferencia.

> Snapshot generado 2026-05-17. Los `file:line` pueden desplazarse con cambios
> posteriores — usar como mapa, no como ground truth.

---

## 0. Reestructura + mejoras (2026-07-08)

**Nueva estructura de paquetes** (los imports públicos viejos siguen funcionando
vía shims):

```
agents_ai/
├── agente_consultor.py     # clase AgenteConsultor (solo la clase; helpers movidos)
├── agente_resumidor.py     # migrado al provider registry (soporta todos los providers)
├── consultor/              # NUEVO
│   ├── clasificacion.py    # regex saludos/acks/consultas amplias
│   └── retrieval.py        # cache FAISS mtime, BM25, híbrida, trim, sección relevante
├── memoria/                # NUEVO
│   ├── historial.py        # DjangoChatMessageHistory (ex memoria_django.py)
│   └── rag_conversaciones.py  # memoria RAG por agente (aprende de conversaciones)
├── rag/                    # NUEVO
│   ├── tika_client.py      # cliente Apache Tika (extracción + OCR spa+eng)
│   ├── extraccion.py       # tubería única: Tika primero, loaders locales de respaldo
│   └── vectorstore.py      # VectorStoreManager (ex vectorstore_manager.py)
├── providers/              # + openai_compat.py, ollama.py, deepseek.py, huawei.py
├── prompts/                # NUEVO — prompts centralizados
│   ├── plantillas.py       # PROMPT_TEMPLATES (ex core/constantes.py)
│   └── personalidades.py   # PERSONALIDAD_PRESETS + CHOICES + FRASES_RELLENO
├── consumo.py              # NUEVO — PRECIO_USD_POR_1K_TOKENS + costo_usd() (dashboard consumo)
├── memoria_django.py       # SHIM → memoria/historial.py
└── vectorstore_manager.py  # SHIM → rag/vectorstore.py
```

`core/constantes.py` re-exporta los prompts desde `agents_ai.prompts` (compat).
El dashboard de consumo (`consumo_apikey`/`consumo_detalle` en
`crm/view_mientrenamiento.py`) ahora devuelve `costo_usd` + tabla `por_modelo`
usando `agents_ai/consumo.py` — cierra el gap §7.3.

**Providers nuevos**: 5=OLLAMA (local), 6=DEEPSEEK, 7=HUAWEI MAAS — todos
OpenAI-compatibles vía `ChatOpenAI` + `ApiKeyIA.base_url` (campo nuevo).
`get_llm/get_embeddings` ahora aceptan `base_url=None`. Providers sin embeddings
(Claude/DeepSeek/Huawei) ya no rompen `AgenteConsultor.__init__` — el agente
sigue en Modo A (contexto estático + FAQs) sin FAISS.

**Apache Tika**: URL + switch en `seguridad.Configuracion.tika_url/tika_activo`
(panel Configuración, badge de estado con acción AJAX `estado_tika`). Amplía
formatos de entrenamiento (doc/docx/ppt/pptx/odt/rtf/epub/html/imágenes con OCR).
Extraer texto no gasta tokens LLM.

**Memoria RAG por agente**: FAISS en `{MEDIA}/vectorstores/agente_<id>_memoria/`.
Cada Q→A válida se indexa en background (solo embeddings) y se recupera como
bloque compacto (k=3, ≤900 chars) en `_construir_contexto`. Switch por agente:
`AgentesIA.memoria_rag_activa` (default True). Dedupe por score ≤0.05, tope
4000 docs, excluye la conversación actual.

**Suite de evaluación** (2026-07-08): modelos `PreguntaEvaluacionAgente` +
`EvaluacionAgente` (crm/models.py, junto a AuditoriaAgenteIA); motor en
`crm/funciones_evaluacion_agente.py` (`ejecutar_evaluacion`: corre las
preguntas contra el AgenteConsultor real con conversacion=None — no toca
historial ni memoria — y un juez LLM batch califica uso_datos/inventa/
criterio/score 0-10 en UNA llamada force_json). Acciones AJAX:
`eval_datos` (GET), `eval_pregunta_save/delete`, `eval_ejecutar` (POST) en
view_mientrenamiento; botón 🧪 en la card del agente. Consumo registrado
origen='auditor'.

**Reproceso RAG**: `agents_ai/rag/reproceso.py` (`reprocesar_agente`) —
extracción → chunking+embeddings → verificación → resumen precomputado del
negocio en `contexto_estatico` (1 llamada LLM, consumo origen='resumidor').
Acción `reprocesar_rag` + botón 🔄. Errores de entrenamiento visibles vía
cache `entrenamiento_errores_<agente_id>` (helper
`_registrar_error_entrenamiento` en crm/models.py, mostrado en el inspector RAG).

**Monitoreo en vivo**: acción GET `resumen_vivo` en `whatsapp/view_trazas.py`
(por sesión, última hora: eventos, respuestas IA, errores, tokens y costo USD
vía `agents_ai/consumo.py`) + panel con auto-refresh 15s en
`whatsapp/templates/whatsapp/trazas/listado.html`.

**Wizard**: ya era de 3 pasos; ahora al crear redirige directo al **chat de
prueba** (`chat_url`) en vez del editor de 8 tabs.

**Migraciones pendientes** (el developer corre makemigrations/migrate):
`Configuracion.tika_activo/tika_url`, `ApiKeyIA.base_url`,
`AgentesIA.memoria_rag_activa`, `Contacto.opt_out/whatsapp_invalido/...`,
`Campana.limite_diario`, `PreguntaEvaluacionAgente`, `EvaluacionAgente`,
choices de proveedor y validators de archivo.

---

## 1. Overview

**Dos apps, un solo subsistema:**

- `agents_ai/` — motor: providers (Gemini/OpenAI/Claude), FAISS, hybrid search,
  prompt building, tool calling, humanización, memoria conversacional. **Sin
  modelos de configuración propios** — todo se configura desde `crm/`.
- `crm/entrenamiento/` — UI + persistencia: CRUD de `AgentesIA`, `ApiKeyIA`,
  `DetalleAgentesAI`, `FaqAgente`, `HerramientaAgente`. Dispara chunking +
  embedding al guardar.

**Tres apps consumen el motor:**

1. `whatsapp/procesar_mensaje.py` — webhook de mensajes entrantes (producción)
2. `crm/api_ia.py` — endpoint REST público `/api/ia/consultar/` (webservice)
3. `crm/view_chat_agente.py` — chat de prueba en la UI de entrenamiento
4. `voz/consumers.py` — turnos de voz Twilio (transcripción + LLM)
5. `cron_jobs/aprender_conversaciones.py` — resumidor + extractor de FAQs

**Decisión arquitectónica clave:** el motor de flujo tradicional
(`crm/motor_flujo_chatbot.py`) **NO importa `agents_ai/`**. La selección
motor-vs-IA ocurre en `whatsapp/procesar_mensaje.py:442-498` según
`session.modo_bot` ∈ {`tradicional`, `ia`, `hibrido`, `ninguno`}. En `hibrido`,
el motor corre primero; si no matchea, cae a IA.

---

## 2. Modelos

Todos heredan de `core.custom_models.ModeloBase` (soft-delete vía `status`)
salvo `MessageStore`.

### 2.1 `agents_ai/models.py`

**`MessageStore`** (`agents_ai/models.py:4-12`) — única tabla del motor.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | BigAuto PK | — |
| `session_id` | CharField(255, indexed) | = `ConversacionWhatsApp.id` |
| `role` | CharField(20) | `'human'` o `'ai'` |
| `content` | TextField | puede llevar marcadores `LISTA_GUARDADA:...` |
| `created_at` | DateTime(auto_now_add) | — |

Sin soft-delete; se purga por cascade desde `Conversacion`.

### 2.2 `crm/models.py` (tabla de configuración IA)

**`AgentesIA`** (`crm/models.py:179-790`) — agente conversacional.

Campos críticos:
- `perfil` FK → `PerfilNegocioIA` (owner)
- `apikey` M2M → `ApiKeyIA` (lista en orden de intento)
- `prompt_template` TextField (variables: `{question}`, `{context}`,
  `{nombre_bot}`, `{descripcion_agente}`, `{estado_animo}`, `{historial_contacto}`,
  `{contexto_extra}`)
- `contexto_estatico` TextField (modo ≤40k chars, se inyecta directo, **0 embeddings/query**)
- `vectorstore_path` CharField(1000) (modo >40k → FAISS)
- `vectorstore_enlaces_path` CharField(1000) (FAISS separado para fuentes API)
- `vectorstore_enlaces_expira` DateTime (TTL del cache de URLs)
- `faqs_en_prompt` PositiveSmallInt (default 5) — top-N FAQs inyectadas literal
- `anotar_listas` Bool — habilita tool-calling para memoria de pedidos

Tuning de retrieval (todos sobre-escribibles por agente):
- `cfg_faiss_k=5`, `cfg_faiss_fetch_k=20`
- `cfg_max_context_chars=4000`
- `cfg_max_output_tokens=3000`
- `cfg_history_turns=5`
- `cfg_user_snippet=150`, `cfg_ai_snippet=400`
- `cfg_temperature` (override del provider)

Persona: `nombre_bot`, `personalidad`, `tono`, `estilo_escritura`.

Humanización: `humanizar_timing` Bool, `humaniz_chars_burbuja_ideal=180`,
`humaniz_chars_burbuja_max=320`, `humaniz_max_burbujas=4`,
`humaniz_escritura_cps=25`, `humaniz_lectura_cps=70`.

Métodos:
- `requiere_tools()` (`crm/models.py:423-434`) — True si `anotar_listas=True` o
  hay `HerramientaAgente` activa.
- `obtener_detalles_agente()` (`crm/models.py:436-462`) — export JSON de hijos.
- `fetch_contexto_apis()` (`crm/models.py:464-597`) — GET de fuentes tipo=1 con
  cache por `usar_cache` / `tiempo_cache_horas`.
- `build_enlaces_vectorstore()` (`crm/models.py:599-790`) — rebuild FAISS de
  fuentes API; marca `ApiKeyIA.estado=False` si falla embedding.

**`DetalleAgentesAI`** (`crm/models.py:806-920`) — material de entrenamiento.

| Campo | Tipo | Para tipo |
|---|---|---|
| `tipo` | choices: 1=ENLACE, 2=ARCHIVO, 3=TEXTO | — |
| `enlace` | URLField | 1 |
| `tipo_dato_enlace` | choices: 1=TEXT, 2=HTML, 3=JSON, 4=EXCEL, 5=CSV | 1 |
| `requiere_token`, `token_autorizacion` | Bool, CharField(500) | 1 |
| `usar_cache`, `tiempo_cache_horas` | Bool, PositiveInt(default=1) | 1 |
| `archivo` | FileField(upload_to=`detalles_agentes/`) | 2 |
| `descripcion` | TextField | 1 (hint), 3 (texto raw) |

Validators en `archivo`: `FileExtensionValidator(['pdf','csv','json','xlsx'])`
+ `FileMaxSizeInMbValidator(10)` (10 MB max).

`save()` (`crm/models.py:827-920`):
1. Ignora `tipo=1` (URLs no disparan rebuild).
2. Agrega texto de todos los `tipo=2/3 status=True`.
3. Threshold @ `crm/models.py:871`:
   - ≤40k chars → `agente.contexto_estatico = texto`, `vectorstore_path=None`.
   - >40k chars → chunkea + embeb + guarda FAISS en
     `{MEDIA_ROOT}/vectorstores/agente_{id}/`.
4. Si embedding falla → `ApiKeyIA.estado=False`, `msgerror=...`.

**`RagColeccion` + `RagFuente`** (`crm/models.py`, final del archivo — 2026-07-13,
fase 1 del RAG por sesión). Colección de conocimiento independiente del agente:
fuentes enlace/archivo/texto con estado de indexación (`pendiente|indexado|error`),
FAISS propio en `media/vectorstores/rag_col_<id>/`, `apikey` opcional (fallback a
la primera activa del perfil, `apikey_efectiva()`). Se vincula a sesiones vía
`SesionWhatsApp.rag_coleccion` (FK, `related_name='sesiones'`). Motor:
`agents_ai/rag/colecciones.py` (`indexar_coleccion` / `consultar_coleccion`).
UI: `/crm/rag/` (`crm/view_rag.py`, template `templates/crm/rag/listado.html`);
la card de la sesión en `/whatsapp/sesiones/` (`_card.html`) muestra la colección
vinculada con link a `/crm/rag/`.
Migraciones pendientes de correr por el developer. Fase 2 (pendiente): grafo de
consulta router→retrieve→respond con memoria resumida, consumido desde
`AgenteConsultor` cuando la sesión tenga colección.

**`ApiKeyIA`** (`crm/models.py:928-967`) — credencial LLM.

| Campo | Tipo |
|---|---|
| `descripcion` | CharField(255) — **la API key plaintext** |
| `proveedor` | Int choices: 2=GEMINI, 3=OPENAI, 4=CLAUDE |
| `modelo` | CharField (opcional, ver `MODELOS_DISPONIBLES`) |
| `webservice_token` | CharField(64, unique) — Bearer del endpoint REST |
| `estado` | Bool — auto-desactivado en fallo de cuota/auth |
| `msgerror` | TextField — último error del test |
| `alias` | CharField(100) |

Default modelos si no se especifica (`crm/view_mientrenamiento.py:22-26`):
- Gemini: `gemini-2.5-flash`
- OpenAI: `gpt-4o-mini`
- Claude: `claude-haiku-4-5-20251001`

Método: `regenerar_webservice_token()` (`crm/models.py:963-966`) →
`secrets.token_urlsafe(48)`.

**`FaqAgente`** (`crm/models.py:1849-1907`) — pares Q&A curados.

| Campo | Tipo |
|---|---|
| `agente` | FK → AgentesIA |
| `pregunta`, `respuesta` | TextField |
| `origen` | choices: `'manual'`, `'auditor'`, `'conversacion'`, `'feedback'` |
| `estado` | choices: `'pendiente'`, `'aprobada'`, `'desactivada'` |
| `prioridad` | PositiveSmallInt(0-100) — mayor = inyectada antes |
| `hits` | PositiveInt — contador de uso |
| `embebido_en_faiss` | Bool — flag de indexación |
| `conversacion_origen`, `mensaje_origen`, `auditoria_origen` | FK opcionales |
| `fecha_aprobacion`, `usuario_aprobacion` | timestamp + autor |

Top-N por prioridad se inyectan literal pre-FAISS; el resto se embebe al aprobar.

**`HerramientaAgente`** (`crm/models.py:1706-1798`) — tool callable por el LLM.

| Campo | Tipo |
|---|---|
| `agente` | FK |
| `nombre` | SlugField(64) — identificador LLM-facing |
| `nombre_amigable` | CharField(120) |
| `descripcion` | TextField — el LLM lo lee para decidir si invocar |
| `metodo` | choices: `'GET'`, `'POST'` |
| `url` | URLField(500) — admite `{param}` |
| `headers` | JSONField |
| `parametros` | JSONField (lista de `{nombre, tipo, descripcion, requerido, pregunta_sugerida}`) |
| `ubicacion_params` | choices: `'query'`, `'body'`, `'path'` |
| `plantilla_respuesta` | TextField (Jinja2 opcional para formatear respuesta) |
| `timeout` | PositiveInt(default=10, max=30) |
| `funcion_codigo` | CharField(64) — si está, invoca función interna en lugar de HTTP |
| `activo` | Bool |

Constraint: `unique_herramienta_nombre_por_agente`.

**`LogHerramientaAgente`** (`crm/models.py:1800-1831`) — audit de invocación.

Campos: `herramienta`, `conversacion`, `fecha(indexed)`, `request_url`,
`request_params`, `response_status`, `response_body`, `duracion_ms`, `exito`,
`error_mensaje`.

**`ConsumoTokenIA`** (`crm/models.py:969-1018`) — **único registro de tokens**.

| Campo | Tipo |
|---|---|
| `apikey` | FK |
| `agente` | FK nullable (null si llamada externa pura) |
| `conversacion` | FK nullable |
| `fecha` | DateTime(auto_now_add, indexed) |
| `tokens_entrada`, `tokens_salida`, `tokens_total` | Int |
| `modelo` | CharField |
| `origen` | choices: `'whatsapp'`, `'chat_crm'`, `'webservice'`, `'resumidor'`, `'sentimiento'`, `'auditor'`, `'plantilla'`, `'herramienta'`, `'imagen'`, `'otro'` |
| `prompt_preview` | CharField(300) |

Meta: ordering `-fecha`, índice compuesto `(apikey, fecha)`.

**`AlertaConsumoIA`** (`crm/models.py:1020-1048`) — umbral de aviso.

OneToOne con `ApiKeyIA`. `umbral_diario`, `umbral_mensual`, `notificar_a` M2M.
**Es alerta, no enforcement** — la llamada no se bloquea.

**`AuditoriaAgenteIA`** — registro de las auditorías IA-asistidas (revisión de
calidad del agente). Generadas por `agents_ai.ai_actions.auditor_crm.generar()`.

---

## 3. Pipeline end-to-end

### 3.1 Entrenamiento (upload → embeddings)

```
UI: /entrenamiento/?action=procedimiento&id=N
  → tab "Conocimiento" → JSON [{tipo, enlace, archivo, descripcion, ...}]
  → POST action=changeagente + detalles_json
  → entrenamiento_ia_view() [crm/view_mientrenamiento.py:221]
  → guardar_detalles_agente() [crm/view_mientrenamiento.py:104]
      → crea/actualiza DetalleAgentesAI status=True
      → status=False para los no enviados (delete lógico)
  → agente.save()
  → DetalleAgentesAI.save() AUTO [crm/models.py:827]
      → agrega texto de tipo=2 (PyPDFLoader/CSVLoader/JSONLoader/UnstructuredExcel)
        + tipo=3 (raw)
      → THRESHOLD 40k chars [crm/models.py:871]
          ≤40k → agente.contexto_estatico = texto, vectorstore_path=None
          >40k → VectorStoreManager(provider, apikey)
                 → load_and_split(path)  [agents_ai/vectorstore_manager.py:65]
                 → RecursiveCharacterTextSplitter(chunk_size=2000, overlap=200)
                 → build_and_save(docs, f"agente_{id}")  [vectorstore_manager.py:75]
                    → FAISS.from_documents(docs, embeddings)  ← consume tokens NO trackeados
                    → guarda en {MEDIA}/vectorstores/agente_{id}/
                       (index.faiss + index.pkl + docstore.pkl)
                 → agente.vectorstore_path = relpath
      → si embedding falla → apikey.estado=False, msgerror=...
```

**Chunking:** `chunk_size=2000`, `chunk_overlap=200` (hard-coded en
`agents_ai/vectorstore_manager.py:61,72`).

**Embeddings por provider:**
- Gemini: `models/text-embedding-004` (vía `GoogleGenerativeAIEmbeddings`)
- OpenAI: `OpenAIEmbeddings` (default modelo de la lib)
- Claude: **❌ NotImplementedError** (`agents_ai/providers/claude.py:24-28`).
  Agentes con apikey Claude requieren una segunda apikey Gemini/OpenAI para embeddings.

**Re-entrenamiento manual:**
- Acción `procesaragente` (`crm/view_mientrenamiento.py:400-452`) — botón explícito.
- Acción `reconstruir_enlaces` (`crm/view_mientrenamiento.py:1084-1147`) — invalida cache + re-fetch URLs (no rebuilds FAISS).
- Acción `faq_aprender_ahora` (`crm/view_mientrenamiento.py:1149-1159`) — dispara `cron_jobs.aprender_conversaciones.procesar_conversaciones()`.

### 3.2 Inferencia (mensaje → respuesta)

```
WhatsApp webhook recibe mensaje
  → procesar_mensaje.process_incoming_message()
  → switch session.modo_bot [whatsapp/procesar_mensaje.py:442-498]
      'tradicional' → motor_flujo_chatbot only
      'ia'         → directo a AgenteConsultor
      'hibrido'    → motor → si !manejado → AgenteConsultor
      'ninguno'    → solo humanos
  → AgenteConsultor(vectorstore_path, conversacion, agente, ...)
        [whatsapp/procesar_mensaje.py:610-632]
  → agente.requiere_tools() ?
        → .consultar_con_listas(pregunta) [agente_consultor.py:1044]
        : .consultar(pregunta)            [agente_consultor.py:925]
  → _construir_contexto(pregunta) [agente_consultor.py:703-793]
      → clasifica (ack? saludo? consulta amplia?)
      → _query_retrieval — enriquece query con ancla de tópico + último AI snippet
      → HYBRID SEARCH:
          BM25Retriever (keyword)  [agente_consultor.py:209-227]
          FAISS MMR (semántico)   [agente_consultor.py:230-256]
              k=cfg_faiss_k, fetch_k=cfg_faiss_fetch_k, lambda_mult=0.5
              amplia → 4×k, λ=0.0, 8k chars
              específica → k, λ=0.65, 4k chars
      → dedupe + _trim_contexto(max_chars=cfg_max_context_chars)
      → prepend top-N FAQs (estado='aprobada' por prioridad)
      → append datos live de fuentes API (tipo=1)
      → si sin contexto + sin estático → sin_datos=True
  → prompt.format(question, context, persona vars, contexto_extra=history)
  → llm.invoke(prompt)
      o llm.bind_tools(tools).invoke(prompt) — loop max 3 iter
  → _extraer_tokens() del response_metadata
  → ConsultaResultado(respuesta, tokens_entrada/salida/total, fin_detectado)
  → ConsumoTokenIA.objects.create(origen='whatsapp', ...) [whatsapp/procesar_mensaje.py:712-727]
  → dividir_en_burbujas() [agents_ai/humanizacion.py]
  → por cada burbuja: delay(lectura/escritura) + whatsapp_service.send_text_message()
  → persiste MensajeWhatsApp(ia_generado=True)
```

**Memoria conversacional:** `DjangoChatMessageHistory`
(`agents_ai/memoria_django.py:6-106`) envuelve `MessageStore` como
`BaseChatMessageHistory` de LangChain. Inyección como `{contexto_extra}` en el
prompt vía `_contexto_previo()` (`agente_consultor.py:551-597`).

**Streaming:** **No implementado**. `llm.invoke()` bloquea hasta respuesta
completa; humanización corre después (delays artificiales simulan typing).

---

## 4. URLs

### 4.1 Definidas en el proyecto

| URL | Handler | Método |
|---|---|---|
| `/crm/entrenamiento/` | `entrenamiento_ia_view` (`crm/view_mientrenamiento.py:174`) | GET, POST |
| `/crm/entrenamiento/wizard/` | `agente_wizard_view` (`crm/view_agente_wizard.py`) | GET, POST |
| `/crm/entrenamiento/chat/<str:agente_enc_id>/` | `chat_agente_view` (`crm/view_chat_agente.py`) | GET, POST |
| `/api/ia/consultar/` | `consultar_ia_view` (`crm/api_ia.py:55`) | POST (Bearer auth) |
| `/crm/api/captura_local/` | `captura_local` (`crm/api_captura_local.py`) | POST |
| `/ajaxrequest/<accion>` | `core.ajax.ConsultasAjax` | POST (CRUD genérico) |

### 4.2 Webhooks que terminan en IA (no son URLs de browser)

- `whatsapp/meta_webhook/` → `whatsapp.procesar_mensaje.process_incoming_message`
- `whatsapp/webhook_handler/` → idem (Baileys)

### 4.3 Modos del agente en `/entrenamiento/?action=procedimiento&id=N`

8 tabs en `crm/templates/crm/entrenamiento/agente/form_pagina.html`:
Persona, Conocimiento, FAQs, Herramientas, Cierre, Auditor, Prompt, Avanzado.

---

## 5. AJAX actions catalog

Todas las acciones POSTean a `/crm/entrenamiento/` con `action=<key>` y
retornan `JsonResponse({error, ...})`. Origen: `crm/view_mientrenamiento.py`.

### 5.1 CRUD agentes / apikeys

| action | línea | Hace |
|---|---|---|
| `addagente` | :190 | Crea `AgentesIA` + hijos `DetalleAgentesAI` |
| `changeagente` | :221 | Update + upsert detalles |
| `deleteagente` | :251 | Soft-delete (status=False) |
| `addapikey` | :258 | Crea `ApiKeyIA` |
| `changeapikey` | :278 | Update |
| `deleteapikey` | :287 | Soft-delete |
| `reactivarapikey` | :499 | `estado=True` |
| `limpiar_error_apikey` | :506 | Clear `msgerror` |
| `regenerar_ws_token` | :567 | Nuevo `webservice_token` |

### 5.2 Testing / preview

| action | línea | Hace |
|---|---|---|
| `preview_procesamiento` | :294 | Inventario sin ejecutar (archivos, textos, bytes, ¿FAISS?) |
| `preview_prompt` | :343 | Renderiza prompt con demo vars; lista vars faltantes |
| `procesaragente` | :400 | Dispara chunking + embedding |
| `testapikey` | :612 | Llama "Responde solo: ok" → reporta latencia, tokens, billing, errores tipificados (quota, auth, modelo) |
| `testapikey_masivo` | :751 | Batch test todas las apikeys del perfil |
| `ejecutar_prompt_agente` | :853 | Invoca LLM con pregunta real + FAISS real (incluye traza completa) |
| `herramienta_simular` | :941 | Simula al agente invocando tools (con `traza[]`) |
| `herramienta_simular_reset` | :1012 | Limpia sesión de simulación |

### 5.3 Auditor IA (revisión automática)

| action | línea | Hace |
|---|---|---|
| `auditoria_generar` | :512 | Llama `ai_actions.auditor_crm.generar(agente, usuario, dias=30)` |
| `auditoria_aplicar` | :529 | Aplica sugerencia a `prompt_template` o `contexto_estatico` |
| `auditoria_revertir` | :545 | Revierte cambios del auditor |
| `auditoria_aplicar_faq` | :558 | Importa FAQs pendientes propuestas por auditor |

### 5.4 FAQs

| action | línea | Hace |
|---|---|---|
| `faq_save` | :1021 | Create/update FAQ |
| `faq_delete` | :1044 | Soft-delete |
| `faq_aprobar` | :1051 | `estado='aprobada'` + timestamp + autor |
| `faq_desactivar` | :1061 | `estado='desactivada'` |
| `faq_bulk_aprobar` | :1068 | Bulk |
| `faq_prioridad` | :1161 | Update 0-100 |
| `faq_aprender_ahora` | :1149 | Dispara cron `aprender_conversaciones` |

### 5.5 Herramientas (tool-calling)

| action | línea | Hace |
|---|---|---|
| `herramienta_save` | :772 | Create/update + parse `parametros_json` / `headers_json` |
| `herramienta_delete` | :803 | Soft-delete |
| `herramienta_toggle_activo` | :811 | Toggle |
| `herramienta_ia_asistida` | :1168 | `ai_actions.herramientas_crm.generar(frase)` → config JSON |

### 5.6 Fuentes API (tipo=1)

| action | línea | Hace |
|---|---|---|
| `reconstruir_enlaces` | :1084 | Invalida cache + re-fetch + diagnóstico HTTP por URL |

### 5.7 Generación asistida

| action | línea | Hace |
|---|---|---|
| `generar_agente_ia` | :573 | `ai_actions.agentes_crm.generar(descripcion, tono, idioma)` |

### 5.8 Cierre de conversación + alertas

| action | línea | Hace |
|---|---|---|
| `agente_regla_fin_guardar` | :453 | `activo`, `usar_senal_llm`, `frases_cierre` |
| `agente_regla_fin_accion_add` | :462 | Acción al cerrar (tipo, destino, plantilla_mensaje) |
| `agente_regla_fin_accion_delete` | :481 | — |
| `alerta_consumo_save` | :486 | `AlertaConsumoIA` (umbral diario/mensual + recipients) |

### 5.9 Mantenimiento

| action | línea | Hace |
|---|---|---|
| `optimizar_defaults_agentes` | :818 | Downgrade params en agentes no toqueteados a mano |
| `vercontexto` (GET) | — | Preview de contexto + FAQs + tools |
| `auditoria_historial` / `auditoria_detalle` (GET) | — | Histórico de auditorías |
| `preview_optimizar_agentes` (GET) | — | Dry-run de la optimización |

---

## 6. Templates + CSS + JS

### 6.1 Templates (`crm/templates/crm/entrenamiento/`)

| Template | Renderizado por | Propósito |
|---|---|---|
| `form.html` | GET `/` | Dashboard: cards de agentes + apikeys |
| `agente/form_pagina.html` | GET `?action=procedimiento` | Editor 8-tabs full-page |
| `agente/wizard.html` | `agente_wizard_view` | Wizard rápido |
| `agente/form.html` | embedded | Form base |
| `chat.html` | `chat_agente_view` | Chat de prueba |
| `faq/lista.html` | tab FAQs | Lista + aprobar |
| `faq/form.html` | embedded en lista | Add/edit |
| `herramienta/lista.html` | tab Herramientas | Lista + toggle |
| `herramienta/form.html` | embedded | Add/edit |
| `herramienta/logs.html` | embedded | Audit log |
| `apikey/form.html` | modal | Add/edit apikey |

### 6.2 CSS

- `static/stylenew/entrenamiento.css` — cards de agentes, badges, chips
- `static/stylenew/agentesia_form.css` — form

### 6.3 JS

**No hay JS dedicado bajo `static/js/crm/entrenamiento/`** — interacciones
inline en los templates (fetch + Bootstrap tabs).

---

## 7. Token accounting end-to-end

### 7.1 Extracción

`crm/api_ia.py:326-336` — `_extraer_tokens(response)`:
- Lee `response_metadata` o `usage_metadata`:
  - `input_tokens` | `prompt_token_count` | `prompt_tokens` → entrada
  - `output_tokens` | `candidates_token_count` | `completion_tokens` → salida
- Provider-agnóstico (Gemini/OpenAI/Claude).

Cada provider expone `extract_tokens(ai_message)` en su módulo
(`agents_ai/providers/{gemini,openai,claude}.py`) y `AgenteConsultor` los acumula
en loops de tool-calling (`agente_consultor.py:1083-1086`).

### 7.2 Persistencia

`ConsumoTokenIA.objects.create(...)` con `origen` etiquetando el caller:

| Origen | Caller | File:line |
|---|---|---|
| `whatsapp` | webhook entrante | `whatsapp/procesar_mensaje.py:712-727` |
| `webservice` | REST `/api/ia/consultar/` | `crm/api_ia.py:345-352` |
| `chat_crm` | chat de prueba en entrenamiento | `crm/view_mientrenamiento.py:853+` |
| `imagen` / `audio` | endpoints multimodales | `crm/api_ia.py:271-320` |
| `resumidor` / `sentimiento` | `agents_ai.agente_resumidor` | cron `aprender_conversaciones.py` |
| `auditor` | `ai_actions.auditor_crm.generar()` | acción `auditoria_generar` |
| `plantilla` / `herramienta` | otros ai_actions | — |

### 7.3 Cost calculation

**❌ No existe** tabla de price-per-1k-tokens. Solo se cuentan tokens crudos.
Hueco para reingeniería: agregar `ModeloPrecioIA(proveedor, modelo, precio_in, precio_out)`.

### 7.4 Quota / throttling

**Pre-call:**
- `whatsapp/procesar_mensaje.py:582` — chequea que exista al menos una
  `ApiKeyIA(estado=True)` antes de invocar.
- `crm/api_ia.py:54` — rate limit del webservice: 60 req / 60 s.
- **No hay quota per-user/per-org pre-call.**

**Post-call:**
- `crm/alertas_consumo.py:8-20` — `verificar_alerta_consumo(apikey)` chequea
  thresholds en `AlertaConsumoIA`. Si excede → **notifica pero no bloquea**.
- `crm/alertas_consumo.py:22-106` — agregaciones por API key (diaria/mensual)
  vía Django ORM `Sum('tokens_total')`.

**Auto-disable:**
- Si `_extraer_tokens` retorna error de auth/quota → `apikey.estado=False`,
  `msgerror=...` (`whatsapp/procesar_mensaje.py:758-760`).

### 7.5 Embedding tokens

**❌ No se trackean.** El embedding consume tokens del provider pero `FAISS.from_documents()` (`agents_ai/vectorstore_manager.py:75-79`) no emite registro a `ConsumoTokenIA`. **Hueco crítico** — el costo de re-entrenar agentes es invisible en la UI.

### 7.6 Display

- `entrenamiento_ia_view` (GET sin action) — dashboard con cards muestran
  consumo por apikey.
- Acciones `auditoria_*` exponen tokens de la auditoría.

---

## 8. Call sites externos a `agents_ai/`

Agrupados por app caller.

### 8.1 whatsapp/

| File:line | Función | Llama a |
|---|---|---|
| `whatsapp/procesar_mensaje.py:610-632` | `process_incoming_message` | `AgenteConsultor()` + `.consultar()` / `.consultar_con_listas()` |
| `whatsapp/procesar_mensaje.py:712-727` | idem | Persiste `ConsumoTokenIA(origen='whatsapp')` |

### 8.2 crm/

| File:line | Función | Llama a |
|---|---|---|
| `crm/api_ia.py:231-268` | `_procesar_texto` (en `consultar_ia_view`) | `AgenteConsultor()` |
| `crm/api_ia.py:271-295` | `_procesar_imagen` | LLM con visión (provider directo) |
| `crm/api_ia.py:297-320` | `_procesar_audio` | Transcripción + `_procesar_texto` |
| `crm/view_chat_agente.py` | `chat_agente_view` | `AgenteConsultor` (vía AJAX) |
| `crm/view_mientrenamiento.py:404,438,441,443` | `procesaragente` | `VectorStoreManager` (chunk + embed) |
| `crm/view_mientrenamiento.py:513,537` | `auditoria_*` | `ai_actions.auditor_crm.generar/aplicar` |
| `crm/view_mientrenamiento.py:583` | `generar_agente_ia` | `ai_actions.agentes_crm.generar` |
| `crm/view_mientrenamiento.py:859-902` | `ejecutar_prompt_agente` | `AgenteConsultor` |
| `crm/view_mientrenamiento.py:1168` | `herramienta_ia_asistida` | `ai_actions.herramientas_crm.generar` |
| `crm/models.py:652,690,758` | `AgentesIA.build_enlaces_vectorstore` | `VectorStoreManager` |
| `crm/models.py:806-920` | `DetalleAgentesAI.save` | `VectorStoreManager` |

### 8.3 cron_jobs/

| File:line | Función | Llama a |
|---|---|---|
| `cron_jobs/aprender_conversaciones.py:105-113` | `_actualizar_perfil_contacto` | `AgenteResumidor.resumir()` |

### 8.4 voz/

| File:line | Función | Llama a |
|---|---|---|
| `voz/consumers.py:97-100` | `VozTwilioConsumer._procesar_turno` | Transcripción + LLM (vía services.py) |

### 8.5 scripts/

Ninguno directo. Los seeders no invocan inferencia.

---

## 9. Providers + configuración

### 9.1 Estructura

`agents_ai/providers/__init__.py:59-75` — `get_provider(id_or_name)` retorna
singletons mapeados:

| ID | Nombre | Clase | LLM | Embeddings |
|---|---|---|---|---|
| 2 | `gemini` | `GeminiProvider` | `ChatGoogleGenerativeAI` | `GoogleGenerativeAIEmbeddings` (`text-embedding-004`) |
| 3 | `openai` | `OpenAIProvider` | `ChatOpenAI` | `OpenAIEmbeddings` |
| 4 | `claude` | `ClaudeProvider` | `ChatAnthropic` | **❌ NotImplementedError** |

`MODELOS_DISPONIBLES` (`agents_ai/providers/__init__.py`) — lista todos los modelos por provider para el dropdown del form.

### 9.2 Interfaz común

`agents_ai/providers/base.py:1-40` — `BaseProvider`:
- `default_model()`
- `get_llm(apikey, model_name, **kwargs)`
- `get_embeddings(apikey)`
- `extract_tokens(ai_message)` → `(input_tokens, output_tokens)`

### 9.3 Config surface

**API keys:** NO desde env vars / `credenciales.json`. Vienen de
`ApiKeyIA.descripcion` (DB). El test inicial las valida y desactiva las
inválidas.

**Settings que sí lee:** `fastchatdj/settings.py:30-69` solo carga DB +
`SECRET_KEY` + `BASE_URL_PRODUCCION` desde `credenciales.json`. Nada de IA.

**Paths:**
- FAISS por agente: `{MEDIA_ROOT}/vectorstores/agente_{id}/`
- FAISS de fuentes API: `{MEDIA_ROOT}/vectorstores/agente_api_{id}/`

---

## 10. Constantes clave

`agents_ai/agente_consultor.py:44-70`:

| Constante | Default | Override |
|---|---|---|
| `_FAISS_K` | 5 | `agente.cfg_faiss_k` |
| `_FAISS_FETCH_K` | 20 | `agente.cfg_faiss_fetch_k` |
| `_MAX_CONTEXT_CHARS` | 4000 | `cfg_max_context_chars` |
| `_MAX_STATIC_CHARS` | 1200 | — |
| `_HISTORY_TURNS` | 5 | `cfg_history_turns` |
| `_USER_SNIPPET` | 150 | `cfg_user_snippet` |
| `_AI_SNIPPET` | 400 | `cfg_ai_snippet` |
| `_MAX_OUTPUT_TOKENS` | 3000 | `cfg_max_output_tokens` |
| `_TOPIC_ANCHOR_CHARS` | 180 | — |
| `_GREETING_WORDS` | frozenset | — |
| `_ACK_RE` / `_AMPLIA_RE` | regex | — |

`agents_ai/humanizacion.py:35-43`:

| Constante | Default |
|---|---|
| `DEFAULT_CHARS_BURBUJA_IDEAL` | 180 |
| `DEFAULT_CHARS_BURBUJA_MAX` | 320 |
| `DEFAULT_MAX_BURBUJAS` | 4 |
| `DEFAULT_LECTURA_CPS` | 70 |
| `DEFAULT_ESCRITURA_CPS` | 25 |

`agents_ai/vectorstore_manager.py:61,72`:

| Constante | Default |
|---|---|
| `chunk_size` | 2000 |
| `chunk_overlap` | 200 |

`crm/models.py:871`:

| Threshold | Default |
|---|---|
| Estático vs FAISS | 40000 chars |

---

## 11. Integraciones externas

| Servicio | SDK | Uso |
|---|---|---|
| Gemini API | `langchain_google_genai` | LLM + embeddings |
| OpenAI API | `langchain_community.chat_models.ChatOpenAI` | LLM + embeddings |
| Anthropic | `langchain_anthropic.ChatAnthropic` | LLM (sin embeddings) |
| FAISS local | `langchain_community.vectorstores.FAISS` | Vector store |
| PyPDF | `langchain_community.document_loaders.PyPDFLoader` | PDF |
| CSV/JSON/Excel | `CSVLoader`, `JSONLoader`, `UnstructuredExcelLoader` | Loaders |
| Webhooks HerramientaAgente | `requests` directo en `tools_builder.ejecutar_herramienta` | HTTP tools |

---

## 12. ai_actions/ (acciones IA fuera del chat loop)

`agents_ai/ai_actions/` — módulos que invocan LLM para tareas generativas one-shot.

| Módulo | Propósito | Acción AJAX |
|---|---|---|
| `base.py` | `validar_apikey()`, `build_llm(force_json=True)`, `parse_json_response()` con 4-stage fallback (parse → fence → balance → repair), `log_consumo()`, `invocar_json()` | — |
| `prompts.py` | Registry central de prompts (`pipeline_wa`, `campanas_wa`, `horarios_wa.*`) | — |
| `agentes_crm.py` | Genera `AgentesIA` desde free-form | `generar_agente_ia` |
| `auditor_crm.py` | Auditor de calidad del agente | `auditoria_*` |
| `herramientas_crm.py` | Genera `HerramientaAgente` desde frase | `herramienta_ia_asistida` |
| `plantillas_wa.py` | Genera plantillas WhatsApp | — |
| `horarios_wa.py` | Parse de horarios desde lenguaje natural | — |
| `campanas_wa.py` | Genera campañas multi-canal | — |
| `pipeline_wa.py` | Genera Kanban de ventas | — |
| `dpchatbots_crm.py` | Generación para flujos chatbot tradicionales | — |

Exception común: `IAActionError` (`base.py:25`) — safe to display.

---

## 13. Gaps conocidos / candidatos a reingeniería

> Resueltos 2026-07: (a) todos los providers ahora pasan timeout + max_retries
> al cliente LangChain (`providers/base.py`: 60s cloud / 120s Ollama-compat /
> 30s embeddings, 1 retry) — antes Gemini reintentaba 6 veces con backoff y un
> provider caído colgaba el webhook minutos por cada API Key del agente;
> (b) BM25 cacheado por path+mtime (`consultor/retrieval.py:_get_bm25_cached`)
> — antes se re-tokenizaba todo el docstore en cada mensaje; (c) clientes
> LLM/embeddings cacheados por config (`providers.get_llm_cached` /
> `get_embeddings_cached`) — reuso de pool de conexiones entre mensajes;
> (d) `listas_memoria` se carga lazy solo en `consultar_con_listas`;
> (e) multicanal (2026-07): el pipeline IA es agnóstico al canal (IG/TikTok entran por el
> mismo `process_incoming_message` → `AgenteConsultor`); nueva variable opcional de
> template `{canal}` → 'whatsapp'/'instagram'/'tiktok'/'messenger'
> (`AgenteConsultor._canal_conversacion`), y los senders IG/TikTok parten respuestas
> > 1000 chars (`whatsapp/servicio_canal_base.py::partir_texto_por_limite`) porque la
> Graph API rechaza mensajes largos.

1. **Embedding tokens NO trackeados** — costo invisible. Sugerencia: agregar
   `origen='embedding'` a `ConsumoTokenIA` y llamar desde `build_and_save()`.
2. **No hay cost calculation** — solo conteo crudo. Agregar tabla de precios
   por modelo.
3. **Quota es post-hoc** — solo alertas. Para enforcement real, chequear
   `AlertaConsumoIA` antes de `llm.invoke()`.
4. **No streaming** — todo bloqueante. La humanización compensa pero deja
   latencia visible en respuestas largas.
5. **FAISS cache invalidation manual** — `invalidate_vectorstore_cache(path)`
   debe llamarse explícito tras rebuild. Riesgo: respuestas con índice viejo.
6. **Sin async/Celery** — chunking + embedding bloquean el request HTTP. Para
   docs grandes la UI cuelga.
7. **No versionado de índices** — rebuild es destructivo, sin rollback.
8. **Multi-provider embedding fallback** — si la primera apikey falla durante
   embedding, itera al siguiente pero falla en silencio al final
   (`crm/models.py:648-773`).
9. **`FaqAgente.embebido_en_faiss`** — flag declarado pero no se ve código que
   lo actualice post-embedding (`crm/models.py:1885-1888`).
10. **`AgentesIA.descripcion` deprecated** — auto-fill desde `nombre`. Migrar
    plenamente a `nombre_bot` + persona fields.
11. **API keys en plaintext** (`ApiKeyIA.descripcion`) — candidato a cifrado.
12. **`guardar_detalles_agente()` duplicado** — lógica solapada con
    `DetalleAgentesAI.save()`.
13. **`VectorStoreManager` acoplado a LangChain** — loaders y splitter
    hard-coded. Para soportar más formatos (DOCX, MD) requiere editar la clase.
14. **`except: pass` extendido** — varios silenciamientos sin logging.

---

## 14. Cheat sheet de reingeniería

**Agregar nuevo provider LLM:**
1. Nueva clase en `agents_ai/providers/<nombre>.py` heredando `BaseProvider`.
2. Registrar en `agents_ai/providers/__init__.py` (mapping int + name).
3. Agregar choice en `ApiKeyIA.proveedor` (`crm/models.py:928`).
4. Agregar modelos en `MODELOS_DISPONIBLES`.
5. Defaults en `crm/view_mientrenamiento.py:22-26`.

**Agregar nuevo tipo de fuente de entrenamiento:**
1. Choice en `DetalleAgentesAI.tipo` (`crm/models.py:806`).
2. Branch en `DetalleAgentesAI.save()` (`crm/models.py:827`).
3. Loader en `VectorStoreManager.load_and_split()`
   (`agents_ai/vectorstore_manager.py:65`).
4. UI: handler en `guardar_detalles_agente()` (`crm/view_mientrenamiento.py:104`)
   + tab Conocimiento en `form_pagina.html`.

**Agregar nuevo node type al motor que llame IA:**
- Hoy el motor tradicional no invoca IA. Si se quiere agregar:
  1. Nuevo `tipo_nodo` en `OpcionDepartamentoChatBot` (`crm/models.py:1216`).
  2. Handler en `motor_flujo_chatbot.py` que instancie `AgenteConsultor`.
  3. Logger en `ConsumoTokenIA(origen='motor_node')`.

**Agregar nueva acción AJAX:**
- Branch nuevo en `entrenamiento_ia_view()` POST dispatcher
  (`crm/view_mientrenamiento.py:174-1470`).
- Patrón: `if accion == 'mi_action': ... return JsonResponse({...})`.

**Habilitar enforcement real de quota:**
1. En `whatsapp/procesar_mensaje.py:582` antes de invocar IA, llamar
   `alertas_consumo.consumo_hoy(apikey)` y comparar con `umbral_diario`.
2. Si excede → return early con mensaje de quota agotada.

**Trackear embeddings:**
1. En `VectorStoreManager.build_and_save()`
   (`agents_ai/vectorstore_manager.py:75`), después de
   `FAISS.from_documents`, calcular tokens (suma de chars/4 o tiktoken) y
   crear `ConsumoTokenIA(origen='embedding', tokens_entrada=N, tokens_salida=0)`.
2. Agregar al dashboard de consumo.
