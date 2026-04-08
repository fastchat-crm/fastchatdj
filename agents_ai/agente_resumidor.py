import json
import re
from langchain_community.chat_models import ChatOpenAI
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from .memoria_django import DjangoChatMessageHistory


class AgenteResumidor:
    def __init__(self, provider, apikey, model_name=None, conversacion=None):
        self.provider = provider == 2 and 'gemini' or provider == 3 and 'openai'
        self.apikey = apikey
        self.model_name = model_name or self.default_model()
        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.conversacion = conversacion
        self._historia = (
            DjangoChatMessageHistory(session_id=str(conversacion.id))
            if conversacion else None
        )

    def default_model(self):
        return "gpt-4" if self.provider == "openai" else "gemini-2.5-flash"

    def _get_embeddings(self):
        if self.provider == "gemini":
            return GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004", google_api_key=self.apikey
            )
        elif self.provider == "openai":
            return OpenAIEmbeddings(openai_api_key=self.apikey)
        raise ValueError("Proveedor de embedding no soportado")

    def _get_llm(self):
        if self.provider == "gemini":
            return ChatGoogleGenerativeAI(model=self.model_name, google_api_key=self.apikey)
        elif self.provider == "openai":
            from langchain_community.chat_models import ChatOpenAI
            return ChatOpenAI(model_name=self.model_name, openai_api_key=self.apikey)
        raise ValueError("Proveedor de LLM no soportado")

    def _get_texto_chat(self) -> str:
        if not self._historia:
            return ""
        messages = self._historia.messages
        lines = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                lines.append(f"Cliente: {msg.content}")
            elif isinstance(msg, AIMessage):
                lines.append(f"Asistente: {msg.content}")
        return "\n".join(lines)

    def resumir(self) -> str:
        texto_chat = self._get_texto_chat()
        if not texto_chat:
            return ""
        prompt = (
            "Resume de forma clara, breve y cronológica la siguiente conversación "
            "entre un cliente y un asistente:\n\n"
            f"{texto_chat}\n\nResumen:"
        )
        return self.llm.invoke(prompt).content

    def analizar_sentimiento(self) -> dict:
        """Analiza el tono/sentimiento de la conversación del cliente.

        Returns dict:
            {
              "sentimiento": "positiva" | "neutral" | "tibia" | "pasiva" | "negativa" | "agresiva" | "muy_positiva",
              "puntuacion": 1-10,
              "resumen": "texto extendido incluyendo análisis de tono"
            }
        """
        texto_chat = self._get_texto_chat()
        if not texto_chat:
            return {"sentimiento": "", "puntuacion": None, "resumen": ""}

        prompt = f"""Analiza la siguiente conversación entre un cliente y un asistente de WhatsApp.

CONVERSACIÓN:
{texto_chat}

Responde ÚNICAMENTE con un JSON válido con esta estructura (sin texto adicional antes o después):
{{
  "sentimiento": "<una de: muy_positiva | positiva | neutral | tibia | pasiva | negativa | agresiva>",
  "puntuacion": <número entero del 1 al 10, donde 10=muy positivo, 1=muy agresivo/negativo>,
  "resumen": "<resumen conciso de 2-4 oraciones que incluya: qué consultó el cliente, cómo fue atendido, y cómo fue el tono general de la conversación>"
}}

Criterios de sentimiento:
- muy_positiva: cliente muy satisfecho, agradecido, elogios
- positiva: cliente satisfecho, tono cordial
- neutral: tono informativo, sin carga emocional clara
- tibia: cliente poco comprometido, respuestas monosílabas, poca interacción
- pasiva: cliente que no responde o abandona sin resolver su problema
- negativa: cliente insatisfecho, queja clara pero sin agresividad
- agresiva: cliente frustrado, usa lenguaje fuerte, exige, insulta o presiona"""

        try:
            raw = self.llm.invoke(prompt).content.strip()
            # Extraer JSON aunque haya texto envolvente
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
                # Validar claves y tipos
                sentimientos_validos = {'muy_positiva', 'positiva', 'neutral', 'tibia', 'pasiva', 'negativa', 'agresiva'}
                sentimiento = result.get('sentimiento', 'neutral')
                if sentimiento not in sentimientos_validos:
                    sentimiento = 'neutral'
                puntuacion = result.get('puntuacion')
                try:
                    puntuacion = max(1, min(10, int(puntuacion)))
                except (TypeError, ValueError):
                    puntuacion = 5
                return {
                    "sentimiento": sentimiento,
                    "puntuacion": puntuacion,
                    "resumen": result.get('resumen', ''),
                }
        except Exception:
            pass
        return {"sentimiento": "neutral", "puntuacion": 5, "resumen": ""}