# App `facebook/` — capa de control del canal Facebook (Messenger + página)

> Creada 2026-07-14 como espejo de `instagram/` (ver plan en
> `.ai/docs/propuestas/megaestudio_omnicanal.md`, fases F1-F3). **No tiene
> modelos propios**: una página de Facebook se materializa como
> `SesionWhatsApp(proveedor='messenger', session_id='messenger-<page_id>')` +
> `ConfigMessenger` (OneToOne, `whatsapp/models.py`), reusando todo el motor
> compartido (conversaciones, IA, asignación, webhooks, secuencias, campañas).

## Mapa de archivos

| Archivo | Rol |
|---|---|
| `apps.py` | Registro `FacebookConfig` (en `INSTALLED_APPS` de `fastchatdj/settings.py`). |
| `urls.py` | Tupla `facebook_urls` (6 rutas) + `urlpatterns` (incluye la ruta pública `webhook/`). Montada en `/facebook/` desde `fastchatdj/urls.py`. |
| `webhook_view.py` | Receiver del webhook Messenger → `/facebook/webhook/` (`csrf_exempt`). Módulo delgado: re-exporta `messenger_webhook` de `whatsapp/meta_social_webhook_view.py` (impl compartida con Instagram; también procesa comentarios del feed). |
| `view_centro.py` | `/facebook/centro/` → `whatsapp.view_centro._render_centro(request, 'facebook')` (guía en `GUIAS_CANAL`). |
| `view_monitoreo.py` | `/facebook/monitoreo/` → `whatsapp.view_monitoreo_social.monitoreo_webhook_canal(request, 'messenger')`: auditoría de eventos webhook (`EventoMetaRecibido` prefijo `messenger:`), stats, filtros error/firma/pendiente y detalle de payload. |
| `view_cuentas.py` | `/facebook/sesiones/` — conectar páginas: autodetección desde token (`/me/accounts`), probar conexión, activar/suspender, eliminar (soft). |
| `funciones_cuentas.py` | Helpers: `autodetectar_desde_token`, `guardar_cuenta` (crea sesión + `ConfigMessenger`), `probar_conexion` (via `MessengerService.obtener_perfil`), `generar_verify_token`. |
| `view_conversaciones.py` | `/facebook/conversaciones/` y `/facebook/conversaciones-finalizadas/` — wrappers `conversacionesView` / `conversacionesFinalizadasView` con `canal_fijo='messenger'`; template compartido de whatsapp, branding vía `BRANDING_INBOX_CANAL`. Aislamiento por canal (2026-07-16): `canal_conversacion_permitido` bloquea `ver_mensajes`/`contactoId`/deep-link de convs de otro canal y las claves `localStorage` van namespaced (`wa_last_conv_finalizada_messenger`, etc.) — antes el inbox de Facebook auto-abría la última conv de WhatsApp. |
| `view_contactos.py` | `/facebook/contactos/` — wrapper `contactoView(canal_fijo='messenger')`: módulo de contactos acotado a sesiones Messenger (sin alta manual/importación; los contactos nacen del webhook). |
| `view_comentarios.py` | `/facebook/comentarios/` — wrapper `comentariosView(canal_fijo='facebook')`. |
| `view_reglas.py` | `/facebook/reglas-comentarios/` — wrapper `reglasComentariosView(canal='facebook')`. |
| `view_posts.py` | `/facebook/publicaciones/` — wrapper de la vista genérica `whatsapp/view_publicaciones_social.py::publicacionesSocialView(canal='facebook')` (grilla live GET `/{page_id}/posts` normalizado al shape IG + modal de moderación). 2026-07-16: al abrir el modal se sincronizan los comentarios en vivo del post a `ComentarioSocial`; botón "Nueva publicación" (texto/link/foto vía `MessengerService.publicar_post`); la grilla muestra shares + insights (impresiones/alcance/clics — requiere `read_insights`, degrada sin romper). |
| `templates/facebook/` | `cuentas/listado.html`, `publicaciones/listado.html`, `publicaciones/_comentarios_post.html`. El inbox de conversaciones usa el template compartido de whatsapp. |
| CSS | `static/css/facebook/cuentas_listado.css`, `static/css/facebook/publicaciones_listado.css`. |

## Mapeo canal ↔ proveedor

El **proveedor** de la sesión es `messenger` (ya existía en `PROVEEDORES_SESION`);
el **canal de comentarios** es `facebook` (`CANALES_COMENTARIO`). El mapeo vive en
`whatsapp/models.py::PROVEEDOR_POR_CANAL` (junto a `CANALES_CON_ACCIONES`). No
crear un proveedor `facebook` nuevo.

## Flujo de datos

- **DMs Messenger**: webhook **`/facebook/webhook/`** (`facebook/webhook_view.py`,
  re-exporta la impl compartida de `whatsapp/meta_social_webhook_view.py`) →
  `process_incoming_message` → pipeline completo. Alias legacy deprecado:
  `/whatsapp/messenger_webhook/`. **Al configurar el panel de Meta usa la URL
  canónica `/facebook/webhook/`.**
- **Comentarios del feed**: mismo webhook, `field == 'feed'` con
  `item == 'comment'` → `funciones_comentarios.guardar_comentario_facebook`
  (usa `created_time` real del payload) → motor de reglas
  `procesar_reglas_comentario` (respuesta pública / DM privado / etiqueta).
