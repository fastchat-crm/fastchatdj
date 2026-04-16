"""Provider para Google Gemini (Generative AI)."""
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    name = "gemini"

    def default_model(self) -> str:
        return "gemini-2.5-flash"

    def get_llm(self, apikey, model_name, max_output_tokens, temperature=0.1):
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=apikey,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )

    def get_embeddings(self, apikey):
        return GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=apikey,
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
