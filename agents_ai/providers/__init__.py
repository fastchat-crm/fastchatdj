"""
Registry central de providers de LLM.

Punto de entrada único: `get_provider(nombre_o_id)` devuelve la instancia BaseProvider
correspondiente. Si el provider no existe, lanza ValueError con mensaje claro.

Cómo agregar un nuevo provider (ej. Claude):
  1. Crear `agents_ai/providers/claude.py` con `class ClaudeProvider(BaseProvider)`.
  2. En `crm/models.py` agregar `(4, 'CLAUDE')` a `PROVEEDOR_CHOICES`.
  3. Aquí abajo importar `ClaudeProvider`, agregarlo a `_PROVIDERS` y mapear el id 4
     a `'claude'` en `PROVEEDOR_ID_TO_NAME`.
  4. Listo — el resto del código ya lo soporta automáticamente.
"""
import hashlib
import logging
import threading

import requests
from django.core.cache import cache

from .base import BaseProvider
from .gemini import GeminiProvider
from .openai import OpenAIProvider
from .claude import ClaudeProvider
from .ollama import OllamaProvider
from .ollama_local import OllamaLocalProvider
from .deepseek import DeepSeekProvider
from .huawei import HuaweiProvider

logger = logging.getLogger(__name__)


# Registry: nombre interno → instancia singleton del provider
_PROVIDERS: dict[str, BaseProvider] = {
    GeminiProvider.name: GeminiProvider(),
    OpenAIProvider.name: OpenAIProvider(),
    ClaudeProvider.name: ClaudeProvider(),
    OllamaProvider.name: OllamaProvider(),
    OllamaLocalProvider.name: OllamaLocalProvider(),
    DeepSeekProvider.name: DeepSeekProvider(),
    HuaweiProvider.name: HuaweiProvider(),
}

# Mapeo id (de crm.models.PROVEEDOR_CHOICES) → nombre interno
PROVEEDOR_ID_TO_NAME: dict[int, str] = {
    2: 'gemini',
    3: 'openai',
    4: 'claude',
    5: 'ollama',
    6: 'deepseek',
    7: 'huawei',
    8: 'ollama_local',
}


