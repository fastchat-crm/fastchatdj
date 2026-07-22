"""Provider para Ollama Cloud — API compatible con OpenAI (https://ollama.com/v1).

Ollama Cloud expone un endpoint OpenAI-compatible, así que reutilizamos ChatOpenAI
apuntando el base_url a Ollama. El conteo de tokens viene en formato OpenAI estándar.

Nota: Ollama Cloud NO provee embeddings con la cuenta actual; el RAG usa embeddings
de otro proveedor (Gemini). Por eso get_embeddings lanza NotImplementedError.

Para Ollama auto-hospedado (modelos locales), ver providers/ollama_local.py.
"""
import requests

from .base import BaseProvider

OLLAMA_BASE_URL = "https://ollama.com/v1"
OLLAMA_MODELS_URL = f"{OLLAMA_BASE_URL}/models"


class OllamaProvider(BaseProvider):
    name = "ollama"

    def default_model(self) -> str:
        return "gpt-oss:20b"

    def get_llm(self, apikey, model_name, max_output_tokens, temperature=0.1, base_url=None):
        # ChatOpenAI moderno (langchain_openai) — soporta tool-calling (bind_tools)
        # y parsea bien las respuestas. El de langchain_community está deprecado y
        # NO soporta bind_tools con Ollama.
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name or self.default_model(),
            api_key=apikey,
            base_url=OLLAMA_BASE_URL,
            max_tokens=max_output_tokens,
            temperature=temperature,
        )

    def get_embeddings(self, apikey, base_url=None):
        raise NotImplementedError(
            "Ollama Cloud no provee embeddings. Para el RAG de un agente Ollama Cloud, "
            "configura embeddings de Gemini (el vectorstore usa un proveedor de embeddings aparte)."
        )

    def extract_tokens(self, ai_message) -> tuple[int, int]:
        # Formato OpenAI estándar (Ollama Cloud lo respeta).
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
            OLLAMA_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=6,
        )
        response.raise_for_status()
        data = response.json()
        modelos = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            if not model_id:
                continue
            modelos.append((model_id, f"[Ollama] {model_id}"))
        modelos.sort(key=lambda t: t[0])
        return modelos
