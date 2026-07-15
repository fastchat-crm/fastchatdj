# Megaestudio omnicanal — CRM aplicado a WhatsApp, Instagram, TikTok y Facebook

> Fecha: 2026-07-14. Estudio de arquitectura + brechas + plan para completar Facebook
> (Messenger, comentarios de página, publicaciones) y elevar el producto al nivel de
> GoHighLevel / ManyChat — e incluso superarlo.
> Fuentes: código real del repo (4 auditorías), `.ai/docs/funcionalidades.md`,
> `.ai/docs/instagram_comentarios.md`, `.ai/docs/tiktok_integracion.md`, `meta/README.md`,
> benchmark web GHL/ManyChat 2025-2026.

---

## 1. Conclusión ejecutiva

El CRM está **mucho menos acoplado a WhatsApp de lo que sugiere el naming**. La
arquitectura multicanal ya existe y funciona: un canal nuevo = `SesionWhatsApp(proveedor=X)`
+ `Config<Canal>` (OneToOne) + sender que hereda de `ServicioCanalBase` + webhook que
traduce al shape interno y llama `process_incoming_message`. Desde ahí todo es gratis:
contacto, conversación, opt-out, motor de flujo/IA, asignación de asesores, bandeja
WebSocket, secuencias, growth links, analytics.

**Facebook es el canal más barato de completar**: el backend de Messenger ya está
operativo end-to-end (`ConfigMessenger`, `MessengerService`, `messenger_webhook`).
Falta solo la capa de control (app `facebook/` espejo de `instagram/`), el campo de
webhook `feed` para comentarios de página, publicaciones y el alta de `facebook` en
`CANALES_COMENTARIO`. Estimación: es el mismo patrón que ya se ejecutó dos veces
(instagram 2026-07-08, tiktok 2026-07-08).

Contra GoHighLevel, fastchat ya gana en profundidad de IA conversacional (RAG por
agente, memoria, auditor, trazas, juez LLM) y pierde en: email/SMS como canales, social
planner (publicar), calendarios de reserva pública, webchat propio y white-label SaaS.
Contra ManyChat, la paridad de features de engagement ya se construyó (secuencias,
segmentos, growth links, reglas comentario→DM); faltan triggers de Stories/Live y la
API pública subscriber-céntrica.

---

## 2. Estado actual por canal (matriz real, auditada 2026-07-14)

| Capacidad | WhatsApp Baileys | WhatsApp Meta | Instagram | Messenger (FB) | TikTok | Facebook Página |
|---|---|---|---|---|---|---|
| Config por sesión | implícita | `ConfigMeta` (models.py:1586) | `ConfigInstagram` (:2472) | `ConfigMessenger` (:2526) | `ConfigTikTok` (:2498) | — (usaría ConfigMessenger) |
| Proveedor en dispatcher | ✅ | ✅ | ✅ | ✅ `MessengerService` | ✅ `TikTokService` | n/a |
| Webhook entrante | ✅ | ✅ HMAC | ✅ HMAC | ✅ HMAC (`messenger_webhook`, urls.py:167) | ✅ sin HMAC (hardcoded True, tiktok_webhook_view.py:91) | ❌ campo `feed` no procesado |
| DMs entrantes → pipeline completo | ✅ | ✅ | ✅ | ✅ | ⏳ beta | ✅ (= Messenger) |
| Envío texto | ✅ | ✅ | ✅ | ✅ | ✅ (por validar sandbox) | ✅ |
| Envío media | ✅ | ✅ | ✅ (media_url público) | ✅ | ❌ stub | ✅ |
| App de control / UI sesiones | tablero | tablero + OAuth | `/instagram/sesiones/` | ❌ **no hay app** | `/tiktok/sesiones/` | ❌ |
| Inbox conversaciones por canal | ✅ | ✅ | ✅ | ❌ (solo bandeja general) | ✅ (vacío) | ❌ |
| Comentarios (recepción) | — | — | ✅ webhook `comments` | ❌ | ❌ (fase 2) | ❌ |
| Comentarios (responder/ocultar/DM) | — | — | ✅ | ❌ | ❌ (view rechaza canal ≠ instagram, view_comentarios.py:92) | ❌ |
| Reglas comentario→DM | — | — | ✅ `/instagram/reglas-comentarios/` | ❌ | ❌ | ❌ |
| Publicaciones (grilla live) | — | — | ✅ `/instagram/publicaciones/` | ❌ | ❌ | ❌ |
| Publicar/programar posts | — | — | ❌ | ❌ | ❌ | ❌ |
| Centro de canal | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| Selector global navbar | ✅ | ✅ | ✅ chip | ⚠️ sin chip propio | ✅ chip | ❌ |

