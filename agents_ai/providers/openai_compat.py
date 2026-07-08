"""Base compartida para providers con API compatible con OpenAI.

Ollama, DeepSeek y Huawei MaaS exponen endpoints /v1/chat/completions con el
mismo contrato que OpenAI — se reutiliza ChatOpenAI apuntando a otra base_url.
La base_url viene de `ApiKeyIA.base_url`; si está vacía se usa
`default_base_url` del provider concreto.
"""
from .base import BaseProvider, LLM_TIMEOUT_LOCAL_SEGUNDOS, LLM_MAX_RETRIES


class OpenAICompatProvider(BaseProvider):
    name = ""
    default_base_url = ""
    timeout_segundos = LLM_TIMEOUT_LOCAL_SEGUNDOS

    def _resolver_base_url(self, base_url) -> str:
        url = (base_url or self.default_base_url or '').strip().rstrip('/')
        if not url:
            raise ValueError(
                f"El proveedor '{self.name}' requiere una Base URL configurada en la API Key."
            )
        if not url.endswith('/v1'):
            url = f"{url}/v1"
        return url

    def get_llm(self, apikey, model_name, max_output_tokens, temperature=0.1, base_url=None):
        from langchain_community.chat_models import ChatOpenAI
        return ChatOpenAI(
            model_name=model_name,
            openai_api_key=(apikey or 'sin-clave'),
            openai_api_base=self._resolver_base_url(base_url),
            max_tokens=max_output_tokens,
            temperature=temperature,
            request_timeout=self.timeout_segundos,
            max_retries=LLM_MAX_RETRIES,
        )

    def get_embeddings(self, apikey, base_url=None):
        raise NotImplementedError(
            f"El proveedor '{self.name}' no ofrece API de embeddings. "
            "Configura una API Key adicional con Gemini u OpenAI para el vectorstore."
        )

    def extract_tokens(self, ai_message) -> tuple[int, int]:
        usage_std = getattr(ai_message, 'usage_metadata', None) or {}
        if usage_std:
            return (
                usage_std.get('input_tokens', 0) or 0,
                usage_std.get('output_tokens', 0) or 0,
            )
        meta = getattr(ai_message, 'response_metadata', {}) or {}
        usage = meta.get('token_usage', {}) or {}
        return (
            usage.get('prompt_tokens', 0) or 0,
            usage.get('completion_tokens', 0) or 0,
        )
