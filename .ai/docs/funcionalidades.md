# Mapa de funcionalidades de fastchat

Inventario completo a nivel de feature: qué hace cada módulo, caso de uso y punto de
entrada. Generado 2026-07-14 desde los `urls.py`, vistas y templates reales.
Objetivo del producto: plataforma de mensajería multicanal + IA que reemplace
GoHighLevel y ManyChat.

Rutas de montaje: `whatsapp/` → `/whatsapp/`, `crm/` → `/crm/`, `agenda/` → `/agenda/`,
`voz/` → `/voz/`, `autenticacion/` → `/autenticacion/`, `seguridad/` → `/seguridad/`,
`area_geografica/` → `/area-geografica/`, `instagram/` → `/instagram/`,
`tiktok/` → `/tiktok/`, `public/` → `/`. `meta/` y `core/` son librerías sin URLs propias.

---

## whatsapp/ — motor central de mensajería multicanal

### Centro de canal (`/whatsapp/centro/`, `/instagram/centro/`, `/tiktok/centro/`, `view_centro.py`)
- Página guía por canal: cards de cada módulo con qué hace, cuándo usarlo, nivel (esencial/recomendado/avanzado) y orden por fases (conexión → automatización → audiencia/marketing → operación → medición). Contenido estático en `GUIAS_CANAL`; wrappers en `instagram/view_centro.py` y `tiktok/view_centro.py`.

### Sesiones / canales (`/whatsapp/sesiones/`, `view_sesiones.py`)
- Tablero de conexiones en cards con estado, badge de conversaciones abiertas y refresco AJAX por card. Canales activables desde configuración: WhatsApp QR (Baileys), WhatsApp API (Meta), Instagram, Messenger, TikTok.
- Conexión Baileys por QR (start/status/verificar/disconnect/reconnect contra el servicio Node).
- Conexión Meta Cloud API: OAuth Embedded Signup (`meta_oauth_view.py`) o alta manual con validación dry-run (`meta_manual_view.py`); registro/verificación OTP del número; revalidar credenciales; plantilla de prueba.
- Edición de sesión: `modo_bot` (ninguno/tradicional/ia/hibrido), idioma, zona horaria, `min_sesion`, mensajes de bienvenida/despedida/handoff/reconexión, agente IA, departamentos.
- Activar/pausar servicio sin desconectar; eliminación individual/bulk/huérfanas.
- Usuarios de la sesión con roles asesor/supervisor (`PerfilSesionWhatsApp`) + modal de carga de asesores (conversaciones abiertas, 24h, disponibilidad) + logs de notificaciones de asignación.
- Resumen de salud de la conexión (checklist con % de completitud), historial de cambios, modal post-conexión con pasos críticos Meta.
- Configuración de anuncios (Marketing API, `services_ads.py`) para atribución CTWA.
- Respuestas rápidas y menús rápidos por sesión (envío interactivo: botones/list en Meta, numerado en Baileys).
- Diagnóstico Meta (`meta_diagnostico_view.py`): webhook, suscripción WABA, salud del número, trazas; foto de perfil.
- Selector global de sesión activa (`/whatsapp/sesion-activa/`).

### Contactos (`/whatsapp/contacto/`, `view_contacto.py`)
- Listado con filtros, detección de duplicados entre sesiones, export Excel.
- CRUD + importación masiva xlsx/csv con etiquetas autocreadas y reporte por fila.
- Campos personalizados (`CampoPersonalizadoContacto`/`ValorCampoContacto`) y etiquetas M2M.
- Opt-out automático (`opt_out.py`): keywords BAJA/STOP y ALTA en entrantes; errores Meta 131050→opt_out, 131030→número inválido; los crons masivos excluyen estos contactos.
- Sincronización de agenda Baileys (`sync_contacts.py`).

### Mensajes programados (por contacto)
- Programar texto+adjunto a fecha/hora (solo Baileys), enviar ahora, eliminar. Despacho por `cron_jobs/enviar_mensajes_programados.py` con claim atómico anti-doble-envío y tope de `intentos`.

