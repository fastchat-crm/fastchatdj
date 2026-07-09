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
| `urls.py` | Tupla `instagram_urls` (formato del sistema para `urls_sistema`/módulos) + `urlpatterns`. Montada en `/instagram/` desde `fastchatdj/urls.py`. |
| `view_cuentas.py` | `/instagram/sesiones/` (renombrada desde `cuentas/` 2026-07) — conectar/editar/probar/suspender/eliminar sesiones. Acción `autodetectar`: con solo el Access Token extrae page_id / ig_user_id / @username. Al guardar prueba conexión y genera el webhook verify token. UI en cards estilo tablero de sesiones WhatsApp (reusa `conex-*` de `/static/stylenew/sesiones.css`) + modal "Nueva conexión" con sidebar de canales que redirige a `/whatsapp/sesiones/` y `/tiktok/sesiones/`. |
| `funciones_cuentas.py` | Helpers de `view_cuentas`: `autodetectar_desde_token` (Graph `/me/accounts` y `/me`), `guardar_cuenta` (crea `SesionWhatsApp` + `ConfigInstagram`, `session_id='instagram-<ig_user_id>'`), `probar_conexion` (actualiza `estado`). |
| `view_conversaciones.py` | `/instagram/conversaciones/` — wrapper directo de `whatsapp.view_conversaciones.conversacionesView(canal_fijo='instagram')`: el MISMO inbox/chat en vivo de WhatsApp acotado a sesiones Instagram (desde 2026-07; antes era un listado con deep-link). |
| `view_comentarios.py` | `/instagram/comentarios/` — wrapper de `whatsapp.view_comentarios.comentariosView(canal_fijo='instagram')`. |
| `view_posts.py` | `/instagram/publicaciones/` — grilla en vivo de posts (`InstagramService.listar_publicaciones`) con likes/comentarios de IG + conteo de comentarios del CRM por `media_id`. Administración tipo post (2026-07): botón "Comentarios" abre modal con los `ComentarioSocial` del post (GET `action=comentarios_post&media_id=`, partial `_comentarios_post.html`) y permite responder/ocultar/mostrar/DM inline — el POST delega en `whatsapp.view_comentarios._procesar_accion`. |
| `templates/instagram/...` | `cuentas/listado.html`, `conversaciones/listado.html`, `publicaciones/listado.html`. CSS en `static/css/instagram/`. |

## Convenciones

- Vistas basadas en funciones; helpers en `funciones_<tema>.py`.
- Visibilidad: dueño de la sesión o superuser (cuentas); `sesiones_vista_completa` (conversaciones/posts).
- El webhook del canal NO está aquí: es `/whatsapp/instagram_webhook/` (`whatsapp/meta_social_webhook_view.py`).
- Guía de tokens para clientes: Documentación in-app, slug `conectar-instagram-tiktok`.
