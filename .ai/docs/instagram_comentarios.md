# Comentarios de redes sociales (Instagram y Facebook) — módulo implementado

> Fecha: 2026-07-08. Fase 1 de moderación de comentarios: Instagram vía webhook `comments`.
>
> Update 2026-07-16 — grilla de publicaciones (`view_publicaciones_social.py`):
> (1) `action=comentarios_post` ahora SINCRONIZA en vivo antes de listar
> (`funciones_comentarios.sincronizar_comentarios_publicacion` →
> `listar_comentarios_publicacion` del service por canal): importa a
> `ComentarioSocial` los comentarios hechos antes de suscribir el webhook o
> cuyos eventos se rechazaron (sin correr reglas comentario→DM — son
> históricos). Antes el post decía "1 comentario" (métrica Meta) y el modal
> salía vacío. (2) `action=publicar_post` (POST): botón "Nueva publicación" en
> la grilla — FB `POST /{page_id}/feed` o `/photos` (texto + link + foto URL);
> IG flujo container→`media_publish` (imagen URL pública obligatoria).
> (3) FB `listar_publicaciones` pide `shares` + insights
> (`post_impressions`, `post_impressions_unique`, `post_clicks`) en el mismo
> request y la grilla los muestra; si la app no tiene `read_insights`,
> reintenta sin insights (la grilla no se rompe, solo no muestra alcance).
> 2026-07-14: se sumó **Facebook** (canal `facebook`, proveedor `messenger`): comentarios del
> feed de página vía webhook `feed` (`guardar_comentario_facebook`), acciones vía
> `MessengerService` (responder = `POST /{comment_id}/comments`, ocultar = `is_hidden`,
> private reply igual que IG) y app de control `facebook/` (ver `facebook/README.md`).
> El resolver de sender por canal vive en `funciones_comentarios.service_por_canal`
> (dict explícito; canal sin soporte → dict de error, no excepción); el mapeo
> canal↔proveedor en `whatsapp/models.py::PROVEEDOR_POR_CANAL`. La grilla de
> publicaciones es una vista genérica compartida:
> `whatsapp/view_publicaciones_social.py` + `funciones_publicaciones.py`
> (2026-07-15; `instagram/view_posts.py` y `facebook/view_posts.py` son wrappers).
> TikTok reutilizará este mismo módulo (campo `canal`) cuando su API esté aprobada — ver `.ai/docs/tiktok_integracion.md`.

## Qué hace

Inbox de moderación de comentarios de publicaciones: los comentarios llegan por el webhook
de Instagram ya existente, se listan en `/instagram/comentarios/` y `/tiktok/comentarios/`
(la ruta genérica `/whatsapp/comentarios/` se eliminó el 2026-07-09; la vista compartida
`whatsapp/view_comentarios.py::comentariosView` se accede solo vía los wrappers per-canal)
y el asesor puede:

- **Responder públicamente** (Graph API `POST /{comment_id}/replies`).
- **Ocultar / volver a mostrar** (`POST /{comment_id}` con `hide`).
- **Enviar DM privado** al autor (private reply: `POST /{page_id}/messages` con
  `recipient.comment_id`; ventana Meta de 7 días desde el comentario). Cuando el autor
  responde el DM, el webhook normal de IG crea Contacto/Conversación y el lead entra al
  pipeline estándar (IA, asignación, etiquetas).

## Archivos