### Conversaciones — inbox activo (`/whatsapp/conversaciones/`, `view_conversaciones.py`)
- Bandeja por sesión con filtros (criterio, clasificación Lead→Cliente, sin responder, mías), badge no leídas, vista supervisor vs asesor (`permisos_sesion.py`).
- Hilo con estado IA, asignación, ventana Meta 24h, atribución CTWA, estadísticas.
- Envío de texto/multimedia con bloqueo por ventana 24h (pide plantilla); mensajes fallidos reenviables; responder como humano pausa el bot.
- Transcripción Whisper de notas de voz; editar/eliminar mensaje (solo Baileys); enviar plantilla Meta APPROVED desde el chat.
- Tomar conversación (asignación atómica + presentación automática), asignar/desasignar con handoff y notificación, round-robin vía API.
- Estados de atención (abierta/pendiente/resuelta), snooze, reabrir, toggle IA, bloquear cierre automático, reiniciar flujo, cerrar con/sin despedida.
- Respuesta a recordatorio de turno: "confirmar"/"cancelar" se resuelven sin LLM (`agenda/respuestas_recordatorio.py`).
- Ficha de cliente CRM desde el chat (alta manual precargada con variables del flujo), historial del contacto, cambiar clasificación/nombre.
- Feedback a mensajes del bot → crea `FaqAgente` aprobada + vectorstore.
- Asignar a pipeline Kanban; respuestas rápidas globales con `/atajo`; presencia "escribiendo" y anticolisión de agentes por WebSocket.

### Conversaciones finalizadas (`/whatsapp/conversaciones-finalizadas/`)
- Bandeja de cerradas con filtros por fechas/sentimiento/clasificación, hilo solo lectura, resumen IA, reactivación dentro de ventana o plantilla de reconexión.

### Pendientes de reconexión (`/whatsapp/conversaciones-pendiente-reconexion/`)
- Bandeja de reenganche con plantilla de reconexión o descarte; automatizado por `cron_jobs/enviar_mensaje_reconexion.py`.

### Campañas masivas (`/whatsapp/campanas/`, `view_campanas.py`)
- Campañas texto/plantilla/media con segmentación por etiquetas incluir/excluir, throttle por minuto, multi-canal (whatsapp/instagram/messenger); estados borrador→programada→enviando→completada/pausada/cancelada/error.
- Generación de campaña con IA; detalle por envío; stats por API. Despacho por `cron_jobs/ejecutar_campanas.py` con tope diario por tier Meta.

### Plantillas Meta (`/whatsapp/plantillas/`)
- CRUD con categorías UTILITY/MARKETING/AUTHENTICATION, variables `{{n}}`, botones; someter a aprobación Meta, sincronizar estados; generación/edición con IA (preview 2 pasos).

### Tarifas Meta (`/whatsapp/tarifas/`)
- CRUD de tarifas por país/categoría con vigencias + simulador de costos de envíos masivos.

### Etiquetas (`/whatsapp/etiquetas/`)
- CRUD (nombre/color) por usuario, asignación individual y masiva vía API. Base de la segmentación de campañas.

### Segmentos guardados (`/whatsapp/segmentos/`, `view_segmentos.py`)
- Filtros reutilizables de contactos (`SegmentoContacto`, condiciones JSON evaluadas en `funciones_segmentos.py`): etiquetas incluir (cualquiera/todas) y excluir, canal de origen, campos personalizados (igual/contiene/vacío/con valor, vía subquery Exists), actividad reciente (con/sin mensajes en N días). Siempre excluyen opt-out e inválidos.
- Builder visual con vista previa de audiencia (conteo + muestra). Usables como audiencia de campañas (`Campana.segmento`, se recalcula al materializar envíos) y para inscripción masiva en secuencias.

### Enlaces de captación / growth links (`/whatsapp/enlaces/`, `view_growth.py`)
- `EnlaceCrecimiento`: link `wa.me` con texto prellenado + marcador `(ref: codigo)` y QR (api.qrserver.com). Al llegar el mensaje con el marcador (`funciones_growth.py`, hook en `procesar_mensaje.py`): registra el uso (una vez por contacto, `UsoEnlaceCrecimiento`), aplica etiqueta (que puede disparar secuencia), inscribe en secuencia directa y/o responde mensaje fijo cortando el pipeline. Métrica de leads por enlace.