`CANALES_COMENTARIO` (models.py:2701) solo admite `instagram`/`tiktok` — hay que sumar `facebook`.

### Selector global de sesión (nota pedida por el usuario)

Al loguear, la sesión activa vive en `request.session[WA_SESION_ACTIVA_KEY]`
(`core/funciones.py:757`, vista `/whatsapp/sesion-activa/`). El context processor
`selector_sesion` (`whatsapp/context_processors.py:5`) ya lista sesiones de **todos**
los proveedores sin filtrar — una sesión `proveedor='messenger'` aparecería sola.
Lo único pendiente para Facebook: chip de filtro + ícono en
`static/stylenew/selector_sesion_global.{css,js}` y badge en las cards del tablero
(`whatsapp/templates/whatsapp/sesiones/_card.html`), igual que se hizo con TikTok.

---

## 3. Reutilización del CRM por subsistema (veredictos con evidencia)

| Subsistema | Veredicto | Evidencia |
|---|---|---|
| Bandeja de chat (vista + `ChatConsumer` + WebSocket) | **REUTILIZABLE** — ya multicanal | `conversacionesView(canal_fijo=...)` (view_conversaciones.py:301-316); IG/TikTok ya la reusan con wrapper |
| Asignación de asesores | **REUTILIZABLE** | pool por sesión vía `PerfilSesionWhatsApp` (helpers_asignacion.py:78-97), agnóstico al proveedor; aviso vía service abstracto |
| Modelos (Contacto/Conversación/Mensaje/campañas/segmentos/pipeline) | **REUTILIZABLE** | `Contacto.canal`+`external_id`+`meta_user_id` (models.py:294-315), `origen_canal`/`proveedor` en conversación (:568, :600), `Campana.canales` JSON (:2285) |
| Agentes IA (`AgenteConsultor`, RAG, memoria) | **ADAPTABLE→REUTILIZABLE** | devuelve solo texto; ya canal-aware (`_canal_conversacion`, agente_consultor.py:363-376); atado nominalmente a `ConversacionWhatsApp` (:11, :719) |
| Motor de flujo tradicional | **ADAPTABLE** | transporte abstraído y degrada botones a texto numerado si no es Meta (motor_flujo_chatbot.py:666, :705); pero importa `MensajeWhatsApp`/`TrazaMensajeIA` (:636, :554) y usa `contacto.from_number`/`session.numero` como identidad (:591-608) |
| Comentarios sociales + reglas | **REUTILIZABLE** | `ComentarioSocial`/`ReglaComentario` ya tienen campo `canal`; solo ampliar choices y acciones por canal |

### Grietas técnicas detectadas (deuda a corregir antes/junto con Facebook)

1. **`Contacto.save()` fuerza identidad telefónica** (whatsapp/models.py:380-386):
   `from_number = f"{numero}@s.whatsapp.net"` y deriva `contacto_numero` de dígitos.
   Riesgo de corromper IGSID/PSID/open_id. Corregir: aplicar la normalización solo
   cuando `canal == 'whatsapp'`.
2. **Motor de flujo acoplado por nombre**: `_persistir_mensaje_saliente` crea
   `MensajeWhatsApp` con `remitente=self.session.numero` — para canales sociales el
   "número" no existe; mapear a `session_id`/`external_id`.
