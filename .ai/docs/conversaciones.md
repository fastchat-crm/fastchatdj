# Módulo Conversaciones WhatsApp

Referencia técnica de las dos vistas espejadas que sostienen el chat agéntico:
`/whatsapp/conversaciones/` (abiertas) y `/whatsapp/conversaciones-finalizadas/`.
Cubre vistas, templates, JavaScript de cliente, WebSockets y reglas de negocio.

---

## 1. Overview

El módulo gestiona conversaciones de WhatsApp en vivo y su histórico. Vive en
dos vistas paralelas que comparten layout (`base_chat.html`) y partials, pero
difieren en queryset, footer y acciones permitidas.

**Vistas:**
- `whatsapp/view_conversaciones.py` → `conversacionesView(request, canal_fijo=None)` — chats activos
  (`estado_conversacion=0`). Con `canal_fijo` ('instagram'/'tiktok') el mismo inbox se acota a las
  sesiones de ese proveedor: `/instagram/conversaciones/` y `/tiktok/conversaciones/` son wrappers
  directos (2026-07). Por eso el JS de `listado.html` usa `{{ ruta }}` (request.path) y NO URLs
  hardcodeadas a `/whatsapp/conversaciones/` — mantener esa regla al agregar acciones.
  Desde 2026-07-09 el filtro base del listado y el badge `total_sin_leer` usan el queryset
  `sesiones` (ya acotado por `canal_fijo`), NO `sesiones_visibles(...)` directo: antes, un canal
  sin sesiones (`sesion_seleccionada=None`, caso TikTok) mostraba conversaciones de TODOS los
  canales. El modal `#modalSinSesiones` de `listado.html` también es per-canal (copy + link a
  `/instagram/sesiones/` o `/tiktok/sesiones/`). Mantener ese scoping al agregar filtros.
- `whatsapp/view_conversaciones_finalizadas.py:35` → `conversacionesFinalizadasView`
  — chats cerrados (`estado_conversacion=1`).

**Proveedores de transporte** soportados (snapshot en `ConversacionWhatsApp.proveedor_atencion`):
Meta Cloud API, Baileys (Node), Instagram DM, Messenger. Selección vía dispatcher
`get_whatsapp_service(sesion)` (`whatsapp/services.py:604`).

**Dataflow de alto nivel:**

```
ENTRANTE
Meta/Baileys → POST /whatsapp/meta_webhook/  ó  /whatsapp/webhook_handler/
  → procesar_mensaje.process_incoming_message()
  → persiste MensajeWhatsApp + actualiza Conversacion + EstadisticasConversacion
  → channel_layer.group_send → ChatConsumer + SessionRoomConsumer
  → frontend recibe HTML por WS → reemplaza DOM

SALIENTE
JS (composer) → POST /whatsapp/conversaciones/ action=send
  → get_whatsapp_service(sesion).send_text_message() / send_media_message()
  → API externa
  → persiste MensajeWhatsApp con agente=request.user, ia_generado=False
  → JsonResponse con HTML parcial → JS lo inyecta en #mensajes-container
```

**URLs** (`whatsapp/urls.py:39-45`, `95-99`):

| Ruta | Vista |
|------|-------|
| `/whatsapp/conversaciones/` | `conversacionesView` |
| `/whatsapp/conversaciones-finalizadas/` | `conversacionesFinalizadasView` |
| `/whatsapp/webhook_handler/` | Webhook entrante Baileys |
| `/whatsapp/meta_webhook/` | Webhook entrante Meta |

WebSocket routes (`whatsapp/routing.py:4-7`):

| Ruta | Consumer | Grupo channel layer |
|------|----------|---------------------|
| `ws/chat/<conversacion_id>/` | `ChatConsumer` | `chat_<id>` |
| `ws/session/<session_id>/` | `SessionConsumer` | `whatsapp_session_<sid>` |
| `ws/sessionroom/<session_id>/` | `SessionRoomConsumer` | `whatsapp_sessionroom_<sid>` |

---

## 2. Modelos clave

Solo los campos que tocan estas vistas. Catálogo completo en `whatsapp/models.py`.

### `SesionWhatsApp` (`models.py:60`)
- `proveedor` — `'baileys'|'meta'|'instagram'|'messenger'`. Determina dispatcher.
- `es_meta` / `es_baileys` — properties helper. Usar siempre estas, nunca campos crudos.
- `numero` — número WhatsApp visible (también discrimina mensajes salientes).
- `session_id` — UUID Baileys o `phone_number_id` Meta.
- `activo` — pausa toda la sesión (corta webhooks entrantes).
- `min_sesion` — minutos antes de marcar conversación como expirada (default 10).
- `modo_bot` — `'ia'|'tradicional'|'ninguno'`. Define si responde IA o flujo CRM.
- `agente_ia` — FK a `crm.AgentesIA`.
- `config_meta` — OneToOne con `ConfigMeta` (solo para Meta).

