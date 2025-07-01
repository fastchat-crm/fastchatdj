import os
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import (
    PyPDFLoader, CSVLoader, JSONLoader, UnstructuredExcelLoader
)
from langchain_community.chat_models import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import ConversationalRetrievalChain
from langchain.prompts import PromptTemplate
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.callbacks.base import BaseCallbackHandler
from PyPDF2 import PdfReader

# === Setea API Keys ===
os.environ["OPENAI_API_KEY"] = "sk-..."
os.environ["GOOGLE_API_KEY"] = "AIzaSyBXa3ys3DHgDrbymnOuJ5pFP8KgwIwp6QM"

# === Callback para streaming ===
class StreamingCallbackHandler(BaseCallbackHandler):
    def __init__(self):
        self.texto_completo = ""

    def on_llm_new_token(self, token: str, **kwargs):
        print(token, end='', flush=True)
        self.texto_completo += token

# === Verificar si el PDF necesita OCR ===
def requiere_ocr(path_pdf, min_caracteres=10):
    try:
        reader = PdfReader(path_pdf)
        texto_total = ""
        for page in reader.pages:
            texto = page.extract_text()
            if texto:
                texto_total += texto
            if len(texto_total) >= min_caracteres:
                return False
        return True
    except Exception:
        return True

# === Cargar documento ===
def cargar_documento(path):
    if path.endswith(".pdf"):
        if requiere_ocr(path):
            raise ValueError("⚠️ El PDF parece escaneado y requiere OCR. OCR no implementado aún.")
        loader = PyPDFLoader(path)
    elif path.endswith(".csv"):
        loader = CSVLoader(path)
    elif path.endswith(".json"):
        loader = JSONLoader(path)
    elif path.endswith(".xlsx"):
        loader = UnstructuredExcelLoader(path)
    else:
        raise ValueError("Formato no soportado.")
    return loader.load()

# === Crear vectorstore ===
def crear_vectorstore(documentos, usar_openai=True):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = splitter.split_documents(documentos)

    if usar_openai:
        embeddings = OpenAIEmbeddings()
    else:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

    return FAISS.from_documents(docs, embeddings)

# === Crear agente con control estricto de contexto ===
QA_PROMPT = PromptTemplate.from_template("""
Eres un asistente útil que responde exclusivamente con base en los documentos proporcionados.

Si no encuentras la respuesta en los documentos, responde únicamente:
"No tengo esa información".

Pregunta: {question}
====================
{context}
====================
Respuesta:
""")

def crear_agente_qa(vectorstore, usar_openai=True, streaming=False, callback_handler=None):
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})

    if usar_openai:
        llm = ChatOpenAI(
            model_name="gpt-4",
            streaming=streaming,
            callbacks=[callback_handler] if callback_handler else None,
        )
    else:
        llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-pro",
            streaming=streaming,
            callbacks=[callback_handler] if callback_handler else None,
        )

    qa_chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        combine_docs_chain_kwargs={"prompt": QA_PROMPT},
        return_source_documents=False
    )

    return qa_chain

# === Uso principal ===
if __name__ == "__main__":
    archivo = "C:\\Users\\JASMANY\\Downloads\\PAGO_VELEZ_merged.pdf"

    try:
        docs = cargar_documento(archivo)
        print(f"📄 Documentos cargados: {len(docs)}")
    except ValueError as e:
        print(e)
        exit()

    vs = crear_vectorstore(docs, usar_openai=False)

    streaming = True
    callback = StreamingCallbackHandler() if streaming else None

    agente = crear_agente_qa(vs, usar_openai=False, streaming=streaming, callback_handler=callback)

    pregunta = "¿De qué trata este documento?"
    print("\n🧠 Respuesta:")
    result = agente.invoke({"question": pregunta, "chat_history": []})

    if not streaming:
        print(result["answer"])
    elif callback:
        print("\n\n🔎 Texto completo capturado:")
        print(callback.texto_completo, result)
