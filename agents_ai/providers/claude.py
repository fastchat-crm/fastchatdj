"""Provider para Anthropic Claude."""
import requests

from .base import BaseProvider

CLAUDE_MODELS_URL = "https://api.anthropic.com/v1/models"
CLAUDE_API_VERSION = "2023-06-01"


class ClaudeProvider(BaseProvider):
    name = "claude"

    def default_model(self) -> str:
        return "claude-haiku-4-5-20251001"

    def get_llm(self, apikey, model_name, max_output_tokens, temperature=0.1):
        # Import diferido — el paquete no se carga si nunca usamos Claude
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            anthropic_api_key=apikey,
            max_tokens=max_output_tokens,
            temperature=temperature,
        )

    def get_embeddings(self, apikey):
        # Anthropic NO ofrece API de embeddings propia. Para FAISS/vectorstores,
        # el usuario debe registrar otra API Key con Gemini u OpenAI.
        raise NotImplementedError(
            "Anthropic Claude no ofrece API de embeddings. "
            "Configura una API Key adicional con Gemini u OpenAI para el vectorstore "
            "(el agente puede usar Claude para chat y otra key para embeddings)."
        )

    def extract_tokens(self, ai_message) -> tuple[int, int]:
        # Formato estándar LangChain — Claude reporta usage_metadata
        usage_std = getattr(ai_message, 'usage_metadata', None) or {}
        if usage_std:
            return (
                usage_std.get('input_tokens', 0) or 0,
                usage_std.get('output_tokens', 0) or 0,
            )
        meta = getattr(ai_message, 'response_metadata', {}) or {}
        usage = meta.get('usage', {}) or {}
        return (
            usage.get('input_tokens', 0) or 0,
            usage.get('output_tokens', 0) or 0,
        )

    def list_models(self, api_key: str) -> list[tuple[str, str]]:
        response = requests.get(
            CLAUDE_MODELS_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": CLAUDE_API_VERSION,
            },
            timeout=6,
        )
        response.raise_for_status()
        data = response.json()
        modelos = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            if not model_id:
                continue
            modelos.append((model_id, f"[Claude] {model_id}"))
        modelos.sort(key=lambda t: t[0])
        return modelos
