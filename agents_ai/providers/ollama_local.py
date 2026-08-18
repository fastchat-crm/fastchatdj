"""Provider para Ollama local (modelos auto-hospedados, endpoint OpenAI-compatible).

Apunta a un despliegue propio de Ollama (por defecto http://localhost:11434) vía la
`base_url` de la API Key. A diferencia de Ollama Cloud (providers/ollama.py), sí ofrece
embeddings locales (nomic-embed-text) para FAISS.
"""
from .base import EMBEDDINGS_TIMEOUT_SEGUNDOS, EMBEDDINGS_MAX_RETRIES
from .openai_compat import OpenAICompatProvider


class OllamaLocalProvider(OpenAICompatProvider):
    name = "ollama_local"
    default_base_url = "http://localhost:11434"

    def default_model(self) -> str:
        return "llama3.1"

    def get_embeddings(self, apikey, base_url=None):
        from langchain_community.embeddings import OpenAIEmbeddings
        kwargs = dict(
            model="nomic-embed-text",
            openai_api_key=(apikey or 'ollama'),
            openai_api_base=self._resolver_base_url(base_url),
            request_timeout=EMBEDDINGS_TIMEOUT_SEGUNDOS,
            max_retries=EMBEDDINGS_MAX_RETRIES,
        )
        try:
            return OpenAIEmbeddings(check_embedding_ctx_length=False, **kwargs)
        except TypeError:
            return OpenAIEmbeddings(**kwargs)
