from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import HumanMessage, AIMessage
from langchain.memory import ConversationBufferMemory

from whatsapp.models import ConversacionWhatsApp
from .memoria_django import DjangoChatMessageHistory

import os
import unicodedata
import re
import json
from datetime import datetime


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
        self.conversacion: ConversacionWhatsApp = conversacion
        self.memory = self._get_memory()
        self.prompt_template_text = prompt_template_text
        self.listas_memoria = {}
        self._cargar_listas_desde_memoria()

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

    def _cargar_listas_desde_memoria(self):
        if not self.memory:
            return
        for mensaje in self.memory.chat_memory.messages:
            if isinstance(mensaje, AIMessage) and mensaje.content.startswith("LISTA_GUARDADA:"):
                try:
                    data = json.loads(mensaje.content.replace("LISTA_GUARDADA:", ""))
                    self.listas_memoria.update(data)
                except:
                    pass

    def _guardar_listas_en_memoria(self):
        if not self.memory or not self.listas_memoria:
            return
        data_json = json.dumps(self.listas_memoria, ensure_ascii=False)
        self.memory.chat_memory.add_ai_message(f"LISTA_GUARDADA:{data_json}")

    def _extraer_contexto_reciente(self, cantidad_turnos=3):
        if not self.memory:
            return ""

        mensajes = self.memory.chat_memory.messages[-(cantidad_turnos * 2):]  # turnos = user+ai
        historial = []
        for msg in mensajes:
            if isinstance(msg, HumanMessage):
                historial.append(f"Usuario: {msg.content}")
            elif isinstance(msg, AIMessage):
                historial.append(f"Asistente: {msg.content}")
        return "\n".join(historial)

    def consultar_con_listas(self, pregunta, descripcion_agente=''):
        consulta = self.consultar(pregunta, descripcion_agente)
        resultado_lista = ''
        try:
            comando_data = json.loads(consulta)
            accion = comando_data.get("accion")
            lista = comando_data.get("nombre_lista", "pedido")
            item = comando_data.get("item", "")

            if accion == "agregar_item":
                if lista not in self.listas_memoria:
                    self.listas_memoria[lista] = {"items": []}
                if item not in self.listas_memoria[lista]["items"]:
                    self.listas_memoria[lista]["items"].append(item)
                    self._guardar_listas_en_memoria()
                    resultado_lista = f"📝 Agregado a tu pedido: {item}"
                else:
                    resultado_lista = f"ℹ️ Ya está en tu pedido: {item}"

            if accion == "mostrar_lista":
                if lista not in self.listas_memoria or not self.listas_memoria[lista]["items"]:
                    resultado_lista = "📝 Tu pedido está vacío."
                items = self.listas_memoria[lista]["items"]
                listado = "\n".join([f"{i+1}. {x}" for i, x in enumerate(items)])
                resultado_lista = f"📋 Tu pedido:\n{listado}\n\nTotal: {len(items)} ítems"

        except Exception as ex:
            print(ex)
        if resultado_lista:
            if self.memory:
                self.memory.chat_memory.add_user_message(pregunta)
                self.memory.chat_memory.add_ai_message(resultado_lista)
        return resultado_lista or consulta

    def consultar(self, pregunta, descripcion_agente=''):
        pregunta_normalizada = normalizar_texto(pregunta)
        contexto_previo = self._extraer_tema_previos_turnos()

        if self.memory and len(self.memory.chat_memory.messages) == 0:
            saludo = self.llm.invoke(f"""¿El siguiente texto es solo un saludo?: "{pregunta}" 
Responde exactamente "ES_SALUDO" o "NO_ES_SALUDO".""").content.strip()
            if saludo == "ES_SALUDO":
                bienvenida = "Hola 👋, ¿en qué puedo ayudarte?"
                if self.memory:
                    self.memory.chat_memory.add_user_message(pregunta)
                    self.memory.chat_memory.add_ai_message(bienvenida)
                return bienvenida

        reformulada = self.llm.invoke(
            f"Reescribe esta pregunta para hacerla más efectiva para búsqueda en una base de conocimiento: {pregunta}"
        ).content.strip()

        docs = self.retriever.get_relevant_documents(reformulada)
        contexto = "\n\n".join({d.page_content for d in docs})

        if not contexto.strip():
            return "No tengo esa información."

        prompt_template = PromptTemplate.from_template(f'{self.prompt_template_text}\n')
        prompt_final = prompt_template.format(
            question=f'{pregunta} or {reformulada}',
            context=contexto,
            descripcion_agente=descripcion_agente,
            contexto_extra=contexto_previo
        )

        try:
            respuesta = self.llm.invoke(prompt_final).content
        except Exception:
            respuesta = "Ocurrió un error generando la respuesta."

        if self.memory:
            self.memory.chat_memory.add_user_message(pregunta)
            self.memory.chat_memory.add_ai_message(respuesta)

        return respuesta

    def _extraer_tema_previos_turnos(self):
        if not self.memory:
            return ""
        mensajes = self.memory.chat_memory.messages
        ultimos = mensajes[-4:] if len(mensajes) >= 4 else mensajes
        partes = []
        for i in range(0, len(ultimos), 2):
            if i + 1 < len(ultimos):
                h = ultimos[i]
                a = ultimos[i + 1]
                if isinstance(h, HumanMessage) and isinstance(a, AIMessage):
                    partes.append(f"Usuario: {h.content[:100]}...")
                    partes.append(f"Asistente: {a.content[:150]}...")
        return "Conversación previa:\n" + "\n".join(partes) + "\n\n" if partes else ""