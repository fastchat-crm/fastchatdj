# agents_ai/prompts — prompts centralizados

Todo prompt del sistema IA vive en `agents_ai`. `core/constantes.py` re-exporta
estos símbolos por compatibilidad — los imports viejos siguen funcionando.

| Archivo | Para qué es |
|---|---|
| `plantillas.py` | `PROMPT_TEMPLATES` — el template maestro del agente conversacional (por idioma), con las "reglas de oro" (nunca decir que es un bot, solo datos del contexto, mensajes cortos, variación de frases) y todas las variables disponibles (`{question}`, `{context}`, `{nombre_bot}`, `{historial_contacto}`, ánimo, horario...). |
| `personalidades.py` | `PERSONALIDAD_PRESETS` — presets de persona (Amable/Directo/Formal/Vendedor/Soporte) que llenan de un click nombre, personalidad, tono, estilo y temperature; `PERSONALIDAD_PRESET_CHOICES` para el form; `FRASES_RELLENO` — frases rotativas de humanización. |

Prompts que viven en otros archivos del paquete (a propósito, junto a su lógica):
`ai_actions/prompts.py` (registry de las acciones one-shot) y
`auditor_agente.AUDITOR_SYSTEM_PROMPT` (auditoría de agentes).
