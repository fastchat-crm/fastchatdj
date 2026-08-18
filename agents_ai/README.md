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
| `optimizador.py` | Auditoría de consumo por agente: cruza la configuración efectiva con `ConsumoTokenIA` y devuelve hallazgos accionables. Ver la sección "Optimizador de consumo" más abajo. |
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

## Optimizador de consumo (2026-08-10)

`optimizador.py` + pestaña **Optimización** en `/crm/centro-ia/`.

El punto de partida es una medición, no una intuición: en producción WhatsApp
gastó **370.722 tokens de entrada contra 48.584 de salida**, un factor de 7,6.
El gasto de un agente no está en lo que responde sino en lo que se le manda, y
lo que se le manda lo arma la configuración. Por eso el optimizador cruza dos
cosas que antes se miraban por separado — la cascada de parámetros
(`crm/ia_config.py`) y el consumo real (`ConsumoTokenIA`).

### Presupuesto de prompt

`presupuesto_prompt(agente)` calcula cuánto pesaría el prompt si cada pieza se
llenara hasta su tope: instrucciones + contexto estático + RAG + historial. Ese
número comparado contra la entrada real medida da la **saturación**, y de ahí
salen las dos lecturas que importan:

- **Saturación baja** (< 60 %): el tope no es el que manda el tamaño real, así
  que bajarlo no quita un solo token de la factura. El optimizador se calla.
- **Saturación > 100 %**: hay tokens entrando por fuera de la cascada
  (herramientas, FAQs, la pregunta del usuario). Se reporta como
  `presupuesto_incompleto`, porque es gasto que hoy no se puede recortar desde
  el panel y conviene identificar antes de apretar los topes que sí existen.

### Reglas

| Código | Qué detecta |
|---|---|
| `prompt_inflado` | La pieza más pesada del prompt, solo cuando el presupuesto se está usando de verdad. Propone recortar un 30 %. |
| `presupuesto_incompleto` | El prompt real pesa más que todos los topes sumados. |
| `pico_de_prompt` | Una llamada 3× por encima del promedio: contexto que se desbocó, no una pregunta larga. |
| `razonamiento_facturado` | Una tarea de clasificación devolviendo cientos de tokens. Casi siempre es pensamiento extendido. |
| `sin_instrumentar` | Consumo sin `origen`: no se puede atribuir ni recortar. |
| `faqs_sin_vectorizar` | Mete N FAQs en cada prompt y no tiene conocimiento vectorizado. |
| `tope_salida_holgado` | El tope supera 3× la respuesta más larga real. No ahorra por sí solo; acota el peor caso. |

Los propuestos se calculan sobre el **máximo observado**, nunca sobre el
promedio: un agente que responde 34 tokens de media pero 900 en su caso más
largo quedaría con el tope en 102 y truncaría la respuesta larga.

### Por qué el diagnóstico no lo hace un LLM

Todo lo anterior es aritmética sobre datos medidos: no hay nada que interpretar
y sí mucho que equivocar — un modelo inventando nombres de campo escribiría
configuraciones inválidas, y gastar tokens para ahorrar tokens es discutible.

El LLM entra en un solo lugar donde gana: `revisar_texto_prompt()` lee las
instrucciones escritas a mano y señala bloques repetidos o sobrantes. Eso sí es
criterio. Es una acción aparte y explícita porque es la única que cuesta tokens.
Pide una lista de recortes, **no una reescritura**: reescribir automáticamente un
prompt en producción cambia cómo el agente le habla a los clientes sin que nadie
lo haya leído.

### Aplicar

`aplicar_recomendacion()` escribe en el **agente**, no en el perfil ni en la
plataforma: fija el valor para ese agente y los que heredan siguen heredando.
Solo acepta campos de `CAMPOS_HEREDABLES` que existan como columna del agente —
`cfg_umbral_distancia` y `cfg_max_static_amplia` viven solo en el Centro de IA y
escribirlos ahí sería inventar un atributo que nadie lee.

## Catálogo por API: tope y recuperación por relevancia (2026-08-10)