### Secuencias drip (`/whatsapp/secuencias/`, `view_secuencias.py`)
- Series de mensajes con esperas en horas entre pasos (estilo ManyChat): CRUD de secuencia + editor de pasos, etiqueta disparadora (inscripción automática vía signal m2m al asignar la etiqueta por cualquier camino), inscripción manual con buscador de contactos, listado de inscripciones con cancelación.
- "Salir al responder": cualquier mensaje entrante del contacto cancela sus inscripciones activas (hook en `procesar_mensaje.py`).
- Despacho por `cron_jobs/ejecutar_secuencias.py` con claim atómico, tope de intentos, respeto de opt-out y backoff de ventana Meta 24h.

### Pipeline / Kanban de ventas (`/whatsapp/pipeline/`)
- Tableros con etapas (color, orden, probabilidad, ganado/perdido), cards ligadas a conversaciones con valor y moneda, drag&drop con historial, comentarios, deep-link al inbox; mover a "ganado" dispara Purchase a Meta CAPI; generación de pipeline con IA.

### Horarios de atención (`/whatsapp/horarios/`)
- Franjas semanales + excepciones/feriados + mensaje fuera de horario + zona horaria; duplicar entre sesiones; sincronización del perfil de negocio con Meta (leer/actualizar); generación con IA.

### Analytics (`/whatsapp/analytics/`)
- KPIs (conversaciones, leads/clientes, mensajes IA/humanos, consumo Meta facturable, tiempos de respuesta), gráficos por día/clasificación/canal/sentimiento, ranking de agentes, ROI CTWA por anuncio, forecast de pipeline, eventos CAPI.

### Supervisión (`/whatsapp/supervision/`)
- Embudo de prospectos, rendimiento por asesor, pronóstico de ventas y monitor en vivo (esperas >10 min, sin asignar).

### Trazas / debug IA (`/whatsapp/trazas/`)
- Trazado end-to-end del pipeline (webhook→LLM→envío) con filtros por etapa/nivel/sesión/API key, timeline por mensaje y resumen en vivo con tokens/costo. Modelo `TrazaMensajeIA`.

### Comentarios sociales (`view_comentarios.py`, expuesto vía `/instagram/comentarios/` y `/tiktok/comentarios/`)
- Inbox de comentarios de publicaciones (`ComentarioSocial`): responder público, ocultar/mostrar, convertir en DM (private reply) → entra al pipeline de conversaciones.

### Reglas comentario→DM (`/instagram/reglas-comentarios/`, `view_reglas_comentarios.py`)
- `ReglaComentario`: automatización por keywords (sin tildes/mayúsculas; vacío = todo comentario), opcionalmente limitada a una publicación. Al matchear (primera regla por orden gana, motor en `funciones_comentarios.procesar_reglas_comentario`, disparado al ingresar el comentario por webhook): respuesta pública automática, DM (private reply, ventana Meta 7 días) y/o etiqueta al contacto si existe. Contador de usos. Canal instagram hoy; tiktok cuando se apruebe su API.

### Webhooks entrantes
- Baileys (`/whatsapp/webhook_handler/` + batch), heartbeat Node (`/whatsapp/heartbeat/`), trace receiver, Meta Cloud (`/whatsapp/meta_webhook/` con HMAC + handshake), Instagram DM, Messenger, TikTok (beta). Idempotencia en dos capas (candado cache + `mensaje_id_externo`). Log e inspección de hits crudos Meta por sesión.
- Todos convergen en `procesar_mensaje.py::process_incoming_message` (contacto→conversación→opt-out→recordatorios agenda→motor flujo/IA→WebSocket).

### Webhooks salientes
- `webhooks_salientes.py`: POST firmado HMAC a suscriptores por evento, backoff exponencial, registro de entregas, auto-desactivación tras 8 fallos.

### API REST v1 (`/whatsapp/api/v1/…`, X-API-Key, rate limit 120/min)
- Contactos (list/create/get), conversaciones (list/mensajes/asignar manual o round-robin/mover etapa/enviar), mensajes a número, etiquetas bulk, evento CAPI manual, stats de campaña.

### WebSocket (Channels, `routing.py`/`consumers.py`)
- `ws/chat/<conv>/` (hilo en vivo, presencia, anticolisión de agentes), `ws/session/<id>/` (QR/estado), `ws/sessionroom/<id>/` (nuevos mensajes al inbox con preview para notificación del navegador).

---

## crm/ — chatbots, agentes IA y CRM

