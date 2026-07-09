# App `tiktok/` — capa de control del canal TikTok

> App Django **sin modelos propios**, espejo de `instagram/`. Datos en `whatsapp/`
> (`SesionWhatsApp` con `proveedor='tiktok'`, `ConfigTikTok`, `ConversacionWhatsApp`,
> `ComentarioSocial` con `canal='tiktok'`).
>
> **Estado del canal:** la Business Messaging API de TikTok está en beta y requiere
> aprobación (ver `.ai/docs/tiktok_integracion.md`). Esta app permite pre-registrar
> cuentas y dejar listo asesores/IA; el webhook `/whatsapp/tiktok_webhook/` y el
> `TikTokService` de envío se implementan al llegar la aprobación.

## Archivos

| Archivo | Para qué es |
|---|---|
| `apps.py` | Registro de la app (`TiktokConfig`). |
| `urls.py` | Tupla `tiktok_urls` + `urlpatterns`. Montada en `/tiktok/` desde `fastchatdj/urls.py`. |
| `view_cuentas.py` | `/tiktok/sesiones/` (renombrada desde `cuentas/` 2026-07) — pre-registro de sesiones Business (nombre, @username, business_id, tokens OAuth opcionales), activar/suspender, eliminar (soft). UI en cards estilo tablero de sesiones WhatsApp (reusa `conex-*` de `/static/stylenew/sesiones.css`) + modal "Nueva conexión" con sidebar de canales que redirige a `/whatsapp/sesiones/` y `/instagram/sesiones/`. |
| `funciones_cuentas.py` | `guardar_cuenta`: crea `SesionWhatsApp(session_id='tiktok-<username>')` + `ConfigTikTok` con verify token generado. |
| `view_conversaciones.py` | `/tiktok/conversaciones/` — wrapper directo de `conversacionesView(canal_fijo='tiktok')`: el mismo inbox/chat de WhatsApp acotado a sesiones TikTok (vacío hasta activar la API). |
| `view_comentarios.py` | `/tiktok/comentarios/` — wrapper de `comentariosView(canal_fijo='tiktok')`. |
| `servicio.py` | `TikTokService(ServicioCanalBase)` — sender de DMs (Business Messaging v1.3, header `Access-Token`). Enchufado en `get_whatsapp_service()` para `proveedor='tiktok'`. Parte textos > 1000 chars en envíos secuenciales. Endpoints por validar contra sandbox al aprobar la app. |
| `templates/tiktok/...` | `cuentas/listado.html`, `conversaciones/listado.html`. CSS en `static/css/tiktok/`. |

El webhook entrante ya existe: `whatsapp/tiktok_webhook_view.py` →
`/whatsapp/tiktok_webhook/` (GET responde `challenge` validando el verify token de
`ConfigTikTok`; POST resuelve la config por `business_id`/`open_id`, traduce el evento y llama
`process_incoming_message`). `CANALES_ORIGEN` y `atendida_por_tiktok` ya soportan el canal.

## Pendiente al aprobar la API

1. Validar shape real del payload del webhook y del endpoint de envío contra el sandbox.
2. Flujo OAuth de conexión (reemplaza la carga manual de tokens en sesiones) + refresh de tokens (cron).
3. Comentarios: cron `comment/list` → `ComentarioSocial(canal='tiktok')` + responder vía API.
4. `/tiktok/publicaciones/` espejo de `instagram/view_posts.py` (grilla de videos + modal de comentarios tipo post) — requiere la Display/Comments API aprobada; el patrón ya está construido en Instagram.
