import os
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import (
    PyPDFLoader, CSVLoader, JSONLoader, UnstructuredExcelLoader
)
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.docstore.document import Document


class VectorStoreManager:
    def __init__(self, storage_dir, provider: str, apikey: str):
        self.storage_dir = storage_dir
        self.provider = provider.lower()
        self.apikey = apikey

        if self.provider == "openai":
            self.embeddings = OpenAIEmbeddings(openai_api_key=self.apikey)
        elif self.provider == "gemini":
            self.embeddings = GoogleGenerativeAIEmbeddings(
                model="models/embedding-001", google_api_key=self.apikey
            )
        else:
            raise ValueError("Proveedor de embedding no soportado: use 'openai' o 'gemini'")

        os.makedirs(self.storage_dir, exist_ok=True)

    def get_loader(self, file_path):
        if file_path.endswith('.pdf'):
            return PyPDFLoader(file_path)
        elif file_path.endswith('.csv'):
            return CSVLoader(file_path)
        elif file_path.endswith('.json'):
            return JSONLoader(file_path)
        elif file_path.endswith('.xlsx'):
            return UnstructuredExcelLoader(file_path)
        else:
            raise ValueError("Formato de archivo no soportado")

    def build_from_string(self, text: str, metadata: dict = None):
        metadata = metadata or {}
        doc = Document(page_content=text, metadata=metadata)
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        docs = splitter.split_documents([doc])
        return docs

    def load_and_split(self, file_path, metadata=None):
        loader = self.get_loader(file_path)
        docs = loader.load()

        for d in docs:
            d.metadata.update(metadata or {})

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        return splitter.split_documents(docs)

    def build_and_save(self, docs, nombre_directorio):
        vs = FAISS.from_documents(docs, self.embeddings)
        vector_path = os.path.join(self.storage_dir, nombre_directorio)
        vs.save_local(vector_path)
        return vector_path

    def vectorstore_exists(self, nombre_directorio):
        faiss_path = os.path.join(self.storage_dir, nombre_directorio)
        return os.path.exists(os.path.join(faiss_path, "index.faiss"))

    def cargar_vectorstore(self, nombre_directorio):
        path = os.path.join(self.storage_dir, nombre_directorio)
        return FAISS.load_local(path, self.embeddings)