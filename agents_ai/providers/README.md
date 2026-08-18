# agents_ai/providers — proveedores LLM

Registry de proveedores. El resto del código NUNCA importa un proveedor
concreto — siempre `get_provider(nombre_o_id)`.

| Archivo | Para qué es |
|---|---|
| `__init__.py` | El registry: `get_provider()`, mapa id→nombre (`PROVEEDOR_ID_TO_NAME`), la lista de modelos para el dropdown (`MODELOS_DISPONIBLES`) y el cache de clientes `get_llm_cached()` / `get_embeddings_cached()` — reutiliza la instancia LangChain (y su pool de conexiones HTTP) mientras la config (provider, key, modelo, max_tokens, temperature, base_url) no cambie; cap de 64 entradas. El hot path (`AgenteConsultor`) usa siempre las variantes cacheadas. Aquí se registra todo provider nuevo. |
| `base.py` | `BaseProvider` (ABC): `default_model()`, `get_llm(apikey, modelo, max_tokens, temperature, base_url)`, `get_embeddings(apikey, base_url)`, `extract_tokens(ai_message)`. Define los presupuestos de red compartidos: `LLM_TIMEOUT_SEGUNDOS` (60s cloud), `LLM_TIMEOUT_LOCAL_SEGUNDOS` (120s Ollama/compat), `LLM_MAX_RETRIES` (1) y `EMBEDDINGS_TIMEOUT_SEGUNDOS` (30s) — todo provider debe pasarlos a su cliente para que una API colgada no bloquee el webhook por minutos. |
| `gemini.py` | Google Gemini (id 2) — LLM + embeddings `text-embedding-004`. |
| `openai.py` | OpenAI GPT (id 3) — LLM + embeddings; acepta `base_url` para gateways compatibles. |
| `claude.py` | Anthropic Claude (id 4) — solo LLM (sin embeddings: el agente usa otra key para el vectorstore). |
| `openai_compat.py` | Base compartida para providers con endpoint OpenAI-compatible: resuelve `base_url` (agrega `/v1`), construye `ChatOpenAI` y extrae tokens. |
| `ollama.py` | Ollama (id 5) — modelos locales auto-hospedados, costo cero por token; embeddings `nomic-embed-text`. |
| `deepseek.py` | DeepSeek cloud (id 6) — `deepseek-chat` / `deepseek-reasoner`; sin embeddings. |
| `huawei.py` | Huawei Cloud MaaS (id 7) — requiere `base_url` del despliegue; sin embeddings. |

Para agregar un proveedor: clase nueva aquí + registrarla en `__init__.py` +
choice en `crm.models.PROVEEDOR_CHOICES` + modelos en `MODELOS_DISPONIBLES` +
default en `crm/view_mientrenamiento._DEFAULT_MODEL_BY_PROVIDER`.