# Modelos disponibles para cada provider — agrupados por familia.
# Si dejás esto vacío en el agente, se usa el default del provider (default_model()).
MODELOS_DISPONIBLES = (
    ('gemini-2.5-flash',          '[Gemini] 2.5 Flash — rápido y económico (default)'),
    ('gemini-2.5-flash-lite',     '[Gemini] 2.5 Flash Lite — el más barato'),
    ('gemini-2.5-pro',            '[Gemini] 2.5 Pro — máxima calidad'),
    ('gemini-1.5-flash',          '[Gemini] 1.5 Flash — versión anterior, estable'),
    ('gemini-1.5-flash-8b',       '[Gemini] 1.5 Flash 8B — versión anterior, ultra barato'),
    ('gemini-1.5-pro',            '[Gemini] 1.5 Pro — versión anterior, alta calidad'),
    ('gpt-4o-mini',               '[OpenAI] GPT-4o Mini — rápido y económico (default)'),
    ('gpt-4o',                    '[OpenAI] GPT-4o — alta calidad'),
    ('gpt-4.1',                   '[OpenAI] GPT-4.1 — máxima calidad'),
    ('gpt-4.1-mini',              '[OpenAI] GPT-4.1 Mini — balanceado'),
    ('gpt-4.1-nano',              '[OpenAI] GPT-4.1 Nano — el más barato'),
    ('gpt-4-turbo',               '[OpenAI] GPT-4 Turbo — versión anterior'),
    ('gpt-3.5-turbo',             '[OpenAI] GPT-3.5 Turbo — más económico, menor calidad'),
    ('claude-haiku-4-5-20251001', '[Claude] Haiku 4.5 — rápido y económico (default)'),
    ('claude-sonnet-4-6',         '[Claude] Sonnet 4.6 — balanceado'),
    ('claude-sonnet-4-5',         '[Claude] Sonnet 4.5 — versión anterior'),
    ('claude-opus-4-7',           '[Claude] Opus 4.7 — máxima calidad'),
    ('claude-opus-4-6',           '[Claude] Opus 4.6 — versión anterior'),
    ('gpt-oss:20b',               '[Ollama] GPT-OSS 20B — Cloud, rápido y económico (default)'),
    ('gpt-oss:120b',              '[Ollama] GPT-OSS 120B — Cloud, alta calidad'),
    ('gemma3:12b',                '[Ollama] Gemma 3 12B — Cloud, equilibrado'),
    ('gemma3:27b',                '[Ollama] Gemma 3 27B — Cloud, alta calidad'),
    ('qwen3-next:80b',            '[Ollama] Qwen3-Next 80B — Cloud, alta calidad'),
    ('glm-4.7',                   '[Ollama] GLM 4.7 — Cloud, alta calidad'),
    ('deepseek-v3.2',             '[Ollama] DeepSeek V3.2 — Cloud, razonamiento'),
    ('ministral-3:8b',            '[Ollama] Ministral 3 8B — Cloud, ligero'),
    ('deepseek-chat',             '[DeepSeek] V3 Chat — económico (default)'),
    ('deepseek-reasoner',         '[DeepSeek] R1 Reasoner — razonamiento profundo'),
    ('DeepSeek-V3',               '[Huawei MaaS] DeepSeek V3 (default)'),
    ('DeepSeek-R1',               '[Huawei MaaS] DeepSeek R1 — razonamiento'),
    ('Qwen3-32B',                 '[Huawei MaaS] Qwen3 32B'),
    ('llama3.1',                  '[Ollama Local] Llama 3.1 — local, sin costo por token (default)'),
    ('llama3.2',                  '[Ollama Local] Llama 3.2 — local liviano'),
    ('qwen2.5',                   '[Ollama Local] Qwen 2.5 — local multilingüe'),
    ('mistral',                   '[Ollama Local] Mistral 7B — local'),
    ('deepseek-r1',               '[Ollama Local] DeepSeek R1 — razonamiento local'),
)


# ---------------------------------------------------------------------------
# Cache de clientes LLM / embeddings
#
# Antes se instanciaba un cliente nuevo por cada mensaje entrante — handshake
# TLS y pool de conexiones desde cero en cada llamada. Los clientes LangChain
# (httpx/grpc por debajo) son thread-safe, así que se reutilizan keyed por su
# configuración completa. Cap simple para no crecer sin límite si rotan keys.
# ---------------------------------------------------------------------------
_MAX_CLIENTES_CACHE = 64
_llm_cache: dict[tuple, object] = {}
_emb_cache: dict[tuple, object] = {}
_clientes_lock = threading.Lock()


def _hash_apikey(apikey):
    """Huella corta de la apikey para usar como parte de la clave de cache.

    Nunca guardamos la apikey en claro dentro del diccionario en memoria: si el
    proceso se vuelca (core dump, inspección) la clave quedaría expuesta. El hash
    identifica igual de bien la config sin exponer el secreto.
    """
    if apikey is None:
        return None
    return hashlib.sha256(str(apikey).encode('utf-8')).hexdigest()


def get_llm_cached(provider: BaseProvider, apikey, model_name, max_output_tokens,
                   temperature=0.1, base_url=None):
    """Devuelve el LLM del provider reutilizando la instancia si la config no cambió."""
    key = (provider.name, _hash_apikey(apikey), model_name, max_output_tokens, float(temperature), base_url)
    with _clientes_lock:
        llm = _llm_cache.get(key)
        if llm is not None:
            return llm
    llm = provider.get_llm(
        apikey=apikey, model_name=model_name, max_output_tokens=max_output_tokens,
        temperature=temperature, base_url=base_url,
    )
    with _clientes_lock:
        if len(_llm_cache) >= _MAX_CLIENTES_CACHE:
            _llm_cache.clear()
        _llm_cache[key] = llm
    return llm


