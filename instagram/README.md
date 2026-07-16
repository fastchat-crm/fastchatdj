# App `instagram/` — capa de control del canal Instagram

> App Django **sin modelos propios**: es la capa de control/UI del canal. Los datos viven en
> `whatsapp/` (`SesionWhatsApp` con `proveedor='instagram'`, `ConfigInstagram`,
> `ConversacionWhatsApp`, `ComentarioSocial`) y las llamadas a Graph API en `meta/instagram.py`.
> Así se reusa el motor completo: webhook → `process_incoming_message` → IA → asignación →
> WebSockets → pipeline.

## Archivos

| Archivo | Para qué es |
|---|---|
| `apps.py` | Registro de la app (`InstagramConfig`). |
| `urls.py` | Tupla `instagram_urls` (formato del sistema para `urls_sistema`/módulos) + `urlpatterns` (incluye la ruta pública `webhook/`). Montada en `/instagram/` desde `fastchatdj/urls.py`. |
| `webhook_view.py` | Receiver del webhook Instagram DM → `/instagram/webhook/` (`csrf_exempt`). Módulo delgado: re-exporta `instagram_webhook` de `whatsapp/meta_social_webhook_view.py` (impl compartida con Messenger, pegada al pipeline de mensajería). |
| `view_cuentas.py` | `/instagram/sesiones/` (renombrada desde `cuentas/` 2026-07) — conectar/editar/probar/suspender/eliminar sesiones. Acción `autodetectar`: con solo el Access Token extrae page_id / ig_user_id / @username. Al guardar prueba conexión y genera el webhook verify token. UI en cards estilo tablero de sesiones WhatsApp (reusa `conex-*` de `/static/stylenew/sesiones.css`) + modal "Nueva conexión" con sidebar de canales que redirige a `/whatsapp/sesiones/` y `/tiktok/sesiones/`. |
| `funciones_cuentas.py` | Helpers de `view_cuentas`: `autodetectar_desde_token` (Graph `/me/accounts` y `/me`), `guardar_cuenta` (crea `SesionWhatsApp` + `ConfigInstagram`, `session_id='instagram-<ig_user_id>'`), `probar_conexion` (actualiza `estado`). |
| `view_conversaciones.py` | `/instagram/conversaciones/` — wrapper de `whatsapp.view_conversaciones.conversacionesView(canal_fijo='instagram', template='instagram/conversaciones/listado.html')`: misma lógica de inbox en vivo que WhatsApp acotada a sesiones Instagram, pero con **template propio** (desde 2026-07-09: copia completa del listado de WhatsApp con branding Instagram fijo — ícono/toast `fa-instagram`, links a `/instagram/sesiones/`, modal sin-sesiones Instagram). Los partials `_modal_*` / `_ci_kebab_portal` siguen compartidos desde `whatsapp/`. Cambios de lógica compartida (JS/WebSocket/acciones) hay que replicarlos en las tres copias. |
| `view_contactos.py` | `/instagram/contactos/` — wrapper de `whatsapp.view_contacto.contactoView(canal_fijo='instagram')`: módulo de contactos acotado a sesiones Instagram (sin alta manual/importación; los contactos nacen del webhook). |
| `view_comentarios.py` | `/instagram/comentarios/` — wrapper de `whatsapp.view_comentarios.comentariosView(canal_fijo='instagram')`. |
| `view_posts.py` | `/instagram/publicaciones/` — grilla en vivo de posts (`InstagramService.listar_publicaciones`) con likes/comentarios de IG + conteo de comentarios del CRM por `media_id`. Administración tipo post (2026-07): botón "Comentarios" abre modal con los `ComentarioSocial` del post (GET `action=comentarios_post&media_id=`, partial `_comentarios_post.html`) y permite responder/ocultar/mostrar/DM inline — el POST delega en `whatsapp.view_comentarios._procesar_accion`. |
| `view_centro.py` | `/instagram/centro/` — wrapper de `whatsapp.view_centro._render_centro(canal='instagram')`: guía instructiva de los módulos del canal. |
| `view_monitoreo.py` | `/instagram/monitoreo/` — wrapper de `whatsapp.view_monitoreo_social.monitoreo_webhook_canal(canal='instagram')`: auditoría de eventos webhook (`EventoMetaRecibido` con prefijo `instagram:`), stats, filtros por error/firma/pendiente y detalle de payload. |
| `templates/instagram/...` | `cuentas/listado.html`, `conversaciones/listado.html`, `publicaciones/listado.html`. CSS en `static/css/instagram/`. |

## Convenciones

- Vistas basadas en funciones; helpers en `funciones_<tema>.py`.
- Visibilidad: dueño de la sesión o superuser (cuentas); `sesiones_vista_completa` (conversaciones/posts).
- El webhook del canal vive en `instagram/webhook_view.py` → **`/instagram/webhook/`** (canónica; usa esta al configurar el panel de Meta). La implementación es compartida con Messenger en `whatsapp/meta_social_webhook_view.py`. Alias legacy deprecado: `/whatsapp/instagram_webhook/`.
- Guía de tokens para clientes: Documentación in-app, slug `conectar-instagram-tiktok`.
- **Comprobar conectividad**: acción POST `diagnostico` en `view_cuentas` → `whatsapp.diagnostico_social.diagnosticar_conexion(sesion)` (módulo compartido). Devuelve pasos con causa+solución (token, IG User ID, respuesta de Graph mapeada a causa legible, webhook verificado) y sincroniza `SesionWhatsApp.estado`. El menú de acciones es un **offcanvas lateral** (propio de la app, no comparte `_card.html`) que clona el `[data-kebab-menu]` de la card; las acciones usan delegación de eventos para funcionar dentro del offcanvas. Incluye, en secciones al estilo del tablero WhatsApp: "Comprobar conectividad" (modal con pasos, valores escapados anti-XSS), "Ver trazabilidad (errores)" → `/instagram/monitoreo/`, y "Analytics de esta sesión" → `/whatsapp/analytics/?sesion=<id>` (analytics es multicanal). Las opciones exclusivas de WhatsApp Cloud (plantillas, campañas, revalidar número) NO aplican a este canal.

## Hardening 2026-07-16 (ultrareview)

- **Webhook por-entry (cross-tenant):** el receiver compartido (`whatsapp/meta_social_webhook_view.py`) resuelve la config **por `entry`** con `sesion__status=True`; los DMs de una cuenta ya no caen en la sesión de otra empresa en un batch multi-cuenta.
- **Unicidad de `ig_user_id`:** `funciones_cuentas.guardar_cuenta` rechaza un `ig_user_id` ya usado por otra sesión activa (alta y edición) y sincroniza `session_id` — cierra el desvío de webhooks por config duplicada.
- **Reconexión tras eliminar:** el alta reactiva la sesión soft-borrada; `delete` apaga `activo`; el webhook ya no atiende sesiones eliminadas.
- **Editar sin re-pegar token:** Access Token obligatorio solo al conectar; en edición se conserva el actual si se deja vacío.
- **Monitoreo con scoping:** `/instagram/monitoreo/` acota por pertenencia (id del payload vs. sesiones visibles).
- **XSS en comentarios de posts:** el caption del modal usa `textContent` en vez de `innerHTML` (`publicaciones/listado.html`).
- **Reglas comentario→DM:** `view_reglas_comentarios` valida `sesion__usuario` en change/delete/toggle (antes IDOR).
- **Race de comentarios:** `funciones_comentarios._persistir_comentario` usa `get_or_create` atómico sobre `comment_id`.
