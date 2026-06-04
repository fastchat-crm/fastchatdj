# Estudio completo del proyecto fastchat

> Auditoría funcional + análisis competitivo. Estado a 2026-05-30.
> Objetivo: mapear todo lo que hace el sistema y qué falta para competir como CRM WhatsApp comercial (vs Wati, Respond.io, Chatwoot, 360dialog, ManyChat).

---

## 1. Resumen ejecutivo

fastchat ya es una **plataforma de mensajería + CRM con IA** muy por encima de un MVP. Tiene doble transporte WhatsApp (Baileys no oficial + Meta Cloud API oficial), Instagram y Messenger, motor de chatbot por flujo, agentes IA con RAG, pipeline kanban, campañas masivas, agenda de turnos, atribución de anuncios (CAPI), API REST y webhooks salientes.

**Lo que la separa de ser un SaaS comercial competitivo:**
1. **No es multi-tenant real** — todo se aísla por `Usuario`/`SesionWhatsApp`, no por organización. Bloqueante para vender como SaaS multi-cliente.
2. **No hay billing/suscripciones ni cuotas por plan.**
3. **Faltan features de productividad de inbox** (snooze, detección de colisión, respuestas rápidas globales).
4. **Sin canales email/SMS ni widget web.**
5. **Deuda técnica de producción** (secretos en `credenciales.json`, email hardcodeado, casi sin tests, posibles N+1).

Veredicto: **excelente producto single-tenant / self-hosted**; requiere capa de tenancy + billing + pulido de inbox para pelear en el mercado SaaS.

---

## 2. Arquitectura y stack

| Capa | Tecnología | Nota |
|---|---|---|
| Backend | Django 4.2.15, Python 3.9 | monolito |
| Realtime | Channels 4 + Daphne (ASGI) + Redis layer | WebSocket chat/sesión/QR |
| BD | PostgreSQL 15 | `ATOMIC_REQUESTS` |
| Cache/colas | Redis | channel layer + cache |
| Media | filesystem local (`MEDIA_ROOT/whatsapp_media/`) | sin TTL ni particionado |
| Email | SendGrid SMTP | API key en claro |
| Cifrado | Fernet (`core/crypto.py`, `EncryptedTextField`) | tokens Meta/Baileys |
| PWA | service worker + WebPush | notificaciones browser |
| Cron | scripts en `cron_jobs/` por SO/scheduler | no distribuido |

**Multi-tenancy: NO nativa.** Existe `Empresa` + `IntegranteEmpresa` (`seguridad/models.py:432`) pero **no está enlazado** a los datos de WhatsApp/CRM. No hay row-level security.

---

## 3. Catálogo funcional por app

### 3.1 `whatsapp/` — núcleo de mensajería + CRM

**Transporte (factory `get_whatsapp_service(sesion)`):**
- **Baileys** (`services.py` → Node.js): QR, envío texto/media, typing, transcripción audio (Whisper), sync contactos, foto de perfil del contacto.
- **Meta Cloud API** (`meta/whatsapp.py`): texto, plantillas, media, interactive (buttons/list/cta_url), guardas de quality_rating y ventana 24h, sanitización de headers.
- **Instagram / Messenger** (`meta/instagram.py`): DMs.

**Webhooks entrantes:** `meta_webhook` (HMAC, identificación por `phone_number_id` único), `webhook_handler` (Baileys), `instagram_webhook`, `messenger_webhook`. Todos normalizan a un shape común → `process_incoming_message()`.

**Pipeline de mensaje entrante** (`procesar_mensaje.py`): dedup idempotente por `mensaje_id_externo`, detección de canal, captura referral CTWA (`ctwa_clid`/`ad_id`/`campaign_id`), auto-crea conversación, round-robin opcional, reporte CAPI lead, guarda media + transcribe audio, broadcast WebSocket, trazas granulares.

**Modelos clave:**
- `SesionWhatsApp` — raíz (proveedor, modo_bot ninguno/tradicional/ia, agente_ia, departamento_default, round-robin, grupo_agenda, mensajes de sistema).
- `Contacto` + `PerfilContacto` (memoria persistente cross-conversación, rolling window 3000 chars).
- `ConversacionWhatsApp` — estado, clasificación, asignación, sentimiento, CAPI, referral, reconexión por plantilla, snapshot `proveedor_atencion`. Método `cerrar()` unificado (resumen IA + despedida).
- `MensajeWhatsApp` — tipos texto/media/ubicación, estado_envio (sent→delivered→read→failed), flags ia_generado/automatico.
- `EstadisticasConversacion`, `HistorialAsignacion`, `MenuRapidoSesion` (respuestas rápidas por sesión).
- `PlantillaWhatsApp` (Meta templates: CRUD, estado, categoría), `TarifaPlantillaMeta` (precios por país/categoría).
- `EtiquetaContacto`, `PipelineVenta` + `EtapaPipeline` + `ConversacionEnPipeline` + `ComentarioCardPipeline` + `HistorialEtapaPipeline` (kanban).
- `Campana` + `EnvioCampana` (broadcast texto/plantilla/media, segmentación por etiquetas/canal/clasificación, scheduling con ventana + throttle/min, tracking respuesta).
- `HorarioAtencion` + `ExcepcionHorario` (business hours + feriados).
- `PixelMeta` + `EventoCAPI` (Conversions API: lead/purchase con dedup).
- `DisponibilidadAgente` + `AsignacionAutomatica` (round-robin / least-loaded).
- `WebhookSaliente` + `EntregaWebhookSaliente` (integraciones outbound con HMAC).
- `TrazaMensajeIA`, `MetaWebhookHit`, `EventoMetaRecibido` (auditoría).