- **Acciones de moderación**: `MessengerService` (`meta/instagram.py`) —
  responder (`POST /{comment_id}/comments`), ocultar (`is_hidden`), private
  reply (`POST /{page_id}/messages` con `recipient.comment_id`, ventana 7 días).
- **Envío saliente**: dispatcher `get_whatsapp_service` → `MessengerService`
  (ya estaba registrado).

## Comprobar conectividad

Acción POST `diagnostico` en `view_cuentas` → `whatsapp.diagnostico_social.diagnosticar_conexion(sesion)` (módulo compartido con IG/TikTok). Devuelve pasos con causa+solución (token, Page ID, respuesta de Graph mapeada a causa legible vía `_causa_graph`, webhook verificado) y sincroniza `SesionWhatsApp.estado`. El menú de acciones es un **offcanvas lateral** (propio de la app) que clona el `[data-kebab-menu]` de la card, con acciones por delegación. Secciones al estilo del tablero WhatsApp: "Comprobar conectividad" (modal con pasos, escapados anti-XSS), "Ver trazabilidad (errores)" → `/facebook/monitoreo/`, "Analytics de esta sesión" → `/whatsapp/analytics/?sesion=<id>`. Las opciones exclusivas de WhatsApp Cloud (plantillas, campañas) no aplican.

## Checklist del administrador (pendientes del developer)

1. `makemigrations whatsapp` + `migrate` — el choice `facebook` en
   `CANALES_COMENTARIO` (ComentarioSocial/ReglaComentario) genera migración.
2. En la Meta App: suscribir el campo **`feed`** del producto Webhooks de la
   página (además de `messages` para Messenger).
3. `python manage.py seed_modulos` para registrar la sección Facebook del
   sidebar (resetea el catálogo y re-vincula roles).
4. Activar el switch del canal Messenger en la configuración global
   (`canales_activos.messenger`) si no lo está.

## Hardening 2026-07-16 (ultrareview)

- **Webhook por-entry (cross-tenant):** `whatsapp/meta_social_webhook_view.py` resuelve la config **por cada `entry`** (`_resolver_config_por_entry`, filtra `sesion__status=True`), no una vez para todo el payload. Un batch multi-página de Meta ya no procesa los mensajes de otra empresa bajo la sesión del primer entry. `tipo_evento` se trunca a 50, el `except` es por-entry (un entry malo no aborta el lote) y los eventos `messaging` sin `message` (delivery/read/postback) se descartan. `_social_a_eventos_internos` emite un evento por adjunto (antes solo el primero).
- **Unicidad de `page_id`:** `funciones_cuentas.guardar_cuenta` rechaza un `page_id` ya usado por otra sesión activa (alta y edición) y mantiene `session_id` en sync — cierra el desvío de webhooks por config duplicada y el reclamo de páginas ajenas.
- **Reconexión tras eliminar:** el alta reactiva la sesión soft-borrada (mismo `session_id`) en vez de bloquear para siempre; `delete` también apaga `activo`.
- **Editar sin re-pegar token:** el Access Token es obligatorio solo al conectar; en edición se conserva el actual si se deja vacío.
- **Monitoreo con scoping:** `/facebook/monitoreo/` (`view_monitoreo_social`) acota los eventos por pertenencia (id destino del payload vs. sesiones visibles); no-superusuarios ya no ven DMs de otros tenants.

## Conectar una página — escollos conocidos

Guía completa para el usuario final: **Documentación → Instagram, Facebook y TikTok**
(`/seguridad/documentacion/?pagina=conectar-instagram-tiktok`,
template `templates/docs/conexion_instagram_tiktok.html`). Lo que hay que saber al tocar este código:

- **`pages_read_engagement` NO alcanza para los comentarios.** Solo cubre el contenido propio de la
  página. Para leer lo que escribe la gente hace falta `pages_read_user_content`, y para responder u
  ocultar `pages_manage_engagement`. Sin ellos el perfil de la página se lee bien y todo *parece*
  conectado, pero Graph responde `(#200) Missing Permissions` recién al pedir el edge `/comments` —
  así estuvieron rotos los comentarios durante semanas sin que el tablero lo notara.
  El set completo del token es: `pages_messaging`, `pages_show_list`, `pages_manage_metadata`,
  `pages_read_engagement`, `pages_read_user_content`, `pages_manage_engagement`.
- **Un permiso activado no aplica al token ya emitido.** El Page Access Token congela los scopes del
  momento de autorizar; hay que regenerarlo y reconectar la página
  (ver `COMO_ACTIVAR_PERMISOS` en `whatsapp/diagnostico_social.py`). Alcanza **Acceso estándar** para
  páginas propias; el **Acceso avanzado** solo hace falta para páginas de terceros y exige App Review.
- **Antes de culpar al webhook**, confirmar con `GET /{app_id}/subscriptions` (¿`object=page` con
  `active=true` y el callback correcto?) y `GET /{page_id}/subscribed_apps`. Verificado el 2026-07-28:
  la suscripción llevaba meses activa y el silencio era **falta de actividad** en una página de prueba
  con 1 seguidor — no una baja de Meta, como se había concluido en una revisión anterior.
- **401 «Firma HMAC inválida» en masa** = eventos firmados por una Meta App distinta de la registrada.
  Se resuelve con `app_secrets_extra` (ver `meta/README.md`), no reconectando la página.
- El botón **Diagnóstico** (`whatsapp/diagnostico_social.py` → `_diag_meta`) inspecciona los scopes
  reales con `debug_token` y da una línea por capacidad, con enlace a la pantalla de Meta donde se activa.
