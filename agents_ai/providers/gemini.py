"""Provider para Google Gemini (Generative AI)."""
import requests
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from .base import (
    BaseProvider,
    LLM_TIMEOUT_SEGUNDOS,
    LLM_MAX_RETRIES,
    EMBEDDINGS_TIMEOUT_SEGUNDOS,
)

GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseProvider):
    name = "gemini"

    def default_model(self) -> str:
        return "gemini-2.5-flash"

    def get_llm(self, apikey, model_name, max_output_tokens, temperature=0.1, base_url=None):
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=apikey,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            timeout=LLM_TIMEOUT_SEGUNDOS,
            max_retries=LLM_MAX_RETRIES,
        )

    def get_embeddings(self, apikey, base_url=None):
        return GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=apikey,
            request_options={'timeout': EMBEDDINGS_TIMEOUT_SEGUNDOS},
        )

    def extract_tokens(self, ai_message) -> tuple[int, int]:
        # Primero intenta el formato estándar de LangChain
        usage_std = getattr(ai_message, 'usage_metadata', None) or {}
        if usage_std:
            return (
                usage_std.get('input_tokens', 0) or 0,
                usage_std.get('output_tokens', 0) or 0,
            )
        # Fallback al formato propio de Gemini
        meta = getattr(ai_message, 'response_metadata', {}) or {}
        usage = meta.get('usage_metadata', {}) or {}
        return (
            usage.get('prompt_token_count', 0) or 0,
            usage.get('candidates_token_count', 0) or 0,
        )

    def list_models(self, api_key: str) -> list[tuple[str, str]]:
        modelos = []
        page_token = ""
        # Paginar hasta agotar; tope de 20 páginas como salvaguarda.
        for _ in range(20):
            params = {"key": api_key, "pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            response = requests.get(GEMINI_MODELS_URL, params=params, timeout=6)
            response.raise_for_status()
            data = response.json()
            for m in data.get("models", []):
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                model_id = m.get("name", "").removeprefix("models/")
                if not model_id:
                    continue
                modelos.append((model_id, f"[Gemini] {model_id}"))
            page_token = data.get("nextPageToken", "")
            if not page_token:
                break
        modelos.sort(key=lambda t: t[0])
        return modelos