**API REST v1** (`api_rest.py`, auth X-API-Key, 120 req/min): contactos, conversaciones, mensajes, asignar, etapa pipeline, enviar, etiquetas, evento CAPI, stats campaña.

**WebSocket** (`consumers.py`): `ChatConsumer` (mensajes + typing), `SessionConsumer` (QR/estado), `SessionRoomConsumer` (listado en vivo).

**Dashboards:** analytics, supervisión (KPI agentes), trazas IA, pipeline.

### 3.2 `crm/` — motor de chatbot + IA

**Motor de flujo** (`motor_flujo_chatbot.py`): nodos `menu/respuesta/pregunta/http/funcion/condicional/set_variable/cta_url/ubicacion/handoff/agenda_turno/loop/fin`. Enrutamiento a departamento por keyword/número/default/meta-menú. Anti-rebobinado (ignora botones viejos), reset configurable, validaciones de entrada (email/cédula EC/RUC/etc.), expresiones `{{variables.x}}` + loops Jinja, máx 25 nodos/turno, handoff manual y por timeout.

**Funciones registradas** (`funciones_chatbot.py`): `cotizar_aria`, `cotizar_am`, `cotizar_am_multiple` (integraciones cotizador seguros/asistencia médica).

**Endpoints/credenciales API reutilizables** para nodos HTTP (`EndpointApiChatbot`, `CredencialApiChatbot`).

### 3.3 `agents_ai/` — agentes LLM

- **Tipos:** Consultor (RAG + tool-calling), Resumidor (resumen + sentimiento 7 categorías), Auditor (analiza salud del agente y propone mejoras de prompt).
- **Providers:** Gemini, OpenAI, Claude (default `claude-haiku-4-5`), con `bind_tools`.
- **RAG híbrido:** BM25 + FAISS (MMR) con dedup, cache FAISS en memoria invalidada por mtime. FAQ inyectadas literal, APIs externas cacheadas sin embeddings, contexto estático directo si <40KB.
- **Tool-calling:** loop acotado a 3 iteraciones; tools estáticas (`agregar_al_pedido`, `consultar_producto`) + dinámicas (`HerramientaAgente`).
- **Memoria:** `DjangoChatMessageHistory` (tabla `message_store`).
- **Humanización:** burbujas, delays lectura/tipeo, detección de ánimo, persona configurable (preset/temperatura/tono).
- Config fina por agente (k FAISS, context chars, history turns, snippets, output tokens).

### 3.4 `agenda/` — turnos

Modelos `GrupoAgenda`, `Recurso`, `HorarioLaboral`, `ExcepcionAgenda`, `Servicio`, `Turno` (estados pending/confirmed/cancelled/rescheduled/fulfilled/no_show; origen chatbot/manual/api). Slots on-the-fly, validación de overlaps, reagendamiento con FK al turno anterior, recordatorios N horas antes. Se integra al chatbot vía nodo `agenda_turno` (sub_action reservar/cancelar/reagendar) + `grupo_agenda` de la sesión.

### 3.5 `voz/` — voz (incompleto)

Esqueleto: `LlamadaVoz`, `MensajeVoz` (Twilio/Jambonz/WebRTC). STT/TTS **no implementados**. Demo Piper TTS en `scripts/`.

### 3.6 `meta/` — integración Meta

`whatsapp.py` (Cloud API), `instagram.py`, `capi.py`, credenciales/perfiles/validación de firma.

### 3.7 Plataforma base

- `core/` — `ModeloBase` (soft-delete `status` + auditoría), `ConsultasAjax`, middleware request/config, validadores, `crypto.py` (Fernet).
- `seguridad/` — `Modulo`/`GroupModulo`/`ModuloGrupo` (permisos por URL/menú), `AudiUsuarioTabla` (auditoría GenericFK), `ErrorLog`, `Notificacion` (+WebPush), `CredencialMetaApp` (app-level cifrado), `SessionUser`/`UsuarioConectado`, backups DB (`view_databasebackup.py`).
- `autenticacion/` — `Usuario` (AbstractUser extendido), login, recuperación de clave. **Sin MFA.**
- `cron_jobs/` — campañas, reconexión sesiones, recordatorios turnos, despedidas, mensajes programados, aprendizaje conversaciones.

