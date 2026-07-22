"""Provider para OpenAI (GPT)."""
import requests
from langchain_community.embeddings import OpenAIEmbeddings

from .base import (
    BaseProvider,
    LLM_TIMEOUT_SEGUNDOS,
    LLM_MAX_RETRIES,
    EMBEDDINGS_TIMEOUT_SEGUNDOS,
    EMBEDDINGS_MAX_RETRIES,
)

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"


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

    def list_models(self, api_key: str) -> list[tuple[str, str]]:
        response = requests.get(
            OPENAI_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=6,
        )
        response.raise_for_status()
        data = response.json()
        # Excluir SKUs que no sirven como modelo de chat (audio/imagen/embeddings/etc).
        no_chat = (
            "-audio", "-realtime", "-transcribe", "-tts", "-search", "-image",
            "image-", "embedding", "moderation", "dall-e", "whisper",
            "babbage", "davinci",
        )
        modelos = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            if not model_id.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
                continue
            if any(bad in model_id for bad in no_chat):
                continue
            modelos.append((model_id, f"[OpenAI] {model_id}"))
        modelos.sort(key=lambda t: t[0])
        return modelos
