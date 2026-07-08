# Integración TikTok — Plan técnico

> Estado 2026-07-08: **esqueleto construido** — app `tiktok/` (cuentas/conversaciones/comentarios),
> modelo `ConfigTikTok`, proveedor `tiktok` en `PROVEEDORES_SESION`/`CANALES_ORIGEN`, webhook
> `/whatsapp/tiktok_webhook/` (`whatsapp/tiktok_webhook_view.py`) y sender `tiktok/servicio.py`
> enchufado en `get_whatsapp_service`. Ver `tiktok/README.md` y `.ai/docs/instagram_comentarios.md`.
> **Bloqueante externo:** aprobación de la Business Messaging API (beta) — los shapes de payload y
> el endpoint de envío deben validarse contra el sandbox al ser aprobados.
> Investigación original: 2026-06-10.

## 1. Qué ofrece TikTok (APIs oficiales)

### 1.1 Business Messaging API (DMs) — el equivalente a Meta Cloud API

- Permite a cuentas **TikTok Business** enviar/recibir mensajes directos vía API a través de plataformas integradas (CRMs = "Messaging Partners").
- Modelo de eventos: **webhooks** — TikTok envía eventos (mensajes entrantes, etc.) a una callback URL HTTPS propia, igual que Meta. Hay endpoints para configurar el webhook y suscribirse a eventos.
- Envío de mensajes: endpoints REST con access token de la cuenta Business (OAuth).
- Estado: **beta** — requiere aplicar como desarrollador en el portal Business API y ser aprobado.
- Restricción regional: solo cuentas Business registradas **fuera** de US / EEA / Suiza / UK. Ecuador ✅.
- Cuentas personales NO sirven: el cliente debe convertir su cuenta a Business (gratis, desde la app TikTok).
- Competidores que ya lo integran como Messaging Partners: SleekFlow, MessageGate, Respond.io.

### 1.2 Comments API (Business Account)

- Listar comentarios de videos propios, responder comentarios, ocultar / cambiar estado.
- Endpoints: `comment/list`, `comment/reply/create`, actualización de estado de comentarios (Business API v1.3).
- Misma app de desarrollador y mismo OAuth que Messaging.

### 1.3 Lo que NO existe

- No hay "Baileys de TikTok": ninguna librería no-oficial estable para DMs. Scraping = baneo de cuenta. Solo vía oficial.

## 2. Decisión de producto: ambos, en 2 fases

| Fase | Qué | Por qué |
|------|-----|---------|
| 1 | **DMs (conversaciones)** | Corazón del CRM. Mapea 1:1 al pipeline existente de WhatsApp/Instagram/Messenger. |
| 2 | **Comentarios** | Inbox secundario tipo moderación: comentario → responder → invitar a DM. Es lo que hacen los CRM grandes. Comentarios solos no hacen CRM; conversaciones sí. |

## 3. Arquitectura: NO crear app Django nueva

El proyecto ya resolvió multi-canal con Instagram y Messenger **dentro de la app `whatsapp`** (no apps separadas). TikTok sigue el mismo camino: se reusa IA, asignación de asesores, pipelines, estadísticas, WebSockets, inbox.

Patrón existente (referencia):

```
SesionWhatsApp ─(1:1)→ ConfigBaileys / ConfigMeta / ConfigInstagram / ConfigMessenger
             ├─(1:N)→ Contacto (campo `canal`)
             └─(1:N)→ PerfilSesionWhatsApp
Contacto ─(1:N)→ ConversacionWhatsApp (`origen_canal`, `proveedor_atencion`)
ConversacionWhatsApp ─(1:N)→ MensajeWhatsApp
```

Todos los canales comparten los mismos modelos, diferenciados por campos — no por tablas.

### Pasos de implementación (cuando se decida construir)