### `Contacto` (`models.py:195`)
- `sesion` (FK), `from_number` (`XXX@s.whatsapp.net` Baileys o wa_id Meta),
  `contacto_numero`, `contacto_nombre`, `contacto_foto`.
- `referral_meta` — JSON CTWA (Click-to-WhatsApp ad) si entró por anuncio.

### `ConversacionWhatsApp` (`models.py:398`)
**Estado:**
- `estado_conversacion` — `0=Activa`, `1=Cerrada`. Filtro principal de cada vista.
- `conversacion_finalizada`, `despedida_enviado` — flags auxiliares.

**Tiempos:**
- `fecha_registro` — base para la ventana de gracia de 6h.
- `fecha_fin_conversacion`, `duracion_conversacion`, `fecha_hora_expira`.

**IA / agente:**
- `ai_activo` — true si la IA puede responder. Auto-pausa al asignar humano.
- `asignado_a`, `primer_agente` (FK Usuario).
- `bloquear_cierre` — opta-out del cierre automático por inactividad.

**Análisis post-cierre:**
- `clasificacion` (int 0-5), `sentimiento`, `puntuacion_sentimiento`.

**Atribución:**
- `origen_canal`, `referral_source_type`, `ctwa_clid`, `ad_id`, `campaign_id`.

**Snapshot transporte:**
- `proveedor_atencion` — se congela al crear; aunque la sesión migre, la conv
  mantiene su transporte. No reescribir.

**Manager custom** (`whatsapp/models_querysetmanagers.py:19`):

```python
ConversacionWhatsApp.objects.sin_expirar  # estado_conversacion=0 + no expirada
ConversacionWhatsApp.objects.expirado     # estado_conversacion=1
```

### `MensajeWhatsApp` (`models.py:887`)
- `conversacion` (FK), `remitente` (número), `mensaje`, `tipo` (`texto|imagen|audio|video|documento|sticker|ubicacion|contacto`).
- `archivo` (FileField), `archivo_url`.
- `mensaje_id_externo` — único; sirve de idempotencia ante reintentos del webhook.
- `estado_envio` — `pendiente|enviado|entregado|leido|fallido`.
- `agente` (FK Usuario, quién respondió), `ia_generado` (bool).
- `editado`/`fecha_edicion`, `eliminado`/`fecha_eliminacion`.
- `leido`, `fecha_leido`.

### `PlantillaWhatsApp` (`models.py:1371`) + `ConfigMeta` (`models.py:1251`)
Solo lo que toca el flujo de plantillas en finalizadas:
- `nombre`, `idioma`, `categoria` (`UTILITY|MARKETING|AUTHENTICATION`).
- `cuerpo`, `footer`, `header_tipo` (`NONE|TEXT|IMAGE|VIDEO|DOCUMENT`), `header_contenido`.
- `variables_json`, `botones_json`.
- `estado_meta` — solo se listan `'APPROVED'`.
- `veces_enviada` — telemetría de uso.
- `ConfigMeta.access_token` (encriptado), `phone_number_id`, `waba_id`.

### Constantes (`models.py:357`, `377`)

```python
ESTADOS_CLASIFICACION = (
    (0, 'Sin Clasificar'), (1, 'Lead'), (2, 'Prospecto'),
    (3, 'Oportunidad'),    (4, 'Cliente'), (5, 'No Interesado'),
)

SENTIMIENTO_CHOICES  # muy_positiva / positiva / neutral / tibia / pasiva / negativa / agresiva
```

### Otros relevantes
- `EstadisticasConversacion` (`models.py:952`) — totales agregados por conv.
- `HistorialAsignacion` (`models.py:971`) — auditoría de quién atendió cuándo.
- `PipelineVenta` (`models.py:1651`), `EtapaPipeline` (`models.py:1666`),
  `ConversacionEnPipeline` (`models.py:1690`) — Kanban CRM.
- `TrazaMensajeIA` (`models.py:1109`) — diagnóstico paso a paso del flujo IA.

---

## 3. Vista de conversaciones abiertas

`whatsapp/view_conversaciones.py`. Decoradores `@login_required` + `@secure_module`.

### Helpers definidos al tope del módulo

| Helper | Línea | Devuelve |
|--------|-------|----------|
| `_estadisticas_conversacion(conv)` | 17 | dict con tokens, mensajes (total/cliente/asesor/IA), duración, estado_badge, primer_agente, + control de respuestas. Lo consume el panel `#stats-panel`. |
| `_control_respuestas(conv)` | 100 | `cr_ia`, `cr_agent`, `cr_agentes` (lista anotada por agente con `Count`). |
| `_tokens_conversacion(conv)` | 122 | Suma simple de tokens entrada/salida/total. |

`view_conversaciones_finalizadas.py:17` los re-importa para reutilizar.

### Flujo inicial de la vista

