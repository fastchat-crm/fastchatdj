"""Provider para DeepSeek (API cloud OpenAI-compatible)."""
from .openai_compat import OpenAICompatProvider


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"
    default_base_url = "https://api.deepseek.com"

    def default_model(self) -> str:
        return "deepseek-chat"

    def get_embeddings(self, apikey, base_url=None):
        raise NotImplementedError(
            "DeepSeek no ofrece API de embeddings. "
            "Configura una API Key adicional con Gemini u OpenAI para el vectorstore "
            "(el agente puede usar DeepSeek para chat y otra key para embeddings)."
        )
