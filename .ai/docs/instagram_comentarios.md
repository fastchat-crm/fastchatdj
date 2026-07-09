# Comentarios de redes sociales (Instagram) — módulo implementado

> Fecha: 2026-07-08. Fase 1 de moderación de comentarios: Instagram vía webhook `comments`.
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
| `whatsapp/funciones_comentarios.py` | Helpers: `guardar_comentario_instagram` (webhook), `responder_comentario`, `ocultar_comentario`, `enviar_dm_comentario`, `_vincular_conversacion`. |
| `whatsapp/view_comentarios.py` | Vista función `comentariosView`: GET listado con filtros (criterio/estado/sesión) + POST acciones (`responder`, `ocultar`, `mostrar`, `enviar_dm`). Visibilidad por `sesiones_vista_completa`. |
| `meta/instagram.py` | Métodos nuevos de `InstagramService`: `responder_comentario`, `ocultar_comentario`, `enviar_dm_desde_comentario`. |
| `whatsapp/meta_social_webhook_view.py` | `_procesar_post_social` ahora recorre `entry[].changes[]` y con `field == 'comments'` llama `guardar_comentario_instagram(sesion, config, value)`. Ignora ecos (autor = `ig_user_id`) y duplicados. |
| `whatsapp/urls.py` | Ya NO expone `comentarios/` (eliminada 2026-07-09); las rutas de UI son `/instagram/comentarios/` y `/tiktok/comentarios/`. Los webhooks (`instagram_webhook`, `tiktok_webhook`) sí siguen en whatsapp. |
| `whatsapp/templates/whatsapp/comentarios/listado.html` + `static/css/whatsapp/comentarios_listado.css` | UI listado + modal responder/DM. |
| `templates/docs/conexion_instagram_tiktok.html` + `seguridad/docs/documentacion.py` | Hoja de documentación in-app: arquitectura, cómo sacar tokens IG (Page Access Token long-lived, ig_user_id, webhook `comments`), proceso TikTok. Slug `conectar-instagram-tiktok`. |

## Pendientes del developer

1. `makemigrations whatsapp` + `migrate` (modelo `ComentarioSocial`).
2. En Meta App: suscribir el campo **`comments`** del producto Instagram (además de `messages`).
3. Registrar los módulos en el sidebar: correr `python manage.py seed_modulos` (desde 2026-07-09
   resetea todo el catálogo, recrea las secciones — incluidas Instagram y TikTok con sus
   `comentarios/` — y re-vincula los roles por URL).

## Limitaciones conocidas

- `fecha_comentario` se estampa con `timezone.now()` al recibir el webhook (el value de Meta no trae timestamp del comentario).
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
| `/instagram/conversaciones/` | `instagram/view_conversaciones.py` | Listado DMs IG con deep-link `?conv=<encrypt_id>` al inbox compartido. |
| `/instagram/comentarios/` | wrapper de `whatsapp.view_comentarios.comentariosView(canal_fijo='instagram')` | Inbox comentarios solo IG. |
| `/instagram/publicaciones/` | `instagram/view_posts.py` | Grilla en vivo (`InstagramService.listar_publicaciones`) con likes/comentarios + conteo de comentarios nuevos en CRM por `media_id`. Modal de moderación tipo post por publicación (`action=comentarios_post`, partial `_comentarios_post.html`): responder/ocultar/mostrar/DM sin salir de la grilla (POST delega en `_procesar_accion` del inbox de comentarios). |
| `/tiktok/sesiones/` (antes `cuentas/`) | `tiktok/view_cuentas.py` | Pre-registro de sesiones (crea `SesionWhatsApp(proveedor='tiktok')` + `ConfigTikTok`); cards estilo tablero + banner de estado beta. |
| `/tiktok/conversaciones/` | `tiktok/view_conversaciones.py` | Listado (vacío hasta aprobar API). |
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
- **TikTok pre-construido**: webhook `whatsapp/tiktok_webhook_view.py` en
  `/whatsapp/tiktok_webhook/` (GET challenge + verify token de ConfigTikTok; POST →
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
2. **App `facebook/`** (Messenger) espejo de `instagram/` — `ConfigMessenger` ya existe.
3. **TikTok**: aprobación beta + OAuth + refresh de tokens (cron) + comentarios por polling.