1. Carga sesiones del usuario (`SesionWhatsApp.objects.filter(usuario_id=request.user.id, status=True)`).
2. Resuelve sesión seleccionada vía `leer_sesion_id(request)` o el primer match.
3. Soporte `request.session.pop('contactoId')` — usado al volver de finalizadas tras reactivar.
4. Soporte deep-link `?conv=<token>` (`view_conversaciones.py:168-181`):
   token cifrado con `decrypt_sesion_id`. Si la conv está finalizada → redirige
   a `/whatsapp/conversaciones-finalizadas/?conv=<token>`. Si está activa →
   marca `auto_open_conv_id` para que el JS la abra al cargar.

### Acciones GET (`?action=...`)

| Action | Línea | Propósito | Retorna |
|--------|-------|-----------|---------|
| `ver_mensajes` | 195 | Carga el chat completo + estadísticas + datos del header | JSON `{html, contacto_*, hashed_id, estado_active, es_meta, ...estadisticas}` con `mensajes_partial.html` |
| `ver_estadisticas` | 241 | Solo el bloque de estadísticas (refresh del panel) | JSON con dict de `_estadisticas_conversacion` |
| `cambiar-clasificacion` | 247 | Form modal | JSON + HTML de `form.html` |
| `cambiar-nombre-contacto` | 259 | Form modal | JSON + HTML de `form.html` |
| `asignar-conversacion` | 271 | Form modal con dropdown de agentes (anotados con carga de trabajo) | JSON + HTML de `form.html` |
| `listar_plantillas_meta` | 280 | Lista plantillas `APPROVED` de `sesion.config_meta` | JSON `{plantillas: [...]}` |

### Acciones POST (`action=...`)

| Action | Línea | Mutación principal | Side effects |
|--------|-------|---------------------|--------------|
| `send` | 323 | Persiste `MensajeWhatsApp` con `agente=request.user`, `ia_generado=False` | Llama service según proveedor, registra `primer_agente` si no existe, log |
| `enviar_plantilla_meta` | 403 | Persiste mensaje renderizado con placeholders sustituidos | Solo Meta + plantilla `APPROVED` |
| `cambiar-clasificacion` | 483 | `clasificacion` | Form save + log |
| `cambiar-nombre-contacto` | 497 | `Contacto.contacto_nombre` | Form save + log |
| `asignar-conversacion` | 512 | `asignado_a`, `fecha_asignacion`, **`ai_activo=False`**, `nota_interna` | Crea `HistorialAsignacion` + `Notificacion` al agente; envía mensaje de handoff vía service con `simularEscritura=True` |
| `toggle-bot` | 594 | Invierte `ai_activo` | — |
| `toggle-bloquear-cierre` | 601 | Invierte `bloquear_cierre` | — |
| `reiniciar-flujo` | 608 | Llama `crm.motor_flujo_chatbot.reiniciar_flujo_tradicional()` | Solo si `sesion.modo_bot='tradicional'` |
| `marcar-resuelto` | 633 | `conversacion.cerrar(enviar_despedida=True)` | Resume IA + envía despedida + cierra |
| `terminar-sin-despedida` | 655 | `conversacion.cerrar(enviar_despedida=False)` | Cierra silenciosamente |
| `transcribe_audio` | 665 | Llama `WhatsAppService.transcribe_audio(msg, 'small', lang)` | Whisper local; al terminar broadcast WS |
| `feedback-mensaje` | 675 | Crea `FeedbackMensajeBot`. Si incorrecto + corrección → crea `FaqAgente` aprobada y la agrega al vectorstore FAISS | — |

### Listado (`view_conversaciones.py:762-867`)

**Filtros Q base** (línea 768):

```python
filtros = Q(
    contacto__status=True, status=True,
    contacto__sesion__usuario__id=request.user.id,
    contacto__sesion__status=True,
    estado_conversacion=0,
)
```

**Filtros opcionales por query param:**
- `?sesion=<encrypted_id>`
- `?criterio=<str>` — ICONTAINS sobre `contacto_numero` o `contacto_nombre`
- `?clasificacion=<int>`
- `?sin_responder=1` — Subquery sobre el último mensaje, excluye los que mandó la sesión
- `?mis_conv=1` — `asignado_a=request.user`

**AJAX `?load_conversations=1`** (línea 824): retorna solo el HTML del partial.
Optimización con `select_related('contacto', 'contacto__sesion', 'contacto__sesion__config_meta', 'contacto__sesion__config_baileys', 'asignado_a')` + `.distinct()` (línea 830-841) para evitar N+1.

**Conteo `total_sin_leer`** (línea 815) — badge global en el header.

**Render final** (línea 874): `render(request, 'whatsapp/conversaciones/listado.html', data)`.

### Cierre de conversación

Método `ConversacionWhatsApp.cerrar(*, enviar_despedida=True, ...)` en `models.py:677`. Pasos:

1. Resume vía `AgenteResumidor` (idempotente).
2. Calcula `fecha_fin_conversacion` y `duracion_conversacion`.
3. Si `enviar_despedida`: aplica `ReglaFinConversacion` configurada o el
   `mensaje_despedida` de la sesión. No bloquea si falla envío — deja traza.
