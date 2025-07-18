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
    def __init__(self, vectorstore_path, provider, apikey, model_name=None, conversacion=None, prompt_template_text=''):
        self.provider = provider == 2 and 'gemini' or provider == 3 and 'openai'
        self.apikey = apikey
        self.model_name = model_name or self.default_model()
        self.vectorstore_path = vectorstore_path
        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.vectorstore = self._load_vectorstore()
        self.retriever = self.vectorstore.as_retriever(search_type="mmr", search_kwargs={"k": 30, "lambda_mult": 0.7})
        self.conversacion = conversacion
        self.memory = self._get_memory()
        self.prompt_template_text = prompt_template_text

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

    def _extraer_tema_previos_turnos(self):
        if not self.memory:
            return ""

        mensajes = self.memory.chat_memory.messages
        if len(mensajes) < 2:
            return ""

        # Obtener los últimos 2-3 intercambios para mejor contexto
        ultimos_mensajes = mensajes[-4:] if len(mensajes) >= 4 else mensajes
        
        contexto_previo = []
        for i in range(0, len(ultimos_mensajes), 2):
            if i + 1 < len(ultimos_mensajes):
                usuario_msg = ultimos_mensajes[i]
                ai_msg = ultimos_mensajes[i + 1]
                if isinstance(usuario_msg, HumanMessage) and isinstance(ai_msg, AIMessage):
                    contexto_previo.append(f"Usuario: {usuario_msg.content[:100]}...")
                    contexto_previo.append(f"Asistente: {ai_msg.content[:150]}...")

        if contexto_previo:
            return f"Conversación previa:\n" + "\n".join(contexto_previo) + "\n\n"
        
        return ""

    def consultar(self, pregunta, descripcion_agente=''):
        pregunta_normalizada = normalizar_texto(pregunta)

        reformulada = self.llm.invoke(
            f"Reescribe formalmente y corrige errores de la siguiente pregunta (SI ES SÓLO UN SALUDO, solo responde ES_SALUDO): {pregunta_normalizada}"
        ).content

        if 'ES_SALUDO' in reformulada:
            return "Hola 👋, ¿en qué puedo ayudarte?"

        docs_orig = self.retriever.get_relevant_documents(pregunta)
        docs_norm = self.retriever.get_relevant_documents(pregunta_normalizada)
        docs_ref = self.retriever.get_relevant_documents(reformulada)
        contexto = "\n\n".join({d.page_content for d in docs_orig + docs_norm + docs_ref})

        if not contexto.strip():
            return "No tengo esa información."

        # Obtener contexto de la conversación anterior
        contexto_extra = self._extraer_tema_previos_turnos()

        prompt_template = PromptTemplate.from_template(f'{self.prompt_template_text}\n')

        prompt_final = prompt_template.format(
            question=f'{pregunta} OR {reformulada}',  # Usar pregunta original, no reformulada
            context=contexto,
            descripcion_agente=descripcion_agente,
            contexto_extra=contexto_extra
        )

        respuesta = self.llm.invoke(prompt_final).content

        # Guardar en memoria la pregunta ORIGINAL y la respuesta
        if self.memory:
            self.memory.chat_memory.add_user_message(f'{pregunta} OR {reformulada}')
            self.memory.chat_memory.add_ai_message(respuesta)

        return respuesta