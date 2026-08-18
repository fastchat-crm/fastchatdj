# agents_ai/prompts — prompts centralizados

Todo prompt del sistema IA vive en `agents_ai`. `core/constantes.py` re-exporta
estos símbolos por compatibilidad — los imports viejos siguen funcionando.

| Archivo | Para qué es |
|---|---|
| `plantillas.py` | `PROMPT_TEMPLATES` — el template maestro del agente conversacional (por idioma), con las "reglas de oro" (nunca decir que es un bot, solo datos del contexto, mensajes cortos, variación de frases) y todas las variables disponibles (`{question}`, `{context}`, `{nombre_bot}`, `{historial_contacto}`, ánimo, horario...). Orden crítico: los bloques estáticos por agente (persona, reglas) van PRIMERO y las variables por mensaje (momento, historial, contexto, pregunta) al FINAL — el prefijo idéntico entre mensajes activa el prompt caching de OpenAI/Claude/DeepSeek (input tokens con descuento). No mover variables dinámicas hacia arriba. |
| `personalidades.py` | `PERSONALIDAD_PRESETS` — presets de persona (Amable/Directo/Formal/Vendedor/Soporte) que llenan de un click nombre, personalidad, tono, estilo y temperature; `PERSONALIDAD_PRESET_CHOICES` para el form; `FRASES_RELLENO` — frases rotativas de humanización. |
| `recomendados.py` | `PROMPT_RECOMENDADO` — plantilla de arranque genérica y editable que se ofrece en el tab "Prompt" del editor de agente. Movido desde `agents_ai/prompts_recomendados.py` (que quedó como shim). |
| `catalogo.py` | Índice declarativo (`CATALOGO`, `PromptInfo`) de TODOS los prompts del motor: clave, ubicación, dónde se usa, propósito, tipo y variables. Es un mapa, no el texto. Helpers: `por_clave`, `por_grupo`, `claves`. Mantener sincronizado al crear/mover/borrar un prompt. |

Prompts que viven en otros archivos del paquete (a propósito, junto a su lógica):
`ai_actions/prompts.py` (registry de las acciones one-shot) y
`auditor_agente.AUDITOR_SYSTEM_PROMPT` (auditoría de agentes). El **catálogo
central** (`catalogo.py`) los indexa a todos, incluidos esos y los de fuera de
`prompts/` (resumidor, sentimiento, evaluación, voz, multimodal).