4. Marca `conversacion_finalizada=True`, `estado_conversacion=1`.

Disparado por: `marcar-resuelto`, `terminar-sin-despedida`, cron job de
inactividad y `enviar_plantilla_meta` (cuando reactiva).

---

## 4. Vista de conversaciones finalizadas

`whatsapp/view_conversaciones_finalizadas.py`. Misma estructura, filtra
`estado_conversacion=1`, sin `send` directo (el cliente solo puede recibir
plantillas Meta para reanudar el hilo).

### Ventana de gracia 6h (`view_conversaciones_finalizadas.py:19-31`)

```python
HORAS_VENTANA_REACTIVAR = 6

def _bloqueo_reactivar(conversacion):
    if not conversacion.fecha_registro:
        return False, None
    vence_en = conversacion.fecha_registro + timedelta(hours=HORAS_VENTANA_REACTIVAR)
    return timezone.now() > vence_en, vence_en
```

Aplica a tres acciones (`send`, `enviar_plantilla_meta`, `marcar-reactivar`).
Si está bloqueada, la respuesta JSON trae el mensaje al usuario y el frontend
muestra `#bloqueo-reactivar-aviso` con la fecha de vencimiento.

### Acciones GET

| Action | Línea | Diferencia respecto a abiertas |
|--------|-------|-------------------------------|
| `ver_mensajes` | 86 | Añade `reactivar_bloqueada`, `reactivar_vence_en`, `reactivar_horas_ventana`, `es_meta` al payload |
| `ver_resumen_conversacion` | 113 | Render de `modal_resumen_conversacion.html` |
| `cambiar-clasificacion` | 122 | Idem abiertas |
| `listar_plantillas_meta` | 140 | Igual que en abiertas pero el resultado se cachea en JS |

### Acciones POST

| Action | Línea | Comportamiento |
|--------|-------|----------------|
| `send` | 182 | Permitido solo dentro de la ventana 6h (caso raro: agente reactivó manualmente y aún la conv está abierta) |
| `enviar_plantilla_meta` | 257 | Sustituye `{{N}}` server-side con `_render_cuerpo`, llama `service.send_template`, **reactiva la conv** (`estado_conversacion=0`, recalcula `fecha_hora_expira` con `min_sesion`), persiste mensaje, guarda `primer_agente` si vacío, setea `request.session['contactoId']` y devuelve `{reactivada: True, url: '/whatsapp/conversaciones/'}` para que el JS redirija |
| `cambiar-clasificacion` | 365 | Idem abiertas |
| `marcar-reactivar` | 379 | Reset puro: `estado_conversacion=0`, limpia `fecha_fin_conversacion`, `despedida_enviado`, `conversacion_finalizada`, `fecha_hora_expira`, `duracion_conversacion`. Setea `contactoId` en sesión y redirige |

### Listado (`view_conversaciones_finalizadas.py:407-468`)

Filtros adicionales: `?fecha_desde`, `?fecha_hasta`, `?sentimiento`, `?clasificacion`. Usa el manager `ConversacionWhatsApp.objects.expirado` que filtra por `estado_conversacion=1`.

Render: `whatsapp/conversaciones/listado_expirado.html`.

---

## 5. Templates + JavaScript

Bajo `whatsapp/templates/whatsapp/conversaciones/`. Ambas vistas extienden
`base_chat.html`. CSS importado siempre con paths absolutos:

```html
<link rel="stylesheet" href="/static/stylenew/conversacion_plantillas.css">
<link rel="stylesheet" href="/static/stylenew/conversaciones.css">
```

### Tema y template por canal (2026-07-09)

Cada canal tiene **su propio template de inbox** (pedido del usuario: no reutilizar
el mismo HTML). `conversacionesView(request, canal_fijo=None, template=...)` acepta
el template a renderizar; los wrappers pasan el suyo:

| Vista | Template |
|---|---|
| `/whatsapp/conversaciones/` | `whatsapp/conversaciones/listado.html` (branding WhatsApp fijo) |
| `/instagram/conversaciones/` | `instagram/templates/instagram/conversaciones/listado.html` |
| `/tiktok/conversaciones/` | `tiktok/templates/tiktok/conversaciones/listado.html` |

Las copias IG/TikTok nacieron como copia completa del listado de WhatsApp con el
branding baked-in (ícono/toast del canal, "Mensaje entrante de Instagram/TikTok",
link de sesión pausada y modal sin-sesiones apuntando a `/instagram/sesiones/` o
`/tiktok/sesiones/`). Los partials `_modal_*` / `_ci_kebab_portal` y todo el JS
embebido siguen siendo los mismos: **un cambio de lógica compartida (acciones,
WebSocket, composer) hay que replicarlo en las tres copias**; un cambio de diseño
de un canal se hace solo en su copia.

Identidad visual (aplica a las tres, vía layout compartido):

