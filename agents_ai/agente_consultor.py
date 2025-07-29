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
        
        # Sistema de listas en memoria
        self.listas_memoria = {}
        self.preguntas_frecuentes = []
        self._cargar_listas_desde_memoria()
        
        # Comandos disponibles para el manejo de listas
        self.comandos_lista = {
            'crear_lista': self._crear_lista,
            'agregar_item': self._agregar_item_lista,
            'mostrar_lista': self._mostrar_lista,
            'eliminar_item': self._eliminar_item_lista,
            'limpiar_lista': self._limpiar_lista,
            'listar_todas': self._listar_todas_las_listas,
        }

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
        # Primero verificar si es un comando de lista
        resultado_lista = self._procesar_comando_lista_ia(pregunta)
        if resultado_lista:
            return resultado_lista
            
        pregunta_normalizada = normalizar_texto(pregunta)
        
        contexto_previo = self._extraer_tema_previos_turnos()
        
        # Solo verificar si es saludo cuando realmente es el primer mensaje de la conversación completa
        if self.memory and len(self.memory.chat_memory.messages) == 0:
            prompt_saludo = f"""Analiza si el siguiente texto es ÚNICAMENTE un saludo sin ninguna pregunta específica.
            
Texto: "{pregunta}"

Responde EXACTAMENTE "ES_SALUDO" si es solo un saludo básico (como "hola", "buenos días", "hi", etc.).
Responde "NO_ES_SALUDO" si contiene alguna pregunta o solicitud específica, aunque incluya un saludo."""

            respuesta_saludo = self.llm.invoke(prompt_saludo).content.strip()
            
            if respuesta_saludo == "ES_SALUDO":
                mensaje_bienvenida = "Hola 👋, ¿en qué puedo ayudarte?"
                if self.conversacion and hasattr(self.conversacion, 'contacto') and hasattr(self.conversacion.contacto, 'sesion'):
                    mensaje_bienvenida = self.conversacion.contacto.sesion.mensaje_bienvenida or mensaje_bienvenida
                
                # Guardar el saludo en memoria para mantener el historial
                if self.memory:
                    self.memory.chat_memory.add_user_message(pregunta)
                    self.memory.chat_memory.add_ai_message(mensaje_bienvenida)
                
                return mensaje_bienvenida

        # Reformular la pregunta para mejorar la búsqueda
        reformulada = self.llm.invoke(
            f"Reescribe y mejora la siguiente pregunta para una búsqueda más efectiva, mantén el contexto y significado original: {pregunta}"
        ).content

        docs_orig = self.retriever.get_relevant_documents(pregunta)
        docs_norm = self.retriever.get_relevant_documents(pregunta_normalizada)
        docs_ref = self.retriever.get_relevant_documents(reformulada)
        contexto = "\n\n".join({d.page_content for d in docs_orig + docs_norm + docs_ref})

        if not contexto.strip():
            return "No tengo esa información."

        # Agregar información de listas al contexto si es relevante
        contexto_listas = self._obtener_contexto_listas(pregunta)
        contexto_extra = contexto_previo + contexto_listas

        prompt_template = PromptTemplate.from_template(f'{self.prompt_template_text}\n')

        prompt_final = prompt_template.format(
            question=f'{pregunta} or {reformulada}',
            context=contexto,
            descripcion_agente=descripcion_agente,
            contexto_extra=contexto_extra
        )

        respuesta = self.llm.invoke(prompt_final).content

        # Registrar la pregunta en el historial de preguntas frecuentes
        self._registrar_pregunta(pregunta)

        if self.memory:
            self.memory.chat_memory.add_user_message(f'{pregunta} or {reformulada}')
            self.memory.chat_memory.add_ai_message(respuesta)

        return respuesta

        prompt_final = prompt_template.format(
            question=f'{pregunta} or {reformulada}',
            context=contexto,
            descripcion_agente=descripcion_agente,
            contexto_extra=contexto_extra
        )

        respuesta = self.llm.invoke(prompt_final).content

        # Registrar la pregunta en el historial de preguntas frecuentes
        self._registrar_pregunta(pregunta)

        if self.memory:
            self.memory.chat_memory.add_user_message(f'{pregunta} or {reformulada}')
            self.memory.chat_memory.add_ai_message(respuesta)

        return respuesta

    def _obtener_contexto_listas(self, pregunta):
        """Obtener contexto relevante de las listas para la consulta"""
        if not self.listas_memoria:
            return ""
        
        contexto_listas = "\n\n📋 **Listas disponibles:**\n"
        for nombre, datos in self.listas_memoria.items():
            if any(palabra in pregunta.lower() for palabra in [nombre.lower(), 'lista', 'menu']):
                items_texto = ', '.join(datos['items'][:5])  # Mostrar solo los primeros 5 items
                if len(datos['items']) > 5:
                    items_texto += f" (y {len(datos['items']) - 5} más)"
                contexto_listas += f"• {nombre}: {items_texto}\n"
        
        return contexto_listas if contexto_listas != "\n\n📋 **Listas disponibles:**\n" else ""

    def _cargar_listas_desde_memoria(self):
        """Cargar listas existentes desde la memoria de la conversación"""
        if not self.memory:
            return
            
        # Buscar listas guardadas en mensajes anteriores
        for mensaje in self.memory.chat_memory.messages:
            if isinstance(mensaje, AIMessage) and mensaje.content.startswith("LISTA_GUARDADA:"):
                try:
                    data = json.loads(mensaje.content.replace("LISTA_GUARDADA:", ""))
                    self.listas_memoria.update(data)
                except:
                    pass

    def _guardar_listas_en_memoria(self):
        """Guardar las listas actuales en la memoria de la conversación"""
        if not self.memory or not self.listas_memoria:
            return
            
        data_json = json.dumps(self.listas_memoria, ensure_ascii=False)
        self.memory.chat_memory.add_ai_message(f"LISTA_GUARDADA:{data_json}")

    def _registrar_pregunta(self, pregunta):
        """Registrar pregunta en el historial de preguntas frecuentes"""
        pregunta_normalizada = normalizar_texto(pregunta)
        
        # Evitar duplicados y preguntas muy cortas
        if (len(pregunta_normalizada) > 5 and 
            pregunta_normalizada not in [normalizar_texto(p.get('pregunta', '')) for p in self.preguntas_frecuentes]):
            
            self.preguntas_frecuentes.append({
                'pregunta': pregunta,
                'fecha': datetime.now().isoformat(),
                'normalizada': pregunta_normalizada
            })
            
            # Mantener solo las últimas 50 preguntas
            if len(self.preguntas_frecuentes) > 50:
                self.preguntas_frecuentes = self.preguntas_frecuentes[-50:]

    def _detectar_comando_lista(self, texto):
        """Detectar si el texto contiene un comando para manejar listas"""
        texto_lower = texto.lower()
        
        # Patrones para detectar comandos de lista
        patrones = {
            'crear_lista': ['crear lista', 'nueva lista', 'hacer lista de', 'lista de'],
            'agregar_item': ['agregar a', 'añadir a', 'incluir en', 'poner en'],
            'mostrar_lista': ['mostrar lista', 'ver lista', 'lista de', 'qué hay en'],
            'eliminar_item': ['quitar de', 'eliminar de', 'borrar de', 'remover de'],
            'limpiar_lista': ['limpiar lista', 'borrar lista', 'vaciar lista'],
            'listar_todas': ['todas las listas', 'qué listas', 'mostrar listas']
        }
        
        for comando, palabras_clave in patrones.items():
            if any(palabra in texto_lower for palabra in palabras_clave):
                return comando
        
        return None

    def _crear_lista(self, nombre_lista, items=None):
        """Crear una nueva lista"""
        if items is None:
            items = []
        
        self.listas_memoria[nombre_lista] = {
            'items': items,
            'fecha_creacion': datetime.now().isoformat(),
            'fecha_modificacion': datetime.now().isoformat()
        }
        
        self._guardar_listas_en_memoria()
        return f"✅ Lista '{nombre_lista}' creada exitosamente."

    def _agregar_item_lista(self, nombre_lista, item):
        """Agregar un item a una lista existente"""
        if nombre_lista not in self.listas_memoria:
            return f"❌ La lista '{nombre_lista}' no existe. ¿Quieres que la cree?"
        
        if item not in self.listas_memoria[nombre_lista]['items']:
            self.listas_memoria[nombre_lista]['items'].append(item)
            self.listas_memoria[nombre_lista]['fecha_modificacion'] = datetime.now().isoformat()
            self._guardar_listas_en_memoria()
            return f"✅ '{item}' agregado a la lista '{nombre_lista}'."
        else:
            return f"ℹ️ '{item}' ya existe en la lista '{nombre_lista}'."

    def _mostrar_lista(self, nombre_lista):
        """Mostrar el contenido de una lista"""
        if nombre_lista not in self.listas_memoria:
            return f"❌ La lista '{nombre_lista}' no existe."
        
        lista = self.listas_memoria[nombre_lista]
        if not lista['items']:
            return f"📝 La lista '{nombre_lista}' está vacía."
        
        items_texto = '\n'.join([f"{i+1}. {item}" for i, item in enumerate(lista['items'])])
        return f"📋 **Lista: {nombre_lista}**\n{items_texto}\n\n*Total: {len(lista['items'])} items*"

    def _eliminar_item_lista(self, nombre_lista, item):
        """Eliminar un item de una lista"""
        if nombre_lista not in self.listas_memoria:
            return f"❌ La lista '{nombre_lista}' no existe."
        
        if item in self.listas_memoria[nombre_lista]['items']:
            self.listas_memoria[nombre_lista]['items'].remove(item)
            self.listas_memoria[nombre_lista]['fecha_modificacion'] = datetime.now().isoformat()
            self._guardar_listas_en_memoria()
            return f"✅ '{item}' eliminado de la lista '{nombre_lista}'."
        else:
            return f"❌ '{item}' no se encuentra en la lista '{nombre_lista}'."

    def _limpiar_lista(self, nombre_lista):
        """Limpiar todos los items de una lista"""
        if nombre_lista not in self.listas_memoria:
            return f"❌ La lista '{nombre_lista}' no existe."
        
        self.listas_memoria[nombre_lista]['items'] = []
        self.listas_memoria[nombre_lista]['fecha_modificacion'] = datetime.now().isoformat()
        self._guardar_listas_en_memoria()
        return f"✅ Lista '{nombre_lista}' limpiada exitosamente."

    def _listar_todas_las_listas(self):
        """Mostrar todas las listas disponibles"""
        if not self.listas_memoria:
            return "📝 No hay listas creadas aún."
        
        resultado = "📋 **Listas disponibles:**\n\n"
        for nombre, datos in self.listas_memoria.items():
            cantidad = len(datos['items'])
            resultado += f"• **{nombre}** ({cantidad} items)\n"
        
        return resultado

    def _procesar_comando_lista_ia(self, texto):
        """Usar IA para procesar comandos de lista más complejos"""
        prompt_lista = f"""
        Analiza el siguiente texto y determina si el usuario quiere realizar alguna operación con listas.
        
        Texto: "{texto}"
        
        Listas existentes: {list(self.listas_memoria.keys())}
        
        Si detectas una operación de lista, responde en formato JSON:
        {{
            "accion": "crear_lista|agregar_item|mostrar_lista|eliminar_item|limpiar_lista|listar_todas",
            "nombre_lista": "nombre de la lista",
            "item": "item a agregar/eliminar (si aplica)",
            "items": ["lista de items si es crear lista"]
        }}
        
        Si NO es una operación de lista, responde: "NO_ES_COMANDO_LISTA"
        """
        
        try:
            respuesta = self.llm.invoke(prompt_lista).content.strip()
            
            if respuesta == "NO_ES_COMANDO_LISTA":
                return None
                
            comando_data = json.loads(respuesta)
            accion = comando_data.get('accion')
            
            if accion == 'crear_lista':
                return self._crear_lista(
                    comando_data.get('nombre_lista'), 
                    comando_data.get('items', [])
                )
            elif accion == 'agregar_item':
                return self._agregar_item_lista(
                    comando_data.get('nombre_lista'),
                    comando_data.get('item')
                )
            elif accion == 'mostrar_lista':
                return self._mostrar_lista(comando_data.get('nombre_lista'))
            elif accion == 'eliminar_item':
                return self._eliminar_item_lista(
                    comando_data.get('nombre_lista'),
                    comando_data.get('item')
                )
            elif accion == 'limpiar_lista':
                return self._limpiar_lista(comando_data.get('nombre_lista'))
            elif accion == 'listar_todas':
                return self._listar_todas_las_listas()
                
        except Exception as e:
            return None
        
        return None

    def obtener_preguntas_frecuentes(self, limite=10):
        """Obtener las preguntas más frecuentes"""
        if not self.preguntas_frecuentes:
            return "📝 Aún no hay preguntas registradas."
        
        preguntas_recientes = self.preguntas_frecuentes[-limite:]
        resultado = "❓ **Preguntas recientes:**\n\n"
        
        for i, pregunta_data in enumerate(preguntas_recientes, 1):
            resultado += f"{i}. {pregunta_data['pregunta']}\n"
        
        return resultado

    def consultar_con_listas(self, pregunta, descripcion_agente=''):
        """Método principal que incluye el manejo de listas"""
        # Primero verificar si es un comando de lista
        resultado_lista = self._procesar_comando_lista_ia(pregunta)
        if resultado_lista:
            return resultado_lista
        
        # Si no es comando de lista, proceder con consulta normal
        return self.consultar(pregunta, descripcion_agente)