---

## 4. Fortalezas diferenciales

1. Doble transporte WhatsApp sin código duplicado + snapshot de proveedor por conversación.
2. IA híbrida (agente LLM con RAG **o** flujo tradicional) por sesión.
3. Atribución de anuncios Click-to-WhatsApp + CAPI (lead/purchase) — pocos competidores PyME lo traen.
4. Reconexión por plantilla (extiende ventana 24h de forma trazable).
5. Memoria persistente del contacto entre conversaciones.
6. Auditoría granular end-to-end (trazas IA + webhook hits + eventos Meta).
7. Pipeline kanban + campañas segmentadas + agenda de turnos integrada al bot.

---

## 5. Gaps competitivos (vs Wati / Respond.io / Chatwoot)

### Inbox / productividad de agente
- ❌ **Snooze / posponer** conversación.
- ❌ **Detección de colisión** (dos agentes en el mismo chat a la vez).
- 🟡 Respuestas rápidas: existen por sesión (`MenuRapidoSesion`) pero no biblioteca global con `/atajos`.
- 🟡 Estados de conversación: solo activo/cerrado; falta "pendiente/resuelto".
- ❌ SLA con escalamiento automático (se miden tiempos, no se accionan).

### Contactos / CRM
- 🟡 **Campos personalizados** flexibles (hoy solo JSON `referral_meta`).
- 🟡 Deals/oportunidades como entidad propia (hoy se aproxima con pipeline sobre conversación).

### Campañas
- ❌ **Drip / secuencias** (mensajes en serie temporizados).
- 🟡 **Opt-out / consentimiento** formal (hoy solo `estado` activo/cerrado) — riesgo de compliance.

### Canales
- ❌ Email, ❌ SMS, ❌ **widget web / live chat SDK**.

### Integraciones
- ❌ Conectores nativos Zapier/Make, HubSpot/Salesforce (sí hay webhooks + API genéricos).
- 🟡 Documentación pública de API (DRF instalado, sin OpenAPI/Swagger).

### SaaS / negocio
- ❌ **Multi-tenancy real** (aislamiento por organización + RLS).
- ❌ **Billing / suscripciones / cuotas por plan** (existe `ConsumoTokenIA` para tokens IA, no para mensajes/contactos).
- ❌ Onboarding / wizard de alta.
- 🟡 i18n (hardcode `es-ec` / `America/Guayaquil`).

---

## 6. Riesgos técnicos / deuda

| Riesgo | Ubicación | Impacto |
|---|---|---|
| Secretos en `credenciales.json` + SendGrid key en claro | `settings.py` | seguridad producción |
| Email de debug hardcodeado | `crm/funciones_chatbot.py` (`COTIZADOR_DEBUG_EMAIL`) | fuga/ruido en prod |
| Casi sin tests | `**/tests.py` | regresiones |
| Posibles N+1 en listados | consultas sin `select_related` | rendimiento |
| Webhooks salientes sin backoff exponencial | `WebhookSaliente` | entregas colgadas |
| Media sin TTL ni particionado | `whatsapp_media/` | disco |
| Cron por SO, no distribuido | `cron_jobs/` | escalado |
| Sin monitoreo (Sentry/health checks) | global | operación |
| Voz incompleta (STT/TTS) | `voz/` | feature a medias |

---

## 7. Roadmap propuesto para "CRM WhatsApp competitivo"

**Fase 1 — Pulido de inbox (rápido, alto impacto percibido)**
- Detección de colisión (lock visible "X está respondiendo").
- Snooze + estado pendiente/resuelto.
- Biblioteca global de respuestas rápidas con `/atajos`.
- Campos personalizados de contacto.

**Fase 2 — Compliance + campañas**
- Opt-out / consentimiento formal + footer de baja.
- Drip / secuencias.
- SLA con alertas/escala automática.

**Fase 3 — SaaS (habilita venta multi-cliente)**
- Multi-tenancy: `Organizacion` + `tenant_id` en queries + RLS PostgreSQL.
- Billing (Stripe), planes, metering de mensajes/contactos, cuotas.
- Onboarding wizard + secrets a variables de entorno/vault.

**Fase 4 — Expansión**
- Widget web / live chat, canal email, SMS.
- API pública documentada (OpenAPI) + conectores Zapier/Make.
- Monitoreo (Sentry, health checks), suite de tests, cron distribuido (Celery).

---

## 8. Conclusión

El producto tiene **profundidad funcional superior al promedio PyME** (IA, atribución de anuncios, doble transporte, agenda). El trabajo pendiente no es de features de chat sino de **plataforma**: tenancy, billing, compliance y pulido de inbox. Con la Fase 1 + Fase 3 ya sería vendible como SaaS competitivo en el segmento PyME/agencias de LATAM.