- `base_chat.html` agrega la clase `canal-<canal_fijo>` al `<body>`, cambia el
  `chat-brand-sub` ("Instagram Workspace" / "TikTok Workspace"), el ícono de marca
  (`fa-instagram` / `fa-tiktok`) y el `theme-color`.
- `static/css/whatsapp/chat_tema_canal.css` (cargado siempre en `base_chat.html`)
  redefine sobre `body.canal-instagram` / `body.canal-tiktok` las variables
  `--chat-primary*` y burbujas enviadas, más el gradiente del `.chat-brand-icon`,
  el `.conversacion-item.active` y el fondo del toast `#toast-nuevo-mensaje`
  (cuyo fondo default verde vive en ese CSS, no inline).
- El selector de sesiones muestra 🎵 TikTok (`sesion.es_tiktok`).

Sin `canal_fijo` todo queda igual (verde WhatsApp).

### Layout — tres zonas

| Zona | ID raíz | Contenido |
|------|---------|-----------|
| Sidebar | `#chat-sidebar` | Selector sesión, tabs, filtros, búsqueda, lista |
| Main | `#chat-main` | Header, paneles toggleables, mensajes |
| Composer | `#chat-footer` | Form de envío (abiertas) o panel plantillas (finalizadas) |

### Sidebar (compartido)

- `#sesion-selector` con `.cs-session-indicator` (active / paused).
- Tabs cruzados (Abiertas ↔ Finalizadas) — link normal, no SPA.
- Filtros:
  - Abiertas: chips rápidos (`Todas`, `Pendientes`, `Mías`) + dropdown de etapa.
  - Finalizadas: panel colapsable con fecha desde/hasta, sentimiento, clasificación.
- `#search-conversacion` con debounce 500ms.
- `#lista-conversaciones` se hidrata vía AJAX `?load_conversations=true`.

### Header del chat

| ID | Vista | Función |
|----|-------|---------|
| `#contacto-foto`, `#contacto-nombre`, `#contacto-numero`, `#conv-id-badge`, `#conv-fechas`, `#contacto-hashedId` | ambas | Datos del contacto |
| `#dropdowns-btn`, `#btn-estadisticas`, `#btn-control-respuestas`, `#ver-resumen-btn` | ambas | Acciones secundarias |
| `#bot-toggle-container`, `#resolver-btn`, `#asignado-container`, `#tokens-container`, `#referral-container` | abiertas | Solo durante chat activo |
| `#reactivar-btn` | finalizadas | Reset de estado |

### Paneles colapsables (toggle desde el dropdown)

- `#stats-panel` — total/cliente/agente/IA + tokens entrada/salida + modelo IA + duración.
- `#control-respuestas-panel` — contadores IA vs agente + chips por agente humano.

### Composer

**Abiertas** (`#chat-footer` → form `#form-enviar-mensaje`):
textarea con auto-grow, emoji picker, input de archivo (`#archivo`),
botón plantillas Meta (`#plantillas-btn`). Al enviar, `action=send`.
Al pulsar enviar el JS pausa la IA preventivamente para evitar double-reply.

**Finalizadas** (footer reemplazado):
- `#bloqueo-reactivar-aviso` (oculto por defecto) — alerta amarilla cuando la
  ventana 6h venció. Bloquea cualquier intento de reactivar.
- `#footer-plantillas-row` — texto explicativo + `#plantillas-btn` con badge.
- `#plantillas-panel` desplegable: header, search, lista, form de variables.
  El form se abre cuando la plantilla tiene `{{N}}` en cuerpo/header o
  cuando el header es IMAGE/VIDEO/DOCUMENT (pide URL + filename opcional).

### Partials

| Archivo | Propósito |
|---------|-----------|
| `conversaciones_partial.html` | Wrapper que itera `{% for conversacion in conversaciones %}` y delega |
| `conversacion_item.html` | Card individual: avatar, status dot, badges (plataforma/clasif/IA-OFF/sentimiento/asignado), nombre, snippet, hora relativa, badge no-leído |
| `mensajes_partial.html` | Historial completo. Dos ramas: `msg-out` (agente o IA) y `msg-in` (cliente). Soporta texto, imagen (fancybox), sticker, audio (con botón transcribir), video, documento. Incluye ack states + feedback IA + form de corrección |
| `mensaje_enviado_partial.html` | Render mínimo de un mensaje recién enviado, para inyección AJAX sin recargar el chat |
| `modal_resumen_conversacion.html` | Resumen IA con sentimiento + barra de puntuación + agente asignado |
| `_modal_asignar_pipeline.html` | Modal Kanban CRM (pipelines + etapas + valor estimado + moneda) |
| `form.html` | Modal genérico para clasificación / nombre / asignación |

### JavaScript — patrón compartido

Estado y construcción de URL:

```js
let _filtros = {sesion_id, criterio, fecha_desde, fecha_hasta, sentimiento, clasificacion};

function _buildUrl() {
    let url = '<ruta-vista>?load_conversations=true';
    if (_filtros.sesion_id) url += '&sesion=' + _filtros.sesion_id;
    // ...resto de filtros
    return url;
}
```