def get_embeddings_cached(provider: BaseProvider, apikey, base_url=None):
    """Devuelve los embeddings del provider reutilizando la instancia por config.

    Propaga NotImplementedError de providers sin API de embeddings (Claude,
    DeepSeek, Huawei) — el caller decide el fallback.
    """
    key = (provider.name, _hash_apikey(apikey), base_url)
    with _clientes_lock:
        emb = _emb_cache.get(key)
        if emb is not None:
            return emb
    emb = provider.get_embeddings(apikey, base_url=base_url)
    with _clientes_lock:
        if len(_emb_cache) >= _MAX_CLIENTES_CACHE:
            _emb_cache.clear()
        _emb_cache[key] = emb
    return emb


# Prefijo del label (tal como aparece en MODELOS_DISPONIBLES) → id de proveedor.
_LABEL_PREFIX_TO_PROVEEDOR_ID: dict[str, int] = {
    '[Gemini]': 2,
    '[OpenAI]': 3,
    '[Claude]': 4,
    '[Ollama]': 5,
    '[Ollama Local]': 8,
}

_CACHE_TIMEOUT_SEGUNDOS = 1800


def _fallback_modelos(proveedor_id: int) -> list[tuple[str, str]]:
    """Filtra MODELOS_DISPONIBLES por el prefijo de label correspondiente al proveedor."""
    prefijo = next(
        (p for p, pid in _LABEL_PREFIX_TO_PROVEEDOR_ID.items() if pid == proveedor_id),
        None,
    )
    if prefijo is None:
        return []
    return [(mid, label) for mid, label in MODELOS_DISPONIBLES if label.startswith(prefijo)]


def listar_modelos_disponibles(proveedor_id: int, api_key: str = "", force_refresh: bool = False) -> list[tuple[str, str]]:
    """Devuelve la lista de modelos disponibles para un proveedor, en vivo desde su API.

    Si no hay `api_key`, devuelve el fallback estático (MODELOS_DISPONIBLES filtrado por
    proveedor). Si hay `api_key`, intenta obtener la lista en vivo (con cache de 30 min,
    salvo `force_refresh=True`) y, si falla o viene vacía, cae de nuevo al fallback estático.
    """
    if not api_key:
        return _fallback_modelos(proveedor_id)

    key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()[:16]
    cache_key = f"agents_ai:modelos_disponibles:{proveedor_id}:{key_hash}"

    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        provider = get_provider(proveedor_id)
        modelos = provider.list_models(api_key)
    except Exception as exc:
        logger.warning(
            "No se pudo obtener modelos en vivo para proveedor_id=%s: %s", proveedor_id, exc,
        )
        return _fallback_modelos(proveedor_id)

    if not modelos:
        logger.warning("Lista de modelos vacía para proveedor_id=%s; usando fallback.", proveedor_id)
        return _fallback_modelos(proveedor_id)

    cache.set(cache_key, modelos, _CACHE_TIMEOUT_SEGUNDOS)
    return modelos


def get_provider(name_or_id) -> BaseProvider:
    """Devuelve la instancia del provider por nombre ('gemini', 'openai', ...)
    o por id numérico (2=gemini, 3=openai, ...).

    Lanza ValueError si el provider no está registrado.
    """
    if isinstance(name_or_id, int):
        name = PROVEEDOR_ID_TO_NAME.get(name_or_id)
        if name is None:
            raise ValueError(f"Provider id {name_or_id} no registrado. Ids válidos: {list(PROVEEDOR_ID_TO_NAME)}")
    else:
        name = str(name_or_id).lower()

    provider = _PROVIDERS.get(name)
    if provider is None:
        raise ValueError(f"Provider '{name}' no registrado. Disponibles: {list(_PROVIDERS)}")
    return provider


__all__ = [
    'BaseProvider', 'GeminiProvider', 'OpenAIProvider', 'ClaudeProvider',
    'OllamaProvider', 'OllamaLocalProvider', 'DeepSeekProvider', 'HuaweiProvider',
    'get_provider', 'get_llm_cached', 'get_embeddings_cached',
    'PROVEEDOR_ID_TO_NAME', 'MODELOS_DISPONIBLES', 'listar_modelos_disponibles',
]
