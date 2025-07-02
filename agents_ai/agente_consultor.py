from langchain.chains import RetrievalQAWithSourcesChain
from langchain.chains.conversational_retrieval.base import ConversationalRetrievalChain
from langchain_community.chat_models import ChatOpenAI
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
import os


class AgenteConsultor:
    def __init__(self, vectorstore_path, provider, apikey, model_name=None):
        self.provider = provider == 2 and 'gemini' or provider == 3 and 'openai'
        self.apikey = apikey
        self.model_name = model_name or self.default_model()
        self.vectorstore_path = vectorstore_path
        self.embeddings = self._get_embeddings()
        self.llm = self._get_llm()
        self.retriever = self._load_vectorstore().as_retriever()

    def default_model(self):
        return self.provider == "openai" and "gpt-4"or "gemini-2.5-pro"

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

    def _load_vectorstore(self):
        if not os.path.exists(self.vectorstore_path):
            raise FileNotFoundError(f"No se encontró el vectorstore en {self.vectorstore_path}")
        return FAISS.load_local(self.vectorstore_path, self.embeddings, allow_dangerous_deserialization=True)

    def consultar(self, pregunta):
        QA_PROMPT = PromptTemplate.from_template("""
        Eres un asistente útil que responde exclusivamente con base en los documentos proporcionados.
        Debes responder como mensaje de whatsapp.

        Si no encuentras la respuesta en los documentos, responde únicamente:
        "No tengo esa información".

        Pregunta: {question}
        ====================
        {context}
        ====================
        Respuesta:
        """)
        chain = ConversationalRetrievalChain.from_llm(
            llm=self.llm,
            retriever=self.retriever,
            combine_docs_chain_kwargs={"prompt": QA_PROMPT},
            return_source_documents=True
        )
        result = chain.invoke({"question": pregunta, "chat_history": []})
        print("result", result)
        respuesta = result.get("answer", "")
        documentos = result.get("source_documents", [])

        detalles_usados = {d.metadata.get("detalle_id") for d in documentos if "detalle_id" in d.metadata}
        return respuesta, list(detalles_usados)