WebSockets — siempre con `ReconnectingWebSocket(reconnectInterval: 1500)`:

```js
function conectarWebSocket(id) {
    chatSocket = new ReconnectingWebSocket(`${wsProtocol}//${host}/ws/chat/${id}/`, ...);
    chatSocket.onmessage = e => {
        const d = JSON.parse(e.data);
        if (d.type === 'new_message' || d.type === 'messages_update') {
            $('#mensajes-container').html(d.html);
            setTimeout(scrollToBottom, 800);
        }
    };
}

function sessionWebSocket(sid) {
    sessionSocket = new ReconnectingWebSocket(`${wsProtocol}//${host}/ws/sessionroom/${sid}/`, ...);
    sessionSocket.onmessage = e => {
        const d = JSON.parse(e.data);
        const el = $(`#lista-conversaciones div[data-id=${d.conversacion_id}]`);
        el.length ? el.replaceWith(d.html) : $('#lista-conversaciones').append(d.html);
    };
}
```

Funciones núcleo:

| Función | Qué hace |
|---------|----------|
| `cargarConversaciones()` | AJAX → render `#lista-conversaciones` + restaura `.active` si hay conv abierta |
| `cargarMensajes(id)` | Anti-doble-click + `pantallaespera()` + AJAX `?action=ver_mensajes` + hidrata header/composer/paneles + `conectarWebSocket()` |
| `_resetChat()` | Limpia todo el panel main al cambiar de sesión |
| `mostrarPlantillasSiMeta(esMeta, convId)` | Solo en finalizadas; pre-fetch + cache + visibilidad badge |
| `enviarMensaje()` | POST `action=send`, FormData con archivo opcional, inyecta HTML parcial |

Click en sidebar:

```js
$(document).on('click', '.cargar-conversacion', function() {
    cargarMensajes($(this).data('id'));
});
```

### Específico de finalizadas — plantillas Meta

- Cache local `_plantillasCache[convId]` evita refetch.
- `_detectarVarsEnCuerpo(body)` extrae IDs de `{{N}}` con regex `/\{\{(\d+)\}\}/g`.
- `_plantillaNecesitaFormulario(p)` decide si abrir el form de variables.
- Si `header_tipo` ∈ `{IMAGE, VIDEO, DOCUMENT}` → input URL obligatorio + filename opcional para DOCUMENT.
- Al enviar, POST `action=enviar_plantilla_meta` con `params_cuerpo_json` y
  `params_header_json`. Si la respuesta trae `{reactivada: true, url}`, redirige
  a la vista de abiertas — la conv ya quedó preseleccionada por
  `request.session['contactoId']`.

---

## 6. WebSockets

### `ChatConsumer` (`whatsapp/consumers.py:9`)
- Grupo: `chat_<conversacion_id>`.
- Handler `whatsapp_message` (línea 25): renderiza `mensajes_partial.html` desde
  el queryset live (`get_messages_html`, línea 64) y emite
  `{type:'messages_update', html}`.
- Recibe del cliente eventos `sendPresenceUpdate` / `quitPresenceUpdate` que se
  reenvían al service (`send_presence_update` / `quit_presence_update`, líneas 43-61).

### `SessionRoomConsumer` (`whatsapp/consumers.py:124`)
- Grupo: `whatsapp_sessionroom_<session_id>`.
- Handler `whatsapp_event` (línea 175): obtiene la conv, renderiza
  `conversacion_item.html`, y emite `{type:'messages_update', html, conversacion_id, from_me, contacto_nombre, preview}`.
- El frontend usa `from_me` y `preview` para decidir si mostrar notificación nativa.

### `SessionConsumer` (`whatsapp/consumers.py:82`)
Más simple: usado por la pantalla de sesiones para QR codes y errores. No
participa en el chat.

### Quién dispara los broadcasts

**No hay** `post_save` signals. El broadcast se hace explícito desde el handler
del webhook entrante (`whatsapp/procesar_mensaje.py:280-301`):

```python
async_to_sync(channel_layer.group_send)(
    f"chat_{conversation.id}",
    {'type': 'whatsapp_message', ...}
)
async_to_sync(channel_layer.group_send)(
    f"whatsapp_sessionroom_{session.id}",
    {'type': 'whatsapp_event', ...}
)
```

También desde `whatsapp/services.py` cuando termina la transcripción de audio
(reemplaza el bubble del audio con el texto transcrito).

**Implicancia:** si agregás un código que crea `MensajeWhatsApp` por fuera del
webhook o del action `send`, **tenés que disparar el broadcast manualmente** —
si no, los demás clientes no verán el mensaje hasta refrescar.

---

## 7. Flujo end-to-end

### Entrante (cliente → frontend)

