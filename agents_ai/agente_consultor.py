from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import HumanMessage, AIMessage
from langchain.memory import ConversationBufferMemory
from .memoria_django import DjangoChatMessageHistory

import os
import unicodedata
import re


def normalizar_texto(texto):
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
    texto = re.sub(r'[^a-zA-Z0-9\s]', '', texto)
    return texto.lower()


class AgenteConsultor:
    def __init__(self, vectorstore_path, provider, apikey, model_name=None, conversacion=None):
        self.provider = provider == 2 and 'gemini' or provider == 3 and 'openai'
        self.apikey = apikey
        self.model_name = model_name or self.default_model()
        self.vectorstore_path = vectorstore_path
        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.vectorstore = self._load_vectorstore()
        self.retriever = self.vectorstore.as_retriever(search_type="mmr", search_kwargs={"k": 15, "lambda_mult": 0.7})
        self.conversacion = conversacion
        self.memory = self._get_memory()

    def default_model(self):
        return "gemini-1.5-pro" if self.provider == "gemini" else "gpt-4"

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

    def _load_vectorstore(self):
        if not os.path.exists(self.vectorstore_path):
            raise FileNotFoundError(f"No se encontró el vectorstore en {self.vectorstore_path}")
        return FAISS.load_local(self.vectorstore_path, self.embeddings, allow_dangerous_deserialization=True)

    def _get_memory(self):
        if not self.conversacion:
            return None
        return ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
            chat_memory=DjangoChatMessageHistory(session_id=str(self.conversacion.id))
        )

    def consultar(self, pregunta, descripcion_agente=''):
        pregunta_normalizada = normalizar_texto(pregunta)
        reformulada = self.llm.invoke(
            f"Reescribe formalmente y corrige errores de la siguiente pregunta: {pregunta_normalizada}"
        ).content

        docs_orig = self.retriever.get_relevant_documents(pregunta)
        docs_norm = self.retriever.get_relevant_documents(pregunta_normalizada)
        docs_ref = self.retriever.get_relevant_documents(reformulada)
        contexto = "\n\n".join({d.page_content for d in docs_orig + docs_norm + docs_ref})

        mensajes_previos = self.memory.chat_memory.messages if self.memory else []
        es_primera_interaccion = len(mensajes_previos) < 2

        ultimo_turno_usuario = None
        for m in reversed(mensajes_previos):
            if isinstance(m, HumanMessage):
                ultimo_turno_usuario = m.content
                break

        prompt_template = PromptTemplate.from_template("""
    Eres un asistente conversacional amable y profesional que responde como si estuviera en WhatsApp.

    Reglas:
    - Usa un tono natural, directo y claro. Agrega emojis solo si ayudan a dar calidez o comprensión (sin exagerar).
    - Si el usuario pregunta qué haces o saluda y es el primer mensaje, responde cordialmente. En el resto, no saludes de nuevo.
    - Mantén el contexto de lo que el usuario ya dijo. No repitas la pregunta ni reinicies el flujo de conversación.
    - Si el usuario pidió algo antes, continúa como si lo recordaras.
    - Si no encuentras la información, di: "No tengo esa información".
    - Ejemplo:
      Usuario: También quiero una pizza  
      Respuesta: Perfecto, agrego una pizza a tu orden.

    Pregunta: {question}
    Contexto:
    {context}
    Respuesta:
    """)

        prompt_base = prompt_template.format(
            question=reformulada,
            context=contexto,
            descripcion_agente=descripcion_agente
        )

        if ultimo_turno_usuario:
            contexto_extra = f"(Antes, el usuario dijo: \"{ultimo_turno_usuario}\")\n\n"
        else:
            contexto_extra = ""

        prompt_final = contexto_extra + prompt_base

        if not es_primera_interaccion:
            prompt_final = prompt_final.replace("Hola", "").replace("👋", "").strip()

        respuesta = self.llm.invoke(prompt_final).content

        if self.memory:
            self.memory.chat_memory.add_user_message(pregunta)
            self.memory.chat_memory.add_ai_message(respuesta)

        return respuesta