### Motor de flujos tradicional (`/crm/departamentos_chatbots/`, editor tipo n8n)
- Departamentos chatbot (color, saludo, keywords de enrutamiento, default, reset triggers) con duplicación.
- Editor visual de grafo: nodos con posición, conexiones etiquetadas, historial de movimientos, prueba de nodos HTTP/función inline, export JSON y payload Meta.
- 13 tipos de nodo: menu, respuesta, pregunta (validaciones none/regex/email/número/cédula EC/RUC EC/fecha/teléfono), http, funcion, condicional, set_variable, cta_url, ubicacion, handoff, agenda_turno, loop, fin. Variables `{{variables.x}}`/`{{response.body...}}`.
- Generación de flujo completo por IA (descripción libre o wizard conversacional) y explicación narrativa del flujo por IA (cacheada).
- Runtime `motor_flujo_chatbot.py` (`EstadoFlujoChatbot`: nodo actual, variables, reintentos, handoff); chat de prueba dry-run por sesión.
- Handoff a humano → `helpers_asignacion.py`: pool por sesión (`PerfilSesionWhatsApp`), filtro `DisponibilidadAgente`, balanceo por carga 24h, notificación interna+push+email con log por canal.

### Endpoints y credenciales API (`/crm/endpoints_api/`)
- `EndpointApiChatbot` (base URL, headers, timeout) y `CredencialApiChatbot` (bearer/basic/apikey/custom) reutilizables en nodos http y herramientas; fusión de duplicados; stub de captura local.

### Perfil de empresa (`/crm/perfil_empresa/`)
- `PerfilNegocioIA` (industria, actividad, público objetivo) + catálogos de productos y servicios + respuestas entrenadas con tono. Alimenta el contexto de todos los agentes.

### Catálogos (`/crm/industria/`, `/crm/actividad_economica/`)
- Industrias con etapas de venta configurables (embudo) y actividades económicas.

### Clientes (`/crm/cliente/`)
- Ficha de cliente con trazabilidad de origen por canal (chatbot/cotizador/agenda/manual) y contador de recurrencia.

### Agentes IA — entrenamiento (`/crm/entrenamiento/`, `view_mientrenamiento.py`)
- CRUD/duplicación de `AgentesIA`: prompt template, contexto estático, presets de personalidad (nombre bot, tono, estilo, temperatura), mensaje de bienvenida sin LLM.
- Humanización: burbujas, delays de lectura/escritura simulados, saludo por franja, detección de ánimo (`agents_ai/humanizacion.py`).
- Config avanzada RAG por agente: `k`/`fetch_k`, presupuestos de chars, turnos de historial, snippets, max output tokens, umbral de relevancia.
- Fuentes de entrenamiento (`DetalleAgentesAI`): enlace/API (con cache), archivo (Tika+OCR, ≤10MB) o texto; contexto estático ≤40k chars o FAISS; preview de prompt/contexto/procesamiento; reprocesar RAG; inspector de chunks.
- Memoria RAG por agente (aprende pares pregunta→respuesta entre conversaciones, FAISS propio, umbral de relevancia en lectura).
- Chat de prueba con media; suite de evaluación con juez LLM (score 0-10); simulación de prompt; optimización de defaults en lote.
- Wizard 3 pasos de creación rápida (`/crm/entrenamiento/wizard/`).

### API Keys IA
- `ApiKeyIA` por proveedor (Gemini/OpenAI/Claude/Ollama/DeepSeek/Huawei MaaS) con modelo, base_url, test individual/masivo, auto-desactivación por error, token de webservice regenerable.

### Herramientas / tools (function-calling)
- `HerramientaAgente`: tools HTTP (método, params tipados que el LLM completa, headers, plantilla Jinja de respuesta, timeout, protección SSRF) o función interna registrada; generación asistida por IA; plantillas; simulador; logs de invocación (`LogHerramientaAgente`).
- Funciones internas registradas (`funciones_chatbot.py`): cotizadores (aria, am, multiple), consulta cédula; suite de agenda (`funciones_agenda.py`): init, listar servicios/días/recursos/mis citas, disponibilidad, resumen, registrar turno (acepta `recordatorio_horas_antes` pedido por el cliente).

### FAQs curables
- `FaqAgente` con estados pendiente/aprobada/desactivada, prioridad, hits; top-N inyectadas al prompt; aprendizaje automático desde conversaciones; feedback de asesores con corrección.

