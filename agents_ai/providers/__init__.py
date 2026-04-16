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


# Registry: nombre interno → instancia singleton del provider
_PROVIDERS: dict[str, BaseProvider] = {
    GeminiProvider.name: GeminiProvider(),
    OpenAIProvider.name: OpenAIProvider(),
}

# Mapeo id (de crm.models.PROVEEDOR_CHOICES) → nombre interno
PROVEEDOR_ID_TO_NAME: dict[int, str] = {
    2: 'gemini',
    3: 'openai',
}


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


__all__ = ['BaseProvider', 'GeminiProvider', 'OpenAIProvider', 'get_provider', 'PROVEEDOR_ID_TO_NAME']