1. **`whatsapp/models.py`**
   - Agregar `'tiktok'` a `PROVEEDORES_SESION` (~línea 99 de `SesionWhatsApp`).
   - Agregar `'tiktok'` a `CANALES_ORIGEN` de `Contacto` (~línea 278) y a los choices de `origen_canal` / `proveedor_atencion` en `ConversacionWhatsApp` (~líneas 533, 565).
   - Nuevo modelo `ConfigTikTok` OneToOne con `SesionWhatsApp`, espejo de `ConfigInstagram` (~línea 2355): `business_id`, `open_id`, `access_token` (cifrado tipo `EncryptedTextField` como `ConfigMeta.access_token`), `refresh_token`, `webhook_verify_token`, `error_mensaje`.
   - Agregar propiedad helper `atendida_por_tiktok` en `ConversacionWhatsApp` (junto a `atendida_por_instagram`, ~línea 721).
2. **Webhook entrante** — nueva vista `whatsapp/tiktok_webhook_view.py`, path `/whatsapp/tiktok_webhook/` (espejo de `meta_social_webhook_view.py`):
   - GET: verificación del webhook.
   - POST: validar firma, normalizar payload TikTok al formato interno, llamar a `process_incoming_message(session, event_data, channel_layer)` de `procesar_mensaje.py`. Desde ahí todo funciona solo: Contacto, Conversación, Mensaje, broadcast a `chat_{conv_id}` y `whatsapp_sessionroom_{session_id}`, motor IA, asignación de asesores.
3. **Servicio de envío** — `meta/tiktok.py` con `TikTokService`, espejo de `InstagramService` (`meta/instagram.py`): POST al endpoint de envío de Business Messaging con el access token de `ConfigTikTok`.
4. **OAuth de conexión** — flujo donde el cliente autoriza su cuenta Business: redirect a TikTok con `app_id`, callback que guarda tokens en `ConfigTikTok` y crea/activa la `SesionWhatsApp` con `proveedor='tiktok'`.
5. **Tablero de sesiones** (`whatsapp/templates/whatsapp/sesiones/tablero.html`): card "TikTok" en el modal "Agregar conexión" (Instagram/Messenger ya tienen su slot ahí) + botón "Conectar cuenta TikTok".
6. **Documentación en la página de sesiones**: panel/acordeón explicando al cliente los pasos: convertir cuenta a Business → clic en conectar → autorizar → listo.
7. **Fase 2 — comentarios**: decidir entre `tipo='comentario'` en `MensajeWhatsApp` o tab separado en conversaciones; sincronización por cron en `cron_jobs/` (polling de `comment/list`) + acción "responder" y "pasar a DM".

## 4. Requisitos externos (bloqueantes, antes de codear)

1. Cuenta **TikTok Business** propia para pruebas.
2. Registrar app de desarrollador en `business-api.tiktok.com/portal` y **solicitar acceso a Business Messaging API (beta)**. Es el paso lento/crítico — sin aprobación no hay DMs. Conviene aplicar antes de empezar a construir.
3. URL pública HTTPS para el webhook — ya existe (`mensajeria.broktech.com.ec`).
4. Con la app aprobada: `app_id` + `app_secret` para el OAuth de clientes (guardar en `credenciales.json`, claves documentadas en `credenciales_template.json`).

## 5. Fuentes

- Business Messaging API Education Hub: https://business-api.tiktok.com/portal/bm-api/education-hub
- About Messaging Partners: https://ads.tiktok.com/help/article/about-message-management-tools
- Crear configuración de webhook Business Messaging: https://business-api.tiktok.com/portal/docs/create-a-business-messaging-webhook-configuration/v1.3
- Suscripción a eventos Business Messaging: https://business-api.tiktok.com/portal/docs/subscribe-to-business-messaging-webhook-events-via-webhooks-api/v1.3
- Responder comentarios: https://business-api.tiktok.com/portal/docs/reply-to-a-comment/v1.3
- Webhooks overview (developers): https://developers.tiktok.com/doc/webhooks-overview/
- Ejemplo de Messaging Partner: https://sleekflow.io/channels-integrations/tiktok-business-messaging