### Auditor IA
- `AuditoriaAgenteIA`: LLM analiza config+métricas y propone mejoras de prompt/contexto con snapshot y rollback; aplicar FAQs sugeridas.

### Acciones IA one-shot (`agents_ai/ai_actions/`)
- Generar: agente (desde descripción o desde departamento con migración de nodos a tools), departamento/flujo, herramienta, campaña multicanal, horarios+excepciones, pipeline+etapas, plantillas Meta. Base común con modo JSON forzado y registro de consumo.

### Consumo, costos y alertas
- `ConsumoTokenIA` por llamada con origen (whatsapp/chat_crm/webservice/resumidor/sentimiento/auditor/plantilla/herramienta), costo USD por tabla de precios (`agents_ai/consumo.py`), y `AlertaConsumoIA` (umbral diario/mensual por key con notificación).

### Reglas de fin de conversación
- `ReglaFinConversacion` (frases o señal LLM `[FIN_CONVERSACION]`) + `AccionFinConversacion` (email/WhatsApp a supervisor/webhook/marcar) ejecutadas al cierre.

### WebService externo
- `POST /api/ia/consultar/` (Bearer webservice_token): sistemas externos consultan al agente con texto/imagen/audio/documento y `session_id` multi-turno.

---

## agents_ai/ — motor de IA (sin URLs propias; ver `agents_ai/README.md`)

- `AgenteConsultor`: pipeline por mensaje — clasificación regex (saludo/ack-smalltalk/consulta amplia), retrieval híbrido BM25+FAISS MMR con umbral de relevancia y 1 solo embedding compartido, FAQs, APIs en vivo, memoria RAG, prompt con prefijo estático (prompt caching), invocación con o sin tool-calling (temperatura reducida en tools), señal de fin, tokens por provider.
- Providers: gemini, openai, claude, ollama, deepseek, huawei (openai_compat) con clientes cacheados y timeouts/retries acotados.
- `AgenteResumidor` (resúmenes + sentimiento), `auditor_agente.py`, `humanizacion.py`, `tools_builder.py`, `consumo.py`, `MessageStore` (historial).
- `rag/`: extracción Tika+OCR, vectorstores FAISS, reproceso. `memoria/`: historial conversacional + memoria RAG por agente.
- Colecciones RAG independientes del agente (`/crm/rag/`): `RagColeccion`/`RagFuente` con FAISS propio, indexación, prueba de consulta y asignación a sesión.

---

## agenda/ — agendamiento de turnos

- Configuración (`/agenda/configuracion/`): grupos de agenda (moneda, zona horaria, horas de recordatorio, responsable notificado), recursos reservables (color/orden/usuario), servicios (duración/precio/recursos M2M), horarios laborales por recurso con slot, excepciones (bloquear día/rango o rango extra).
- Citas (`/agenda/citas/`): calendario de turnos con crear/reagendar (encadena `turno_anterior`)/cambiar estado (pending/confirmed/cancelled/rescheduled/fulfilled/no_show)/eliminar; control de solapamientos; snapshot de precio; cálculo de slots (`helpers.py`).
- Chatbot: nodo `agenda_turno` (reservar/cancelar/reagendar) en el flujo tradicional y suite `agenda_*` como tools del agente IA.
- Notificaciones de creación (correo + push + interna al responsable) y recordatorios automáticos por cron con anticipación por grupo o por turno, catch-up, claim atómico y tope de intentos.
- Respuestas al recordatorio: `respuestas_recordatorio.py` — "confirmar"/"cancelar" deterministas sin LLM, con notificación de cancelación al responsable.

---

## voz/ — llamadas con IA (base incipiente)

- Webhook Twilio (`/voz/twilio/webhook/`): TwiML con saludo + stream WS. Demo WebRTC (`/voz/demo/`) con selector de agente.
- Pipeline STT→LLM→TTS (`services.py`): faster-whisper, Gemini (prompt telefónico corto, sin RAG aún), Piper TTS. Modelos `LlamadaVoz`/`MensajeVoz` con latencias por turno. Sin UI de gestión (solo admin).

---

## instagram/ y tiktok/ — capas de control por canal (sin modelos propios)

- Instagram: sesiones IG (autodetección con Access Token, verify token, prueba), conversaciones DM (inbox compartido con branding IG), comentarios, publicaciones en vivo con moderación y private reply.
- TikTok: pre-registro de cuentas Business (beta), inbox y comentarios listos para cuando se apruebe la Business Messaging API; `TikTokService` ya enchufado al dispatcher de canales.