3. **Webhook TikTok sin HMAC** (`tiktok_webhook_view.py:91`, `firma_valida=True`
   hardcodeado) — resolver al validar contra sandbox.
4. **Posible duplicación `InstagramService`**: el completo vive en `meta/instagram.py`
   pero el dispatcher importa vía shim `whatsapp/services_instagram.py`
   (services.py:666). Verificar que el shim solo re-exporte y no diverja.
5. **Versión Graph hardcodeada**: `meta/instagram.py:14` y `meta/capi.py:30` usan
   `v21.0` en vez de `build_graph_url()`/`settings.META_API_VERSION` (v22.0).
6. **Suscripción de campos Meta**: `POST /{waba_id}/subscribed_apps` no manda
   `subscribed_fields` explícitos; para comentarios FB habrá que suscribir `feed`
   en el producto Messenger/Pages de la Meta App (manual, como se hizo con `comments` de IG).

---

## 4. Plan Facebook (Páginas): conversaciones Messenger + comentarios + publicaciones

Patrón idéntico al ejecutado para `instagram/` — capa de control sin modelos propios.
El backend Messenger ya existe; el 70% del trabajo es UI + un campo de webhook.

### Fase F1 — App `facebook/` (capa de control, espejo de `instagram/`)

| Pieza | Qué hacer | Referencia a clonar |
|---|---|---|
| `facebook/apps.py`, `urls.py` | registrar app + montar `/facebook/` en `urls_sistema` | `instagram/urls.py` |
| `/facebook/sesiones/` | conectar página: token de página → autodetect `page_id`/`page_name` vía `/me/accounts`, probar conexión, activar/suspender. Crea `SesionWhatsApp(proveedor='messenger', session_id='messenger-<page_id>')` + `ConfigMessenger` | `instagram/view_cuentas.py` + `funciones_cuentas.py` (autodetect ya trae page_id) |
| `/facebook/conversaciones/` | wrapper `conversacionesView(canal_fijo='messenger', template='facebook/conversaciones/listado.html')` | `instagram/view_conversaciones.py` |
| `/facebook/centro/` | wrapper `_render_centro(request, 'facebook')` + entrada en `GUIAS_CANAL` | `instagram/view_centro.py`, `whatsapp/view_centro.py` |
| Tablero de canales | pane `_pane_facebook.html` en el modal "Nueva conexión" + card de primera clase en `_card.html` (badge, page_name desde `config_messenger`, kebab con links) | `_pane_instagram.html` |
| Selector global | chip Facebook + ícono en `selector_sesion_global.{css,js}` | chip TikTok |
| Seed | sección Facebook en `seed_modulos` (la corre el developer) | secciones IG/TikTok |
| Doc | `facebook/README.md` + actualizar hoja `conectar-instagram-tiktok` (o crear `conexion_facebook.html`) | doc-sync rule |

Nota: el proveedor ya se llama `messenger` en `PROVEEDORES_SESION` — no crear un
proveedor `facebook` duplicado; la app `facebook/` es solo la URL/branding de cara al
usuario, filtrando `proveedor='messenger'`.

### Fase F2 — Comentarios de página FB (paridad con IG)

1. `CANALES_COMENTARIO` += `('facebook', 'Facebook')` (models.py:2701) y choices de
   `ReglaComentario.canal`.
2. Webhook: en `_procesar_post_social` (meta_social_webhook_view.py) procesar
   `field == 'feed'` con `value.item == 'comment'` (verbo add/edited/remove) →
   `guardar_comentario_facebook` en `funciones_comentarios.py` (mismo shape que IG:
   `comment_id`, `post_id`→`media_id`, `from`, `message`; el payload de `feed` **sí trae
   `created_time`** — usarlo en `fecha_comentario`, mejora sobre IG).
3. Acciones Graph: `POST /{comment_id}/comments` (responder), `POST /{comment_id}`
   `is_hidden` (ocultar), private reply Messenger `POST /{page_id}/messages` con
   `recipient.comment_id` (ventana 7 días) — agregar métodos a `MessengerService`
   (hoy hereda los de IG cuyos endpoints difieren levemente para páginas).
