# agents_ai/memoria — memoria del agente

Dos memorias distintas, no confundirlas:

| Archivo | Para qué es |
|---|---|
| `historial.py` | `DjangoChatMessageHistory` — memoria CONVERSACIONAL: los mensajes de UNA conversación, guardados en la tabla `MessageStore`. Es lo que permite "agregale otra al pedido" dentro del mismo chat. `get_recent(n)` trae los últimos n con LIMIT (no carga todo), filtra mensajes internos `LISTA_GUARDADA:`. |
| `rag_conversaciones.py` | Memoria RAG por AGENTE — conocimiento aprendido ENTRE conversaciones. FAISS en `media/vectorstores/agente_<id>_memoria/`. Se alimenta de: (1) cada pregunta→respuesta válida en vivo (`guardar_interaccion_async`, hilo background con debounce), y (2) el resumen de cada conversación cerrada (`guardar_conocimiento`, se llama desde `resumir_conversacion`). Se consulta en cada mensaje (`recuperar_memoria`, bloque compacto k=3 ≤900 chars, excluye la conversación actual). Solo conversaciones REALES de WhatsApp escriben — los chats de prueba no contaminan. |

Costos: escribir = 1 embedding (el mismo vector sirve para dedupe e indexado);
leer = 0 embeddings extra si llega `query_vector`. Tope 4.000 docs por agente,
dedupe por similitud ≤0.05. Switch por agente: `AgentesIA.memoria_rag_activa`.
