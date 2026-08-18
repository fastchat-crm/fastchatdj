# agents_ai/ai_actions — acciones IA one-shot (fuera del chat)

Funciones internas del sistema que usan IA para GENERAR configuración, no para
conversar. Cada módulo atiende una acción AJAX de una view. Todas registran su
consumo en `ConsumoTokenIA`.

| Archivo | Para qué es | Se usa desde |
|---|---|---|
| `base.py` | Infraestructura común: `validar_apikey`, `build_llm` (modo JSON forzado según provider + `base_url`), `parse_json_response` (parser tolerante en 4 etapas), `log_consumo`, `invocar_json`. Excepción segura para UI: `IAActionError`. | todos los módulos |
| `prompts.py` | Registry central de los prompts de estas acciones. | todos |
| `agentes_crm.py` | Genera un `AgentesIA` completo desde una descripción libre ("crear con IA"). | entrenamiento + departamentos |
| `auditor_crm.py` | Auditoría de calidad del agente: analiza conversaciones/métricas y propone prompt/contexto/FAQs mejorados. | tab Auditor |
| `herramientas_crm.py` | Genera la configuración de una `HerramientaAgente` (tool HTTP) desde una frase. | tab Herramientas |
| `plantillas_wa.py` | Redacta plantillas de WhatsApp listas para enviar a aprobación de Meta. `ajustar_variables_extremos()` corrige cuerpos que empiezan/terminan con `{{N}}` (Meta los rechaza, error 2388299) — se aplica en `generar_uno`, `editar_uno`, `_sanitizar_plantilla` **y en `PlantillaWhatsApp.save()`** (cubre todos los caminos); los prompts lo prohíben y `view_plantillas.someter_a_meta` valida antes de enviar. `editar_uno(plantilla, instruccion, apikey_obj)` = "Editar con IA" del listado: reescribe una plantilla BORRADOR/REJECTED según instrucción libre, sin tocar nombre/idioma, con consumo en `ConsumoTokenIA`. | view_plantillas |
| `campanas_wa.py` | Genera campañas multi-canal (texto + segmentación sugerida). | view_campanas |
| `horarios_wa.py` | Convierte horarios en lenguaje natural ("lunes a viernes de 9 a 6") en registros de horario. | view_horarios |
| `pipeline_wa.py` | Genera el Kanban de ventas (etapas del pipeline) desde una descripción. | view_pipeline |
| `dpchatbots_crm.py` | Genera flujos completos del chatbot tradicional (nodos + conexiones). | departamentos chatbot |