| Archivo | Rol |
|---|---|
| `whatsapp/models.py` → `ComentarioSocial` (final del archivo) | Modelo. `canal` (`instagram`/`tiktok`), `comment_id` unique, `estado` (`nuevo`/`respondido`/`oculto`), `dm_enviado`, FK opcional a `ConversacionWhatsApp`, `payload_json` crudo. |
| `whatsapp/funciones_comentarios.py` | Helpers: `guardar_comentario_instagram` (webhook), `responder_comentario`, `ocultar_comentario`, `enviar_dm_comentario`, `_vincular_conversacion`. Desde 2026-07-14 incluye el motor de reglas: `procesar_reglas_comentario(comentario)` se dispara al final de `guardar_comentario_instagram` — evalúa las `ReglaComentario` activas de la sesión (orden asc, primera que matchea gana; keywords sin tildes/mayúsculas, vacías = todo; `media_id` opcional acota a una publicación) y ejecuta respuesta pública, DM automático y/o etiqueta (si el autor ya es Contacto por `external_id`). |
| `whatsapp/models.py` → `ReglaComentario` | Regla comentario→DM: sesión, canal, keywords, media_id, respuesta_publica, mensaje_dm, etiqueta FK, activa, orden, usos/ultimo_uso. |
| `whatsapp/view_reglas_comentarios.py` + `instagram/view_reglas.py` | CRUD de reglas (vista genérica por canal + wrapper IG). UI en `/instagram/reglas-comentarios/`, template `whatsapp/reglas_comentarios/listado.html` + `static/js/whatsapp/reglas_comentarios.js`. Valida que la regla tenga al menos una acción. |
| `whatsapp/view_comentarios.py` | Vista función `comentariosView`: GET listado con filtros (criterio/estado/sesión) + POST acciones (`responder`, `ocultar`, `mostrar`, `enviar_dm`). Visibilidad por `sesiones_vista_completa`. |
| `meta/instagram.py` | Métodos nuevos de `InstagramService`: `responder_comentario`, `ocultar_comentario`, `enviar_dm_desde_comentario`. |
| `whatsapp/meta_social_webhook_view.py` | `_procesar_post_social` ahora recorre `entry[].changes[]` y con `field == 'comments'` llama `guardar_comentario_instagram(sesion, config, value)`. Ignora ecos (autor = `ig_user_id`) y duplicados. Desde 2026-07-19 las vistas `instagram_webhook`/`messenger_webhook` se excluyen del `ATOMIC_REQUESTS` global (`transaction.non_atomic_requests`), cada entry se procesa en su propio `transaction.atomic()` y la auditoría `EventoMetaRecibido` usa `crear_evento_log`/`guardar_evento_log` (transacción propia, tolerante a fallos): un query fallido ya no envenena la transacción de PostgreSQL ("current transaction is aborted") ni tumba la respuesta 200 a Meta. Los modelos `ConfigInstagram`/`ConfigMessenger`/`ConfigTikTok`/`EventoMetaRecibido`/`ComentarioSocial` requieren migraciones pendientes de generar/aplicar en producción. |
| `whatsapp/urls.py` | Ya NO expone `comentarios/` (eliminada 2026-07-09); las rutas de UI son `/instagram/comentarios/` y `/tiktok/comentarios/`. Los webhooks se movieron a su propia app: **`/instagram/webhook/`**, **`/tiktok/webhook/`** (`/facebook/webhook/` para Messenger). whatsapp conserva sólo los alias legacy deprecados `/whatsapp/instagram_webhook/` y `/whatsapp/tiktok_webhook/`. |
| `whatsapp/templates/whatsapp/comentarios/listado.html` + `static/css/whatsapp/comentarios_listado.css` | UI listado + modal responder/DM. |
| `templates/docs/conexion_instagram_tiktok.html` + `seguridad/docs/documentacion.py` | Hoja de documentación in-app: arquitectura, cómo sacar tokens IG (Page Access Token long-lived, ig_user_id, webhook `comments`), proceso TikTok. Slug `conectar-instagram-tiktok`. |

## Pendientes del developer

1. `makemigrations whatsapp` + `migrate` (modelo `ComentarioSocial`; 2026-07-14 agrega `ReglaComentario`).
2. En Meta App: suscribir el campo **`comments`** del producto Instagram (además de `messages`).
3. Registrar los módulos en el sidebar: correr `python manage.py seed_modulos` (desde 2026-07-09
   resetea todo el catálogo, recrea las secciones — incluidas Instagram y TikTok con sus
   `comentarios/` — y re-vincula los roles por URL).

## Diagnóstico de producción (2026-07-28)

Revisión del estado real en el servidor. Guardado acá porque el código estaba
correcto pero la extracción llevaba semanas sin capturar nada:

