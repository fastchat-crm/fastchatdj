# Paquete `meta/` — integraciones con Meta Graph API

> Todas las llamadas directas a la Graph API de Meta (WhatsApp Cloud, Instagram, Messenger,
> CAPI) viven en este paquete. Ningún otro módulo debería hacer `requests` a
> `graph.facebook.com` directamente. No es una app Django (no está en `INSTALLED_APPS`,
> no tiene modelos): es una librería de servicios que usan `whatsapp/`, `instagram/`,
> `seguridad/` y los webhooks.

## Mapa de archivos

| Archivo | Para qué es |
|---|---|
| `__init__.py` | Índice del paquete: documenta la organización por dominio. |
| `urls.py` | Helpers de URL de Graph API (`build_graph_url`, `build_fb_url`). Centraliza la versión de la API (`settings.META_API_VERSION`, default v22.0) — un upgrade de versión es un solo cambio aquí. |
| `credenciales.py` | Lee las credenciales de la Meta App de la organización: singleton `seguridad.CredencialMetaApp` (BD) con fallback a settings/`credenciales.json`. Expone `get_meta_app_credentials()` → `(app_id, app_secret)`. |
| `webhook.py` | Utilidades comunes a los 3 webhooks Meta (WhatsApp Cloud, Instagram, Messenger): validación de firma HMAC-SHA256 (`X-Hub-Signature-256`), handshake del `hub.verify_token` y extractores de payload. |
| `autodetect.py` | Auto-detección de campos Meta a partir de App ID + Secret (+ System User Token opcional): nombre de App, Business, System User ID, scopes, expiración del token y `config_id` del Embedded Signup. Usado por la pantalla de credenciales Meta en `seguridad/`. |
| `validacion.py` | Checklist completo de credenciales: App ID + Secret válidos, token, scopes requeridos (`whatsapp_business_management`, …), Business Manager y WABAs accesibles. Alimenta el diagnóstico de conexión. |
| `perfiles.py` | Verificadores de perfil por canal: pingean Graph con las credenciales de cada `Config*` y persisten los datos visibles (username / page_name / display_phone) + `ultima_sincronizacion`. Devuelven `(ok, info)` listos para JSON. |
| `capi.py` | Sender de Meta Conversions API (CAPI): dispara eventos Lead / Purchase / CompleteRegistration al Pixel/Dataset con `ctwa_clid` cuando existe (cierra el loop ad → conversión). Cada envío queda auditado en `whatsapp.EventoCAPI`. |
| `whatsapp.py` | `MetaWhatsAppService` — sender de WhatsApp Cloud API (texto, media, plantillas). Misma interfaz pública que `whatsapp.services.WhatsAppService` (Baileys) para que el resto del código sea agnóstico al transporte. `sincronizar_plantillas` pide `fields=...,rejected_reason,quality_score` explícito — Graph API no devuelve el motivo de rechazo por defecto (fix 2026-07-13). `titulo_boton_interactivo()` ajusta títulos de botones/filas al límite de Meta (20/24 chars) quitando emojis antes de truncar — el corte ciego dejaba botones incompletos ("Hablar con aseso"). |
| `instagram.py` | `InstagramService` y `MessengerService` — DMs vía Graph (`POST /{page_id}/messages`), y desde 2026-07: perfil (`obtener_perfil`), publicaciones (`listar_publicaciones`), comentarios (`responder_comentario`, `ocultar_comentario`) y private reply (`enviar_dm_desde_comentario`). Messenger hereda de Instagram cambiando solo el resolver de config. `send_text_message` parte textos > 1000 chars en envíos secuenciales (límite de la Graph API para IG/Messenger). |

## Cómo se enruta un envío

`whatsapp/services.py::get_whatsapp_service(sesion)` decide el sender según
`sesion.proveedor`:

```
baileys   → whatsapp.services.WhatsAppService   (proceso Node local)
meta      → meta.whatsapp.MetaWhatsAppService
instagram → meta.instagram.InstagramService
messenger → meta.instagram.MessengerService
tiktok    → tiktok.servicio.TikTokService  (Business Messaging API — no es Meta;
             vive en la app tiktok/)
```

## Contrato común de canal (2026-07)

Todos los senders heredan de `whatsapp/servicio_canal_base.py::ServicioCanalBase`,
que ES el contrato del dispatcher: `send_text_message` (obligatorio),
`send_media_message` (firma completa con `file_path`/`file_content`/`media_url`/
`conversacion_id`), `send_presence_update`/`quit_presence_update` (no-op default),
y capacidades opcionales con default degradado (`edit_message`, `delete_message`,
`send_template`, `sync_transcribe_audio`, `get_user_image`, `check_session_status`,
`close_session`, `format_phone_number`). Un canal que no soporta una capacidad
devuelve `{'success': False, 'error': <mensaje en español>}` en vez de romper con
AttributeError en el pipeline compartido. Al crear un canal nuevo (ej. `facebook/`):
heredar de `ServicioCanalBase`, implementar `send_text_message` y registrar el
proveedor en `get_whatsapp_service`.

## Convenciones

- Los senders devuelven dicts `{'success': bool, 'error': ..., ...}` — nunca lanzan al caller.
- Config por sesión (`ConfigMeta`, `ConfigInstagram`, `ConfigMessenger`) guarda los tokens
  por cuenta; las credenciales App-level (app_id/app_secret) salen de `meta.credenciales`.
- Módulos legacy (`whatsapp/common_meta.py`, `whatsapp/sesiones_common.py`,
  `whatsapp/services_instagram.py`) re-exportan de aquí — para código nuevo importa
  siempre de `meta.*`.
