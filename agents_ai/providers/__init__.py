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
from .base import BaseProvider
from .gemini import GeminiProvider
from .openai import OpenAIProvider
from .claude import ClaudeProvider


# Registry: nombre interno → instancia singleton del provider
_PROVIDERS: dict[str, BaseProvider] = {
    GeminiProvider.name: GeminiProvider(),
    OpenAIProvider.name: OpenAIProvider(),
    ClaudeProvider.name: ClaudeProvider(),
}

# Mapeo id (de crm.models.PROVEEDOR_CHOICES) → nombre interno
PROVEEDOR_ID_TO_NAME: dict[int, str] = {
    2: 'gemini',
    3: 'openai',
    4: 'claude',
}


# Modelos disponibles para cada provider — agrupados por familia.
# Si dejás esto vacío en el agente, se usa el default del provider (default_model()).
MODELOS_DISPONIBLES = (
    # ── Google Gemini ──
    ('gemini-2.5-flash',          '[Gemini] 2.5 Flash — rápido y económico (default)'),
    ('gemini-2.5-pro',            '[Gemini] 2.5 Pro — máxima calidad'),
    ('gemini-1.5-flash',          '[Gemini] 1.5 Flash — versión anterior, estable'),
    ('gemini-1.5-pro',            '[Gemini] 1.5 Pro — versión anterior, alta calidad'),
    # ── OpenAI ──
    ('gpt-4o-mini',               '[OpenAI] GPT-4o Mini — rápido y económico (default)'),
    ('gpt-4o',                    '[OpenAI] GPT-4o — máxima calidad'),
    ('gpt-4-turbo',               '[OpenAI] GPT-4 Turbo — alta calidad'),
    ('gpt-3.5-turbo',             '[OpenAI] GPT-3.5 Turbo — más económico, menor calidad'),
    # ── Anthropic Claude ──
    ('claude-haiku-4-5-20251001', '[Claude] Haiku 4.5 — rápido y económico (default)'),
    ('claude-sonnet-4-5',         '[Claude] Sonnet 4.5 — balanceado'),
    ('claude-opus-4-6',           '[Claude] Opus 4.6 — máxima calidad'),
)


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
    'get_provider', 'PROVEEDOR_ID_TO_NAME', 'MODELOS_DISPONIBLES',
]