```
[Meta Cloud / Baileys]
   │
   ▼
POST /whatsapp/meta_webhook/  ó  /whatsapp/webhook_handler/
   │   (validación verify_token / X-API-Key NODE_SECRET_KEY)
   ▼
procesar_mensaje.process_incoming_message()
   │
   ├─ idempotencia por mensaje_id_externo
   ├─ persiste / actualiza Contacto
   ├─ persiste / actualiza ConversacionWhatsApp (recalcula fecha_hora_expira)
   ├─ persiste MensajeWhatsApp
   ├─ actualiza EstadisticasConversacion
   │
   ▼
async_to_sync(channel_layer.group_send) → ChatConsumer + SessionRoomConsumer
   │
   ▼
[Frontend] reemplaza #mensajes-container y/o card del sidebar
```

Si `sesion.modo_bot='ia'` y `agente_ia` activa y la conv no fue tomada por humano:
```
   ▼
AgenteConsultor.responder()  (FAISS similarity + LangChain prompt + Google GenAI)
   ▼
get_whatsapp_service(sesion).send_text_message()  → API externa
   ▼
persiste MensajeWhatsApp(ia_generado=True)  + broadcast WS
```

### Saliente (agente → cliente)

```
[JS composer]
   │  POST /whatsapp/conversaciones/  body={action:'send', pk, mensaje, archivo?}
   ▼
view_conversaciones.send  (línea 323)
   │
   ├─ get_whatsapp_service(sesion)  → WhatsAppService | MetaWhatsAppService | ...
   ├─ service.send_text_message()  ó  send_media_message()
   ├─ valida response['success']
   ├─ persiste MensajeWhatsApp(agente=request.user, ia_generado=False)
   ├─ registra primer_agente si no existe
   ▼
JsonResponse({mensaje_html: ...})
   │
   ▼
[JS] inyecta HTML en #mensajes-container + scrollToBottom
   ▼
(además, el broadcast WS se dispara al recibir el ACK del cliente — el HTML
real lo regenera ChatConsumer.get_messages_html para todos los demás clientes)
```

### Reactivación de finalizada (Meta-only)

```
[JS] click en plantilla → form de variables → POST action=enviar_plantilla_meta
   ▼
view_conversaciones_finalizadas.enviar_plantilla_meta  (línea 257)
   │
   ├─ valida _bloqueo_reactivar() → si vencida: error
   ├─ valida sesion.es_meta + plantilla APPROVED
   ├─ get_whatsapp_service(sesion).send_template(...)
   ├─ render placeholders + persiste mensaje local
   ├─ estado_conversacion=0, recalcula fecha_hora_expira
   ├─ request.session['contactoId'] = encrypt(conv.id)
   ▼
JsonResponse({reactivada: true, url: '/whatsapp/conversaciones/'})
   ▼
[JS] window.location.href = '/whatsapp/conversaciones/'
   ▼
conversacionesView lee contactoId de session y abre la conv automáticamente
```

---

## 8. Reglas de negocio clave

| Regla | Dónde | Por qué importa |
|-------|-------|----------------|
| Ventana de gracia 6h para reactivar | `view_conversaciones_finalizadas.py:19, 22-31` | Evita revivir conversaciones muy viejas; aplica a `send`, `enviar_plantilla_meta`, `marcar-reactivar` |
| Plantillas Meta solo `APPROVED` | `listar_plantillas_meta` filtra `estado_meta='APPROVED'` | Meta rechaza el envío de plantillas no aprobadas |
| Sustitución `{{N}}` server-side | `_render_cuerpo()` antes de persistir | Garantiza que el historial muestre el texto final, no el template |
| Auto-pausa IA al asignar humano | `asignar-conversacion` setea `ai_activo=False` | Evita que la IA pise la respuesta del agente |
| Snapshot de proveedor en la conv | `ConversacionWhatsApp.proveedor_atencion` | Si la sesión migra de Baileys a Meta, las conversaciones existentes mantienen su transporte original |
| Cierre por inactividad | Cron job evalúa `fecha_hora_expira < now` y llama `cerrar()` | Liberar conversaciones colgadas; respeta `bloquear_cierre=True` |
| Manager `expirado` | `models_querysetmanagers.py:37` filtra solo por `estado_conversacion=1` | Fuente de verdad — evita que estados inconsistentes (`conversacion_finalizada=True` pero `estado_conversacion=0`) aparezcan en finalizadas |
| Idempotencia webhook | Unique `mensaje_id_externo` | Meta y Baileys reintentan; sin esto se duplicarían mensajes |
| Rate limit Node | Cache `wa_rate_limited_<session_id>` | Si Baileys reporta saturación, `process_incoming_message` corta antes de invocar IA |
| Dispatcher único | Siempre `get_whatsapp_service(sesion)` | Nunca hardcodear `if sesion.proveedor=='meta'` — esparce lógica de transporte |
| `select_related` obligatorio en listado | `view_conversaciones.py:830-841` | El partial `conversacion_item.html` toca `sesion.config_meta`, `sesion.config_baileys`, `asignado_a.foto` — sin `select_related` son N+1 |