- **`ComentarioSocial` estaba vacío** (0 filas) pese a tener sesiones conectadas
  (`messenger` id 42 y `instagram` id 43).
- **Webhook de Facebook: la suscripción SIEMPRE estuvo activa.** Recibió 223
  eventos el 16/Jul (11:10–14:18) y nada más: **216 rechazados con 401 "Firma
  HMAC inválida"** (el caso de dos Meta Apps que documenta `meta/README.md` →
  `app_secrets_extra`) y 7 procesados; el 17/Jul nginx registró 62 × 500.
  Auditoría en `EventoMetaRecibido` (`tipo_evento='messenger:page'`).
  **Corrección (verificado por API el 2026-07-28):** en una primera lectura se
  concluyó que "Meta deshabilitó la suscripción tras los fallos". **Es falso.**
  `GET /{app_id}/subscriptions` devuelve `object=page, active=True`, callback
  `…/facebook/webhook/` y campos `feed,messages,messaging_postbacks`; y
  `GET /{page_id}/subscribed_apps` confirma la página suscrita. El silencio desde
  el 17/Jul se explica simplemente por **falta de actividad** en una página de
  prueba (`fan_count: 1`). Antes de culpar al webhook, confirmar con estos dos
  endpoints — el 401/500 en los logs no implica que Meta haya dado de baja nada.
- **Webhook de Instagram: faltaba la suscripción del objeto en la app (resuelto
  2026-07-28).** Cero eventos históricos, y la causa era concreta:
  `GET /{app_id}/subscriptions` **no listaba ningún objeto `instagram`** (solo
  `whatsapp_business_account`, `page` y `user`). Se creó por API con
  `POST /{app_id}/subscriptions` (`object=instagram`,
  `fields=comments,messages,messaging_postbacks`, callback
  `…/instagram/webhook/`, `verify_token` = `ConfigInstagram.webhook_verify_token`).
  Meta hizo el handshake al instante (GET desde `facebookplatform/1.0` → 200) y
  `webhook_verificado_en` quedó sellado. **La suscripción del webhook se puede
  crear por API, no hace falta el panel.** Instagram no necesita
  `POST /{ig_user_id}/subscribed_apps`: ese campo no existe en la versión actual,
  los eventos de IG viajan por la suscripción de la página vinculada.
- **Faltan scopes para leer comentarios de Facebook.** `debug_token` sobre el
  Page Access Token de la sesión 42 devuelve `pages_read_engagement`,
  `pages_show_list`, `pages_messaging`, `instagram_manage_comments`… pero **no**
  `pages_read_user_content` ni `pages_manage_engagement`. Por eso
  `GET /{post_id}/comments` responde `(#200) Missing Permissions` aunque el post
  reporte `comments_count: 3`. `pages_read_engagement` habilita leer el
  contenido **propio** de la página, NO los comentarios de terceros. Se corrige
  en el panel de Meta (agregar los scopes + reautorizar la página para emitir un
  token nuevo), no desde el código.
- Instagram sí tiene `instagram_manage_comments`: su lectura de comentarios
  responde OK. Su bloqueo era la suscripción faltante del objeto `instagram`
  (ver arriba), ya resuelta — el diagnóstico de la sesión 43 da **todo verde**.
  El único pendiente real quedó del lado de Facebook: los dos permisos.

