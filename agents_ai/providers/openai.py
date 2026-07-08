"""Provider para OpenAI (GPT)."""
from langchain_community.embeddings import OpenAIEmbeddings

from .base import (
    BaseProvider,
    LLM_TIMEOUT_SEGUNDOS,
    LLM_MAX_RETRIES,
    EMBEDDINGS_TIMEOUT_SEGUNDOS,
    EMBEDDINGS_MAX_RETRIES,
)


class OpenAIProvider(BaseProvider):
    name = "openai"

    def default_model(self) -> str:
        return "gpt-4o-mini"

    def get_llm(self, apikey, model_name, max_output_tokens, temperature=0.1, base_url=None):
        # Import diferido — el paquete no se carga si nunca usamos OpenAI
        from langchain_community.chat_models import ChatOpenAI
        kwargs = dict(
            model_name=model_name,
            openai_api_key=apikey,
            max_tokens=max_output_tokens,
            temperature=temperature,
            request_timeout=LLM_TIMEOUT_SEGUNDOS,
            max_retries=LLM_MAX_RETRIES,
        )
        if base_url:
            kwargs['openai_api_base'] = base_url
        return ChatOpenAI(**kwargs)

    def get_embeddings(self, apikey, base_url=None):
        kwargs = dict(
            openai_api_key=apikey,
            request_timeout=EMBEDDINGS_TIMEOUT_SEGUNDOS,
            max_retries=EMBEDDINGS_MAX_RETRIES,
        )
        if base_url:
            kwargs['openai_api_base'] = base_url
        return OpenAIEmbeddings(**kwargs)

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
