"""Provider para Huawei Cloud MaaS (ModelArts Studio, endpoint OpenAI-compatible).

Huawei MaaS expone modelos (DeepSeek, Qwen, GLM, etc.) detrás de un endpoint
por región/despliegue — no hay base_url universal, por eso es obligatorio
configurarla en la API Key (campo Base URL).
"""
from .openai_compat import OpenAICompatProvider


class HuaweiProvider(OpenAICompatProvider):
    name = "huawei"
    default_base_url = ""

    def default_model(self) -> str:
        return "DeepSeek-V3"

    def get_embeddings(self, apikey, base_url=None):
        raise NotImplementedError(
            "Huawei MaaS no expone embeddings vía este conector. "
            "Configura una API Key adicional con Gemini u OpenAI para el vectorstore."
        )
