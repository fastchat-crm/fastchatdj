from langchain_community.chat_models import ChatOpenAI
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings


class AgenteResumidor:
    def __init__(self, provider, apikey, model_name=None, conversacion=None):
        self.provider = provider == 2 and 'gemini' or provider == 3 and 'openai'
        self.apikey = apikey
        self.model_name = model_name or self.default_model()
        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.memoria_cruda = conversacion and conversacion.cargar_memoria() or []
        self.chat_history = self.convertir_historial_a_messages(self.memoria_cruda)
        self.conversacion = conversacion

    def default_model(self):
        return self.provider == "openai" and "gpt-4" or "gemini-2.5-pro"

    def _get_embeddings(self):
        if self.provider == "openai":
            return OpenAIEmbeddings(openai_api_key=self.apikey)
        elif self.provider == "gemini":
            return GoogleGenerativeAIEmbeddings(
                model="models/embedding-001", google_api_key=self.apikey
            )
        else:
            raise ValueError("Proveedor de embedding no soportado")

    def _get_llm(self):
        if self.provider == "openai":
            return ChatOpenAI(model_name=self.model_name, openai_api_key=self.apikey)
        elif self.provider == "gemini":
            return ChatGoogleGenerativeAI(model=self.model_name, google_api_key=self.apikey)
        else:
            raise ValueError("Proveedor de LLM no soportado")

    def convertir_historial_a_messages(self, historial):
        """
        Recibe: lista de pares [usuario, respuesta]
        Devuelve: lista de HumanMessage y AIMessage para LangChain
        """
        messages = []
        for user, ai in historial:
            messages.append(HumanMessage(content=user))
            messages.append(AIMessage(content=ai))
        return messages

    def resumir(self):
        texto_chat = ''
        if not self.chat_history:
            return texto_chat
        for msg in self.chat_history:
            if isinstance(msg, HumanMessage):
                texto_chat += f"Usuario: {msg.content}\n"
            else:
                texto_chat += f"Asistente: {msg.content}\n"
        prompt = f"""Resume de forma clara y breve la siguiente conversación entre un usuario y un asistente:
        {texto_chat}
        Resumen:"""

        return self.llm.invoke(prompt).content