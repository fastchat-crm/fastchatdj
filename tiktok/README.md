# App `tiktok/` — capa de control del canal TikTok

> App Django **sin modelos propios**, espejo de `instagram/`. Datos en `whatsapp/`
> (`SesionWhatsApp` con `proveedor='tiktok'`, `ConfigTikTok`, `ConversacionWhatsApp`,
> `ComentarioSocial` con `canal='tiktok'`).
>
> **Estado del canal:** la Business Messaging API de TikTok está en beta y requiere
> aprobación (ver `.ai/docs/tiktok_integracion.md`). Esta app permite pre-registrar
> cuentas y dejar listo asesores/IA; el webhook `/tiktok/webhook/` y el
> `TikTokService` de envío se implementan al llegar la aprobación.

## Archivos

| Archivo | Para qué es |
|---|---|
| `apps.py` | Registro de la app (`TiktokConfig`). |
| `urls.py` | Tupla `tiktok_urls` + `urlpatterns` (incluye la ruta pública `webhook/`). Montada en `/tiktok/` desde `fastchatdj/urls.py`. |
| `webhook_view.py` | Receiver del webhook TikTok Business Messaging → `/tiktok/webhook/` (`csrf_exempt`). GET responde `challenge` validando el verify token de `ConfigTikTok`; POST valida HMAC-SHA256 contra `client_secret` (fail-closed sólo si hay secreto configurado), resuelve la config por `business_id`/`open_id`, traduce el evento y llama `whatsapp.procesar_mensaje.process_incoming_message`. Registra cada evento en `EventoMetaRecibido` (prefijo `tiktok:`). |
| `view_monitoreo.py` | `/tiktok/monitoreo/` → `whatsapp.view_monitoreo_social.monitoreo_webhook_canal(request, 'tiktok')`: auditoría de eventos webhook (`EventoMetaRecibido` prefijo `tiktok:`), stats, filtros y detalle de payload — clave para verificar el sandbox durante la beta. |
| `view_cuentas.py` | `/tiktok/sesiones/` (renombrada desde `cuentas/` 2026-07) — pre-registro de sesiones Business (nombre, @username, business_id, tokens OAuth opcionales), activar/suspender, eliminar (soft). UI en cards estilo tablero de sesiones WhatsApp (reusa `conex-*` de `/static/stylenew/sesiones.css`) + modal "Nueva conexión" con sidebar de canales que redirige a `/whatsapp/sesiones/` y `/instagram/sesiones/`. |
| `funciones_cuentas.py` | `guardar_cuenta`: crea `SesionWhatsApp(session_id='tiktok-<username>')` + `ConfigTikTok` con verify token generado. |
| `view_conversaciones.py` | `/tiktok/conversaciones/` — wrapper de `conversacionesView(canal_fijo='tiktok', template='tiktok/conversaciones/listado.html')`: misma lógica de inbox que WhatsApp acotada a sesiones TikTok, pero con **template propio** (desde 2026-07-09: copia completa del listado de WhatsApp con branding TikTok fijo — ícono/toast `fa-tiktok`, links a `/tiktok/sesiones/`, modal sin-sesiones TikTok). Los partials `_modal_*` / `_ci_kebab_portal` siguen compartidos desde `whatsapp/`. Cambios de lógica compartida (JS/WebSocket/acciones) hay que replicarlos en las tres copias. Vacío hasta activar la API. |
| `view_contactos.py` | `/tiktok/contactos/` — wrapper de `whatsapp.view_contacto.contactoView(canal_fijo='tiktok')`: módulo de contactos acotado a sesiones TikTok (sin alta manual/importación; los contactos nacen del webhook). |
| `view_comentarios.py` | `/tiktok/comentarios/` — wrapper de `comentariosView(canal_fijo='tiktok')`. |
| `servicio.py` | `TikTokService(ServicioCanalBase)` — sender de DMs (Business Messaging v1.3, header `Access-Token`). Enchufado en `get_whatsapp_service()` para `proveedor='tiktok'`. Parte textos > 1000 chars en envíos secuenciales. Endpoints por validar contra sandbox al aprobar la app. |
| `templates/tiktok/...` | `cuentas/listado.html`, `conversaciones/listado.html`. CSS en `static/css/tiktok/`. |

El webhook entrante vive ahora en esta app: `tiktok/webhook_view.py` →
**`/tiktok/webhook/`** (canónica). `whatsapp/tiktok_webhook_view.py` quedó como shim
que re-exporta la vista y mantiene el alias legacy `/whatsapp/tiktok_webhook/` para no
romper dashboards ya configurados. `CANALES_ORIGEN` y `atendida_por_tiktok` ya soportan
el canal.

> **Al configurar el webhook en el panel de TikTok usa la URL canónica
> `/tiktok/webhook/`.** La antigua `/whatsapp/tiktok_webhook/` sigue respondiendo pero
> está deprecada.

## Comprobar conectividad

Acción POST `diagnostico` en `view_cuentas` → `whatsapp.diagnostico_social.diagnosticar_conexion(sesion)` (módulo compartido). Como la API está en beta y no hay prueba de perfil en vivo, valida credenciales, vigencia del token (`token_expira_en`), identificador, el último `error_mensaje` registrado y el webhook (verificado + `client_secret`). El menú de acciones es un **offcanvas lateral** (propio de la app) que clona el `[data-kebab-menu]` de la card, con acciones por delegación. Secciones al estilo del tablero WhatsApp: "Comprobar conectividad" (modal con pasos, escapados anti-XSS), "Ver trazabilidad (errores)" → `/tiktok/monitoreo/`, "Analytics de esta sesión" → `/whatsapp/analytics/?sesion=<id>`.

## Pendiente al aprobar la API

1. Validar shape real del payload del webhook y del endpoint de envío contra el sandbox.
2. Flujo OAuth de conexión (reemplaza la carga manual de tokens en sesiones) + refresh de tokens (cron).
3. Comentarios: cron `comment/list` → `ComentarioSocial(canal='tiktok')` + responder vía API.
4. `/tiktok/publicaciones/` espejo de `instagram/view_posts.py` (grilla de videos + modal de comentarios tipo post) — requiere la Display/Comments API aprobada; el patrón ya está construido en Instagram.

## Hardening 2026-07-16 (ultrareview)

- **Webhook fail-closed:** `webhook_view._procesar_post` rechaza (401) cuando la firma es verificable e inválida **o** cuando no hay `client_secret` y `META_WEBHOOK_FAIL_CLOSED` (default `True`) — antes procesaba sin firma. El handshake GET ahora exige `verify_token`. Para operar, el form de cuentas captura **`client_secret`** (nuevo campo, `funciones_cuentas`/`cuentas/listado.html`).
- **Resolución con status:** `_resolver_config` filtra `sesion__status=True`; sesiones eliminadas ya no procesan mensajes. `delete` apaga `activo`.
- **Robustez:** `tipo_evento` truncado a 50, parseo seguro de `timestamp`, y `try` por-evento (un evento malo no aborta el lote).
- **Reconexión / re-registro:** el alta reactiva la sesión soft-borrada en vez de bloquear por `session_id` único.
- **Monitoreo con scoping:** `/tiktok/monitoreo/` acota los eventos por pertenencia (business_id/open_id del payload vs. sesiones visibles).