---

## seguridad/ — administración, RBAC y config global

- Configuración global (singleton `Configuracion`): branding, canales activos, token IA del sistema, Tika, cierre higiénico. Términos y condiciones.
- Credenciales Meta App (`CredencialMetaApp`) con autodetección y checklist de validación (`meta/autodetect.py`, `meta/validacion.py`).
- RBAC: roles (`Group`), URLs por rol (`GroupModulo`), árbol de módulos/sidebar, mantenimiento de URLs. Desde Mantenimiento de URLs (`/seguridad/modulo/urls/`) cada módulo se asigna a grupos del sidebar Y se habilita a roles directamente (acciones `roles_modulo`/`guardar_roles_modulo`, crea el `GroupModulo` del rol si no existe).
- Auditoría de acciones de usuario; multi-empresa (`Empresa`); backups de BD descargables (grilla semanal); documentación in-app por temas.
- Mailing masivo (listas + tareas de envío + plantillas); push broadcast (Web Push); notificaciones internas (`/notificaciones/`).
- Suplantar sesión de usuario (soporte); dashboard `/panel/`; API pública `/api/enviar-mensaje/` (rate-limited).

## autenticacion/ — identidad

- Login/logout, recuperación de clave, cambio obligatorio de clave, perfil propio con auditoría, CRUD de usuarios administrativos (roles, carga masiva Excel, export, cambio masivo de clave), personas/clientes (`PerfilPersona`).

## public/ — portal público

- Landing "MensajerIA", login/registro público con términos, restaurar contraseña, recordar usuario, cambiar clave, páginas institucionales (acerca de, quiénes somos, términos/privacidad), registro de visitas.

## area_geografica/ — catálogos

- CRUD de países, provincias y ciudades (parroquias existe pero no expuesto).

## meta/ — librería Graph API (ver `meta/README.md`)

- URLs Graph centralizadas y versión de API, credenciales desde BD, utilidades de webhook (HMAC, handshake, extractores), autodetección y validación de credenciales, verificación de perfiles por canal, CAPI (Lead/Purchase con `ctwa_clid`), `MetaWhatsAppService` (texto/media/plantillas/sync), `InstagramService`/`MessengerService` (DMs, publicaciones, comentarios, private reply).

## core/ — infraestructura compartida

- `ModeloBase` (soft-delete + auditoría), dispatcher AJAX `/ajaxrequest/`, `addData`/`secure_module`/paginador, middleware de request actual, validadores de archivos, PDF/Excel, correo en background, push, cifrado.

## cron_jobs/ — tareas programadas (detalle en `cron_jobs/README.md`)

ejecutar_campanas (1 min) · enviar_mensajes_programados (1 min) · enviar_mensaje_reconexion (15 min) · enviar_mensaje_despedida (10 min) · reabrir_pospuestas (5 min) · reconectar_sesiones (5 min) · enviar_recordatorios_turnos (15 min) · aprender_conversaciones (diario) · enviar_correo_prueba (manual).

---

## Casos de uso transversales

1. **Atención automática multicanal**: cliente escribe por WhatsApp/Instagram → webhook → dedup → opt-out → modo_bot (flujo tradicional, IA o híbrido) → respuesta humanizada en burbujas → traza completa en `/whatsapp/trazas/`.
2. **Handoff a humano**: nodo handoff o asignación manual → selección por carga/disponibilidad → presentación automática → bot pausado → inbox en vivo por WebSocket.
3. **Agendamiento conversacional**: cliente agenda por chat (nodo `agenda_turno` o tools `agenda_*`) → notificación al responsable → recordatorio automático con confirmar/cancelar por respuesta.
4. **Marketing**: importar contactos → etiquetar → campaña segmentada con throttle y tope por tier → opt-out automático → stats y ROI CTWA → conversión reportada a Meta CAPI al ganar el pipeline.
5. **Mejora continua del agente IA**: trazas + consumo/alertas → evaluación con juez LLM → auditor propone cambios → FAQs curadas desde feedback de asesores → minería nocturna de conversaciones exitosas.
6. **Integración externa**: API REST v1, webservice IA multi-turno, webhooks salientes firmados.