**Chequeo de permisos en el diagnóstico (2026-07-28).** `diagnostico_social.py`
solo probaba `obtener_perfil()`, así que daba **"Conexión correcta"** con un
token que lee el perfil pero no los comentarios — así fue como Facebook pasó
semanas roto sin que el tablero lo notara. Ahora `_pasos_permisos(canal, token)`
agrega **un paso por capacidad** (`CAPACIDADES_SCOPES`): ver publicaciones, leer
comentarios, responder/ocultar, DMs. Los scopes se leen con
`scopes_del_token()` → `debug_token` de Graph, que necesita el **App Token**
(`app_id|app_secret`): `/me/permissions` solo sirve para tokens de USUARIO y
sobre un Page Token devuelve `(#100) nonexisting field (permissions)`.
El `resumen` distingue ahora el caso intermedio ("Conecta, pero hay N función(es)
bloqueada(s): …"); `ok` sigue significando solo "la sesión conecta", para no
degradar el estado de una sesión sana por un permiso faltante.

Mapa de scope → capacidad (Facebook):
`pages_read_engagement` = ver las publicaciones **propias** de la página ·
`pages_read_user_content` = leer los comentarios **de terceros** ·
`pages_manage_engagement` = responder/ocultar · `pages_messaging` = DMs.
El error clásico es asumir que `pages_read_engagement` alcanza para comentarios:
no alcanza, y Graph solo lo dice al pedir el edge `/comments`.

**Dónde activar los permisos, dentro del producto (2026-07-28).** Un alert que
dice "falta X" sin decir dónde activarlo no le sirve al administrador. Ahora:
- `url_permisos_meta()` arma el deep-link a
  `developers.facebook.com/apps/<app_id>/app-review/permissions/` usando el App ID
  real de `get_meta_app_credentials()` (cae al listado de apps si no hay App ID).
- `COMO_ACTIVAR_PERMISOS` es el texto único con el camino (Revisión de la app →
  Permisos y funciones), la aclaración Acceso estándar vs avanzado (estándar
  alcanza para páginas propias) y el recordatorio de **reautorizar**: el Page
  Access Token conserva los permisos que tenía al emitirse.
- `_paso()` lleva `enlace` + `enlace_texto` como **campos aparte**: el JS de las
  pantallas de cuentas escapa todo con `escHtml`, así que un `<a>` embebido en
  `solucion` saldría como texto plano. Se renderiza en `.diag-enlace`
  (`static/stylenew/sesiones.css`, bump a `?v2.3` en ambos listados).
- El modal de comentarios muestra los mismos dos botones ("Permisos y funciones"
  y "Reconectar la página/cuenta") vía `data['url_permisos_meta']`.

**La guía de conexión de Facebook pedía permisos incompletos** — causa raíz de
todo esto. `facebook/cuentas/listado.html` listaba `pages_messaging`,
`pages_show_list`, `pages_manage_metadata` y `pages_manage_engagement`, **sin**
`pages_read_engagement` ni `pages_read_user_content`. Quien siguiera la guía
generaba un token que nunca podía leer comentarios. Ahora enumera los 6 con para
qué sirve cada uno, avisa del `(#200)` y agrega el paso de reautorizar al cambiar
permisos. La guía de Instagram ya estaba completa.

## Limitaciones conocidas

- **Reacciones: no se extraen.** Lo único que existe es el contador agregado que
  se lee al pintar la grilla (`reactions.summary(true).limit(0)` en Facebook,
  `like_count` en Instagram). No hay ingesta de eventos de reacción, no se
  guarda quién reaccionó ni con qué emoji, y el webhook de Messenger descarta
  explícitamente los eventos `reaction` (`meta_social_webhook_view.py`). Un
  inbox de reacciones equivalente al de comentarios está sin construir.
- `fecha_comentario` se estampa con `timezone.now()` al recibir el webhook de
  **Instagram** (el value de Meta no trae timestamp del comentario). El webhook
  de Facebook y el sync desde la grilla sí traen fecha real — ver nota de
  timezone abajo.
- **Fechas y `USE_TZ=False` (fix 2026-07-28).** El proyecto guarda datetimes
  naive en hora local, pero Graph entrega siempre UTC (epoch en el webhook de
  Facebook, `...+0000` en el sync). Guardar ese aware tal cual dejaba
  `fecha_comentario` **5 horas adelantada**. Ahora ambos caminos pasan por
  `funciones_comentarios._fecha_convencion_proyecto()`, que convierte a naive
  local con `timezone.make_naive()` cuando `USE_TZ=False` y deja el aware intacto
  cuando es `True`. Al tocar ingesta de fechas de Meta, usar ese helper.
- **Respuestas anidadas de Instagram (fix 2026-07-28).** El edge
  `/{media_id}/comments` de IG solo devuelve comentarios de primer nivel, pero el
  `comments_count` del media SÍ cuenta las respuestas — la grilla decía "8
  comentarios" y el modal mostraba 5. `InstagramService.listar_comentarios_publicacion`
  ahora pide la arista `replies{...}` y aplana padre + respuestas en una sola
  lista, poniendo `parent_id` del padre en cada respuesta. Es el equivalente al
  `filter=stream` que `MessengerService` ya usaba para páginas de Facebook.
- **El fallo de sync ya no es mudo (fix 2026-07-28).**
  `sincronizar_comentarios_publicacion` devuelve `(creados, error)` en vez de
  solo el conteo; el error sale traducido por `diagnostico_social._causa_graph()`
  y `view_publicaciones_social` lo pasa al partial `_comentarios_post.html`
  (rama `{% elif error_sync %}`) de ambos canales. Antes, un token sin permisos
  dejaba el modal vacío con el mismo copy que "no hay comentarios".
- El DM privado saliente no se persiste como `MensajeWhatsApp` (no existe conversación aún); la conversación nace cuando el autor responde.
- `ConfigInstagram` se crea manualmente (admin) — no hay UI de conexión IG todavía.

## Apps por canal (construido 2026-07-08)

El usuario pidió control por canal estilo "app whatsapp". Se crearon **apps Django de
capa de control** (`instagram/`, `tiktok/`) que NO duplican modelos: reusan
`SesionWhatsApp`/`ConversacionWhatsApp`/`ComentarioSocial` de `whatsapp/` filtrando por
`proveedor`/`canal`. Registradas en `INSTALLED_APPS` y en `urls_sistema` de `fastchatdj/urls.py`.

| URL | Vista | Qué hace |
|---|---|---|
| `/instagram/sesiones/` (antes `cuentas/`) | `instagram/view_cuentas.py` | Conectar sesión IG: cards estilo tablero WhatsApp + modal con sidebar de canales; acción `autodetectar` (con el token extrae page_id/ig_user_id/username vía `/me/accounts`), probar conexión, activar/suspender, eliminar (soft). Crea `SesionWhatsApp(proveedor='instagram', session_id='instagram-<ig_user_id>')` + `ConfigInstagram`. |
| `/instagram/conversaciones/` | `instagram/view_conversaciones.py` | Inbox en vivo acotado a IG con template propio `instagram/conversaciones/listado.html` (2026-07-09; ver `.ai/docs/conversaciones.md` § "Tema y template por canal"). |
| `/instagram/comentarios/` | wrapper de `whatsapp.view_comentarios.comentariosView(canal_fijo='instagram')` | Inbox comentarios solo IG. |
| `/instagram/publicaciones/` | `instagram/view_posts.py` | Grilla en vivo (`InstagramService.listar_publicaciones`) con likes/comentarios + conteo de comentarios nuevos en CRM por `media_id`. Modal de moderación tipo post por publicación (`action=comentarios_post`, partial `_comentarios_post.html`): responder/ocultar/mostrar/DM sin salir de la grilla (POST delega en `_procesar_accion` del inbox de comentarios). |
| `/tiktok/sesiones/` (antes `cuentas/`) | `tiktok/view_cuentas.py` | Pre-registro de sesiones (crea `SesionWhatsApp(proveedor='tiktok')` + `ConfigTikTok`); cards estilo tablero + banner de estado beta. |
| `/tiktok/conversaciones/` | `tiktok/view_conversaciones.py` | Inbox en vivo acotado a TikTok con template propio `tiktok/conversaciones/listado.html` (vacío hasta aprobar API). |
| `/tiktok/comentarios/` | wrapper `canal_fijo='tiktok'` | Inbox comentarios TikTok (fase 2). |

Cambios de soporte: `PROVEEDORES_SESION` += `tiktok`, property `es_tiktok`, modelo
`ConfigTikTok` (OneToOne, tokens OAuth + refresh). URLs renombradas de `cuentas/` a
`sesiones/` el 2026-07-08; el seed de módulos usa las nuevas.

### Tablero "Canales conectados" multicanal (2026-07-09)

- Las cards de sesiones IG/TikTok en `whatsapp/templates/whatsapp/sesiones/_card.html` son de
  primera clase: avatar/badge por canal, `@username` desde `config_instagram`/`config_tiktok`
  (agregados al `select_related` del tablero en `view_sesiones.py`), kebab con links al canal
  (gestionar/conversaciones/comentarios/publicaciones) + "Usuarios asignables", footer con
  Conversaciones y Gestionar per-canal. El toggle activo/pausada funciona (handler genérico).
- El modal "Nueva conexión" ya no redirige ni muestra "próximamente" para IG/TikTok: los botones
  del sidebar usan `data-canal` y abren panes con guía paso a paso
  (`_pane_instagram.html`, `_pane_tiktok.html`) + botón a `/instagram/sesiones/` y
  `/tiktok/sesiones/`. CSS nuevo: `static/css/whatsapp/tablero_canales.css`.
- Los forms de cuentas IG/TikTok (`instagram/.../cuentas/listado.html`,
  `tiktok/.../cuentas/listado.html`) tienen un `<details class="guia-inline">` con los pasos
  detallados para obtener credenciales, condensados de la hoja `conectar-instagram-tiktok`.

Doc de servicios Meta: `meta/README.md` (para qué es cada archivo del paquete).

## Completado en segunda pasada (2026-07-08)

- **Modo híbrido implementado**: `MODOS_BOT` += `hibrido`; en `procesar_mensaje.py` la rama
  tradicional ahora acepta `('tradicional', 'hibrido')` — si el motor no maneja el mensaje y el
  modo es híbrido, se traza `hibrido_fallback_ia` y la ejecución cae al pipeline IA normal.
  Tradicional puro sigue cortando sin IA.
- **Agentes IA — uso por sesión/canal**: el listado de agentes (`crm/view_mientrenamiento.py`,
  GET final) anota `num_sesiones` y `sesiones_uso` (nombre + canal) por agente; la tarjeta en
  `crm/templates/crm/entrenamiento/form.html` muestra "En N sesiones" + badges de canal.
- **TikTok pre-construido**: webhook `tiktok/webhook_view.py` en
  **`/tiktok/webhook/`** (GET challenge + verify token de ConfigTikTok; POST →
  `process_incoming_message`), sender `tiktok/servicio.py::TikTokService` enchufado en
  `get_whatsapp_service`, `tiktok` agregado a `CANALES_ORIGEN` y property `atendida_por_tiktok`.
  Falta solo: aprobación beta, OAuth y validar shapes contra sandbox.
- **Docs cliente/admin**: la hoja in-app `conectar-instagram-tiktok` ahora incluye "Cómo usar el
  canal día a día" (pantallas por app + modos de bot) y "Checklist del administrador" (switches
  de canal, credenciales Meta, extraer URLs/roles, webhook, trámite TikTok).

## Roadmap pendiente (acordado con el usuario)

1. ~~Selector global de sesión multicanal~~ **HECHO 2026-07-08**: el dropdown de sesión activa del
   navbar (`templates/base.html` + `static/stylenew/selector_sesion_global.{css,js}`) lista sesiones
   de todos los proveedores con chips de filtro por canal (WhatsApp/Instagram/TikTok, los 3 activos
   por defecto) e ícono TikTok propio. `whatsapp/context_processors.py::selector_sesion` ya era
   multicanal (no filtra por proveedor).
2. ~~App `facebook/` (Messenger) espejo de `instagram/`~~ **HECHO 2026-07-14**: app completa
   (`/facebook/sesiones|conversaciones|comentarios|reglas-comentarios|publicaciones|centro/`),
   comentarios del feed por webhook, reglas comentario→DM, publicaciones en vivo, card de
   primera clase en el tablero, pane propio en "Nueva conexión", chip Facebook en el selector
   global y sección en `seed_modulos`. Pendientes del developer en `facebook/README.md`
   (migración por choice `facebook`, suscribir campo `feed`, re-correr seed).
3. **TikTok**: aprobación beta + OAuth + refresh de tokens (cron) + comentarios por polling.