El bloque de las fuentes API (`DetalleAgentesAI` tipo=1) era el único del prompt
sin ningún tope. El RAG tiene `cfg_max_context_chars` y el contexto estático
`cfg_max_static_chars`; este entraba entero, en cada mensaje. Medido en EPUNEMI
VENDEDOR: **44.710 caracteres de catálogo (97 ítems) por mensaje**, incluidos
cursos de 2024 con `Activo: False` y precio `$0.00`.

No era solo costo. Mandar 97 cursos para contestar por uno obliga al modelo a
encontrar el dato bueno dentro de un pajar de datos muertos — es la causa
directa de que el agente respondiera mal.

Dos mecanismos, en este orden:

1. **`_filtrar_items_api`** — ante una pregunta puntual se queda solo con los
   ítems que hablan de ella. La elección es léxica, sin embeddings: el nombre
   del curso está literalmente en la pregunta ("cuánto cuesta el diplomado en
   oncología"), así que alcanza con coincidencia de palabras y no cuesta ni una
   llamada. Se descartan palabras vacías (`_PALABRAS_VACIAS`) y términos de
   menos de 4 letras, que producen coincidencias por azar.
2. **`_recortar_bloque_apis`** — el techo (`cfg_max_api_chars`, 12.000 por
   defecto, editable en Parámetros IA). Se aplica a las preguntas amplias, donde
   hay que mandar la lista y no un pedazo. Corta en límite de ítem, nunca a
   mitad de línea.

Quién decide cuál aplica es `_es_consulta_amplia`, el mismo criterio que ya usa
el resto del motor para el Modo A / Modo B. Si el filtro no encuentra nada, se
manda la lista recortada: es preferible que el modelo vea una muestra y pueda
ofrecer alternativas antes que dejarlo sin nada.

Medido sobre el catálogo de 44.710 caracteres:

| Pregunta | Bloque | Ahorro | Primer ítem elegido |
|---|---:|---:|---|
| "qué cursos tienen" (amplia) | 12.112 | 73 % | — (lista completa recortada) |
| "cuánto cuesta el diplomado en oncología" | 2.943 | 93 % | DIPLOMADO EN ONCOLOGÍA ✓ |
| "tienen algo de enfermería" | 2.926 | 93 % | AUXILIAR DE ENFERMERÍA ✓ |
| "qué necesito para la licencia profesional C" | 2.876 | 94 % | LICENCIA PROFESIONAL "C" ✓ |

Extremo a extremo, EPUNEMI VENDEDOR pasó de ~17.000 tokens de entrada por
mensaje a 2.727–5.421, con las respuestas dando los precios correctos.

Ambos mecanismos dejan una nota al final del bloque avisando que la lista es
parcial. Sin eso el modelo presenta lo que le llegó como si fuera el catálogo
entero y le dice al cliente que un curso no existe.

## Pensamiento extendido: `razonamiento=False` (2026-08-10)

`BaseProvider.get_llm()` acepta `razonamiento`. En `False`, el provider de
Gemini manda `thinking_budget=0` a los modelos 2.5 (solo esa familia lo
entiende; mandárselo a otro es un error de la API). Los demás providers aceptan
el parámetro y lo ignoran.

No es un ajuste de calidad sino de costo: **los tokens de razonamiento se
facturan como salida**. Medido contra la API real con el mismo prompt de
clasificación:

| | Entrada | Salida | Respuesta |
|---|---:|---:|---|
| `razonamiento=True` | 68 | 180 | `{"sentimiento":"positiva","puntuacion":9}` |
| `razonamiento=False` | 68 | **18** | `{"sentimiento":"positiva","puntuacion":8}` |

Diez veces menos salida por la misma respuesta. En producción el análisis de
sentimiento venía gastando ~1.900 tokens de salida para devolver un JSON de tres
campos sobre un texto de 350.

`AgenteResumidor` (resumir + sentimiento) usa `razonamiento=False`: son tareas de
extracción, el modelo no tiene nada que deliberar. **El agente conversacional
no**, ahí el razonamiento sí mejora la respuesta.

`razonamiento` forma parte de la clave de caché de `get_llm_cached`. Sin eso, el
primer llamador en pedir una config fijaría el modo de pensamiento para todos
los que compartan modelo y key.