4. Levantar el candado de `_procesar_accion` (view_comentarios.py:92) que hoy rechaza
   canal ≠ instagram → despachar por canal.
5. `/facebook/comentarios/` (wrapper `canal_fijo='facebook'`) + `/facebook/reglas-comentarios/`
   → el motor `procesar_reglas_comentario` funciona sin cambios (ya es por canal).
6. Meta App: suscribir campo `feed` del producto Webhooks de la página (checklist admin).

### Fase F3 — Publicaciones de página FB

- `/facebook/publicaciones/`: grilla live `GET /{page_id}/posts` (fields
  `id,message,full_picture,permalink_url,created_time,comments.summary(true),likes.summary(true)`)
  — espejo de `instagram/view_posts.py` con `listar_publicaciones` nuevo en `MessengerService`.
- Modal de moderación por post reutilizando `_comentarios_post.html` (cruza por `media_id`).

### Fase F4 — Correcciones transversales que Facebook destapa

- Fix `Contacto.save()` (grieta #1) — necesario porque los PSID de Messenger son
  numéricos largos y hoy quedarían con sufijo `@s.whatsapp.net`. Verificar cómo llegan
  hoy los contactos IG (mismo bug latente).
- Campañas: `Campana.canales` ya acepta `messenger` (models.py:2285) — probar envío
  masivo respetando la política de 24h de Messenger (message tags si aplica).

---

## 5. TikTok — pendientes (bloqueado por aprobación beta)

Ya pre-construido: `ConfigTikTok`, sender texto, webhook, UI de pre-registro, inbox.
Al aprobar la Business Messaging API:

1. OAuth completo + refresh de tokens (cron en `cron_jobs/`, campos `refresh_token`/`token_expira_en` ya existen).
2. Validar shapes de payload contra sandbox + activar HMAC real (grieta #3).
3. `send_media_message` real (hoy stub).
4. Comentarios fase 2: polling `comment/list` por cron + `reply/create` + ocultar; reglas comentario→DM (canal ya soportado por el motor).
5. `/tiktok/publicaciones/`.

---

## 6. Benchmark GoHighLevel / ManyChat — dónde estamos y qué falta

### Ya en paridad o mejor (no invertir más aquí)

- Inbox omnicanal en vivo (WebSocket, presencia, anticolisión) — paridad GHL Conversations.
- IA conversacional: **superior a GHL Conversation AI** en profundidad (RAG híbrido BM25+FAISS, memoria por agente, FAQs curables, auditor, juez LLM, trazas end-to-end con costo por token, humanización). GHL no expone nada comparable.
- Motor de flujos visual (13 nodos, generación por IA) — paridad workflows GHL / flows ManyChat.
- Secuencias drip, segmentos guardados, growth links con QR, reglas comentario→DM IG — paridad ManyChat (construido 2026-07-14).
- Pipelines Kanban + CAPI Purchase al ganar — paridad GHL Opportunities (con mejor atribución CTWA).
- Agendamiento conversacional (nodo + tools + recordatorios con confirmar/cancelar sin LLM) — paridad funcional con calendarios GHL en el caso de uso por chat.
- Campañas masivas con throttle/tier, plantillas Meta con IA, opt-out automático, API REST v1, webhooks salientes firmados HMAC.

### Brechas vs GHL/ManyChat (backlog priorizado)

| # | Brecha | Qué tienen ellos | Esfuerzo | Impacto |
|---|---|---|---|---|
| 1 | **Facebook completo** (plan §4) | GHL y ManyChat: Messenger + comment-to-DM en posts FB | Bajo (patrón repetido) | Alto — cierra la promesa omnicanal Meta |
| 2 | **Triggers IG avanzados**: Story Reply, Story Mention, Live Comments | ManyChat core | Medio (webhook fields adicionales + tipos en `ReglaComentario`) | Alto — diferenciador ManyChat nº1 |
| 3 | **Nodo webhook/NLU en motor de flujo** (contrato: POST contexto → lista de mensajes) | GHL webhook step / ManyChat Dev Tools | Medio | Alto — extensibilidad |
| 4 | **API pública subscriber-céntrica** (tags/campos por nombre, estilo ManyChat) | ManyChat API | Medio | Medio-alto — integraciones |
| 5 | **Webchat propio embebible** (widget → conversación en el inbox, canal `webchat`) | GHL chat widget all-in-one | Medio | Alto — capta leads sin nº de teléfono |
| 6 | **Social planner** (programar posts FB/IG/TikTok con calendario + IA de contenido) | Solo GHL; ManyChat no publica | Medio-alto | Medio — adyacente pero visible en ventas |
| 7 | **Email como canal** (broadcasts + pasos de email en secuencias; ya existe mailing masivo en `seguridad/` — unificarlo al contacto/segmento) | GHL core | Medio | Medio |
| 8 | **Calendario de reserva pública** (link de booking self-service sobre `agenda/`) | GHL calendars | Medio | Medio |
| 9 | **Click-to-Messenger/IG Ads → flow** (ya hay CTWA para WhatsApp; extender atribución de ads a IG/Messenger) | ManyChat Ads JSON, GHL Ad Manager | Medio | Medio |
| 10 | **Reputación/reviews** (Google/FB: pedir reseña post-venta, responder con IA) | GHL adyacente | Alto | Bajo-medio |
| 11 | **White-label / SaaS mode multi-tenant con rebilling** | GHL plataforma ($497/mes) | Muy alto | Estratégico a largo plazo (ya existe `Empresa` multi-empresa como base) |
| 12 | Voice AI (agente que contesta llamadas) | GHL AI Employee | Alto | `voz/` ya tiene el pipeline STT→LLM→TTS y webhook Twilio — es el germen; falta RAG + UI |

Descartados como no-core: funnels/websites, cursos/membresías, comunidades (adyacentes
GHL fuera del foco mensajería+CRM).

### Dónde podemos SUPERAR a GHL (apuestas)

1. **IA con trazabilidad total**: trazas por mensaje con tokens/costo + auditor + juez —
   venderlo como "IA auditable"; GHL es caja negra.
2. **Comment-to-DM con IA**: hoy las reglas son por keywords (paridad ManyChat); agregar
   modo "clasificar con LLM" (GHL lo hace con Workflow AI) reutilizando `AgenteConsultor` — esfuerzo bajo.
3. **Dual-provider WhatsApp** (Baileys + Cloud API en el mismo inbox): ni GHL ni ManyChat lo ofrecen.
4. **Precio/soberanía**: proveedores IA intercambiables (Gemini/OpenAI/Claude/Ollama/DeepSeek/Huawei) vs lock-in de GHL.

---

## 7. Nota sobre el "MEGA PROMPT" externo

El documento externo propone modelos nuevos (`SocialAccount`, `Contact`, `Conversation`,
`Workflow`), DRF + Celery + Docker. **Se descarta como arquitectura**: implicaría la
reestructura ya rechazada; el equivalente real ya existe (`SesionWhatsApp`+`Config*`,
`ConversacionWhatsApp` multicanal, cron_jobs en vez de Celery). Se absorben sus ideas
válidas, todas mapeadas en este estudio: integración Facebook Pages (§4), webhooks por
canal (ya existen), multi-sesión por empresa (ya existe), bandeja omnicanal WebSocket
(ya existe).

---

## 8. Orden de ejecución recomendado

1. **F1+F2 Facebook** (app + comentarios feed) — cierra omnicanal Meta con esfuerzo mínimo.
2. **Fix `Contacto.save()`** — se hace junto con F1 (lo destapa Messenger).
3. **F3 publicaciones FB** + **brecha #2 triggers IG Stories/Live** — paquete "engagement Meta".
4. **Brechas #3 y #4** (nodo webhook + API pública) — backlog ya acordado.
5. **Webchat (#5)** — nuevo canal de captación.
6. TikTok al aprobar beta (§5).
7. Social planner, email, booking público (#6-8) — capa GHL adyacente.
