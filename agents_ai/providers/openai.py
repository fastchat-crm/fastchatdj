"""Provider para OpenAI (GPT)."""
from langchain_community.embeddings import OpenAIEmbeddings

from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    name = "openai"

    def default_model(self) -> str:
        return "gpt-4o-mini"

    def get_llm(self, apikey, model_name, max_output_tokens, temperature=0.1):
        # Import diferido — el paquete no se carga si nunca usamos OpenAI
        from langchain_community.chat_models import ChatOpenAI
        return ChatOpenAI(
            model_name=model_name,
            openai_api_key=apikey,
            max_tokens=max_output_tokens,
            temperature=temperature,
        )

    def get_embeddings(self, apikey):
        return OpenAIEmbeddings(openai_api_key=apikey)

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
