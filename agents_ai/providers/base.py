"""
Interfaz abstracta para providers de LLM.

Cada provider concreto (Gemini, OpenAI, Claude, etc.) implementa esta clase y se
registra en `agents_ai/providers/__init__.py`. El resto del código consume providers
exclusivamente a través de esta interfaz — no importa proveedores concretos.

Para agregar un proveedor nuevo:
  1. Crear `agents_ai/providers/<nombre>.py` con una clase `<Nombre>Provider(BaseProvider)`
  2. Agregar el `(id, 'NOMBRE')` correspondiente a `crm.models.PROVEEDOR_CHOICES`
  3. Registrarlo en `PROVIDERS` y `PROVEEDOR_ID_TO_NAME` en `providers/__init__.py`
"""
from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Interfaz que cada proveedor de LLM debe implementar."""

    name: str = ""  # identificador interno: 'gemini', 'openai', 'claude', etc.

    @abstractmethod
    def default_model(self) -> str:
        """Modelo por defecto cuando no se especifica uno."""
        ...

    @abstractmethod
    def get_llm(self, apikey: str, model_name: str, max_output_tokens: int, temperature: float = 0.1):
        """Devuelve una instancia LangChain del LLM."""
        ...

    @abstractmethod
    def get_embeddings(self, apikey: str):
        """Devuelve una instancia LangChain de embeddings para FAISS."""
        ...

    @abstractmethod
    def extract_tokens(self, ai_message) -> tuple[int, int]:
        """Extrae (tokens_input, tokens_output) de un AIMessage."""
        ...
