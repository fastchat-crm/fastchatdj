from langchain_community.chat_models import ChatOpenAI
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain.memory import ConversationBufferMemory
from .memoria_django import DjangoChatMessageHistory


class AgenteResumidor:
    def __init__(self, provider, apikey, model_name=None, conversacion=None):
        self.provider = provider == 2 and 'gemini' or provider == 3 and 'openai'
        self.apikey = apikey
        self.model_name = model_name or self.default_model()
        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.conversacion = conversacion
        self.memory = self._get_memory()

    def default_model(self):
        return "gpt-4" if self.provider == "openai" else "gemini-1.5-flash"

    def _get_embeddings(self):
        if self.provider == "gemini":
            return GoogleGenerativeAIEmbeddings(
                model="models/embedding-001", google_api_key=self.apikey
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

    def _get_memory(self):
        if not self.conversacion:
            return None
        return ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
            chat_memory=DjangoChatMessageHistory(session_id=str(self.conversacion.id))
        )

    def resumir(self):
        if not self.memory:
            return ""

        messages = self.memory.chat_memory.messages
        if not messages:
            return ""

        texto_chat = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                texto_chat += f"Usuario: {msg.content}\n"
            elif isinstance(msg, AIMessage):
                texto_chat += f"Asistente: {msg.content}\n"

        prompt = f"""Resume de forma clara, breve y cronológica la siguiente conversación entre un usuario y un asistente:
        {texto_chat}
        Resumen:"""

        return self.llm.invoke(prompt).content