---

## 9. Cómo trabajar en estas vistas

**Agregar un action GET/POST nuevo:**
1. Branch dentro del `if request.method == 'GET'/'POST'` del archivo correspondiente.
2. Si muta estado, envolver en `with transaction.atomic():` (ya está al tope del POST).
3. Devolver `JsonResponse` consistente: `{error: bool, message?, ...}`.
4. Si requiere broadcast, llamar a `channel_layer.group_send` manualmente.

**Agregar un filtro de listado:**
1. Leer `request.GET.get(...)` arriba del bloque de filtros (línea ~763).
2. Componer `filtros &= Q(...)` en la cadena.
3. Acumular en `url_vars` para que la paginación / refresh AJAX lo respete.
4. Pasarlo al `data` para que el template lo persista en el input.
5. Lado JS: agregar al objeto `_filtros` y al `_buildUrl`.

**Agregar un panel toggleable al header:**
1. Botón en `chat-header` con `d-none` por defecto + `data-id`.
2. Panel debajo del header con `d-none`.
3. En `cargarMensajes()`, hidratar datos y mostrar el botón.
4. En `_resetChat()`, esconder ambos.

**Agregar un tipo de mensaje:**
1. Extender `MensajeWhatsApp.tipo` choices.
2. Branch nuevo en `mensajes_partial.html` (rama out e in).
3. Servicio: `send_media_message` ya genérico, ajustar `media_type`.
4. Webhook entrante: branch en `procesar_mensaje.py` para parsear el payload del proveedor.

**Tocar el flujo realtime:**
- Si rompés algo en `ChatConsumer.get_messages_html`, todos los chats abiertos
  dejan de actualizarse. Test manual: abrir 2 pestañas y enviar desde una.
- Si agregás un grupo nuevo, sumarlo en `routing.py` y consumer en `consumers.py`.

**Migrar a un nuevo proveedor:**
1. Agregar opción en `SesionWhatsApp.proveedor`.
2. Crear `services_<nombre>.py` con clase que herede de `WhatsAppService` y
   sobrescriba `send_text_message`, `send_media_message`, `send_template`.
3. Registrar en `get_whatsapp_service` (`services.py:604`).
4. Webhook entrante propio si el proveedor lo requiere; debe terminar llamando
   a `process_incoming_message` con el formato unificado.

---

## 10. Archivos referenciados

| Archivo | Rol |
|---------|-----|
| `whatsapp/view_conversaciones.py` | Vista de abiertas + helpers compartidos |
| `whatsapp/view_conversaciones_finalizadas.py` | Vista de finalizadas + ventana 6h |
| `whatsapp/models.py` | Modelos de dominio |
| `whatsapp/models_querysetmanagers.py` | Manager `sin_expirar` / `expirado` |
| `whatsapp/forms.py` | `CambiarClasificacionForm`, `CambiarNombreContactoForm`, `AsignarAgenteForm` |
| `whatsapp/services.py` | Dispatcher + `WhatsAppService` (Baileys) |
| `whatsapp/services_meta.py` | `MetaWhatsAppService` (Cloud API) |
| `whatsapp/services_instagram.py` | `InstagramService`, `MessengerService` |
| `whatsapp/consumers.py` | `ChatConsumer`, `SessionConsumer`, `SessionRoomConsumer` |
| `whatsapp/routing.py` | Rutas WS |
| `whatsapp/procesar_mensaje.py` | Handler del webhook entrante (broadcast WS) |
| `whatsapp/meta_webhook_view.py` | Endpoint `/meta_webhook/` (Meta) |
| `whatsapp/webhook_baileys_view.py` | Endpoint `/webhook_handler/` (Baileys) |
| `whatsapp/urls.py` | Registro de rutas |
| `whatsapp/templates/whatsapp/conversaciones/listado.html` | Template abiertas |
| `whatsapp/templates/whatsapp/conversaciones/listado_expirado.html` | Template finalizadas |
| `whatsapp/templates/whatsapp/conversaciones/conversaciones_partial.html` | Wrapper sidebar |
| `whatsapp/templates/whatsapp/conversaciones/conversacion_item.html` | Card de conversación |
| `whatsapp/templates/whatsapp/conversaciones/mensajes_partial.html` | Historial chat |
| `whatsapp/templates/whatsapp/conversaciones/mensaje_enviado_partial.html` | Mensaje recién enviado |
| `whatsapp/templates/whatsapp/conversaciones/modal_resumen_conversacion.html` | Modal resumen |
| `whatsapp/templates/whatsapp/conversaciones/_modal_asignar_pipeline.html` | Modal pipeline CRM |
| `whatsapp/templates/whatsapp/conversaciones/form.html` | Modal genérico |
| `static/stylenew/conversacion_plantillas.css` | CSS panel plantillas Meta |
| `static/stylenew/conversaciones.css` | CSS layout chat |
