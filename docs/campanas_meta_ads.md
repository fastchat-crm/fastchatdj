# Campañas de Meta / Anuncios Click-to-WhatsApp (CTWA)

Guía de uso, configuración y URLs del módulo de **medición de anuncios de
Facebook/Instagram** que dirigen a WhatsApp (Click-to-WhatsApp).

El objetivo: saber **qué conversaciones entraron por un anuncio**, de qué
campaña/anuncio vinieron, y medir resultados (leads, clientes, conversión) —
y opcionalmente traer nombres y gasto desde la cuenta publicitaria.

> **Todo es por sesión.** La configuración de anuncios vive en `ConfigMeta`,
> que es `OneToOne` con la sesión de WhatsApp. Cada número/sesión tiene su
> propia conexión de anuncios, igual que WhatsApp, Instagram y Messenger.

---

## 1. Qué mide hoy (sin configurar nada extra)

Cuando un usuario toca un anuncio **Click-to-WhatsApp** y escribe, Meta manda
en el webhook un bloque `referral`. El sistema lo captura automáticamente:

- `whatsapp/meta_webhook_view.py` extrae `referral` del mensaje entrante.
- `whatsapp/procesar_mensaje.py` lo guarda en:
  - `Contacto.referral_meta` (JSON crudo del anuncio).
  - `ConversacionWhatsApp`: `ad_id`, `adset_id`, `campaign_id`, `ctwa_clid`,
    `referral_source_type`, `referral_headline`, `referral_body`,
    `referral_source_url`, `referral_medium`, `referral_payload_json`,
    `origen_canal`.

En el chat (`/whatsapp/conversaciones/`) aparece el badge **"Anuncio"** en el
header cuando la conversación tiene atribución.

En **Analytics** (`/whatsapp/analytics/`) hay una tabla **ROI por CTWA** que
agrupa por `campaign_id` / `ad_id` con total de conversaciones, leads, clientes
y % de conversión.

**Requisitos para que haya atribución:**
- La sesión debe ser **Meta Cloud API** (Baileys no recibe `referral`).
- El anuncio debe ser **Click-to-WhatsApp** (destino WhatsApp).
- Meta no siempre manda `campaign_id`/`ad_id`; a veces solo `ctwa_clid`.

---

## 2. Conectar la cuenta publicitaria (Marketing API)

Esto agrega lo que hoy falta: **nombres legibles** de campaña/anuncio y
**gasto/resultados** traídos desde la cuenta de anuncios.

### ¿Mismos datos de WhatsApp o conexión aparte?

Es el **mismo Meta Business y el mismo System User** — NO un login aparte —
pero el token necesita un permiso extra y hay que conocer el ID de la cuenta
publicitaria.

| | WhatsApp (ya configurado) | Anuncios (a configurar) |
|---|---|---|
| Identificador | `waba_id` + `phone_number_id` | `ad_account_id` (act_XXXX) |
| Scope del token | `whatsapp_business_messaging`, `whatsapp_business_management` | **`ads_read`** (lectura de insights) |

### Pasos en Meta (Business Settings)

1. **Usuarios del sistema** → usá el mismo System User que genera el token de
   WhatsApp.
2. Asignale la **cuenta publicitaria** (Ad Account) con acceso a rendimiento.
3. Generá un token que incluya, además de los scopes de WhatsApp, **`ads_read`**.
   Un solo token puede tener todos los scopes (podés reusar el de WhatsApp si
   lo regenerás con `ads_read`).
4. Copiá el **`ad_account_id`** (formato `act_XXXXXXXX`) desde el Administrador
   de Anuncios → Configuración de la cuenta.

> Si el token de WhatsApp **no** tiene `ads_read`, pegá un token aparte (con ese
> scope) en el campo "Token de anuncios". Si lo dejás vacío, se usa el token de
> WhatsApp.

### Dónde configurar en la app

`/whatsapp/sesiones/` → en la tarjeta de la sesión Meta → menú **⋮** →
**"Conectar anuncios (Click-to-WhatsApp)"**.

En el modal:
- **Cuenta publicitaria (act_XXXX)**: pegá el `ad_account_id`.
- **Token de anuncios (opcional)**: dejalo vacío para reusar el de WhatsApp,
  o pegá uno con `ads_read`.
- **Probar conexión**: verifica que el token pueda leer la cuenta (devuelve
  nombre de la cuenta, moneda y gasto).
- **Guardar**.

---

## 3. URLs y endpoints

| URL | Método | Para qué |
|-----|--------|----------|
| `/whatsapp/sesiones/` | GET `?action=ads_config_modal&pk=<sesion_id>` | Abre el modal de conexión de anuncios |
| `/whatsapp/sesiones/` | POST `action=ads_guardar_config` | Guarda `ad_account_id` + `ads_access_token` (params: `sesion_id`, `ad_account_id`, `ads_access_token`) |
| `/whatsapp/sesiones/` | POST `action=ads_probar` | Prueba la conexión a la Marketing API (param: `sesion_id`) |
| `/whatsapp/conversaciones/` | GET `?action=ver_mensajes` | Devuelve, entre otros, el bloque `referral` de la conversación (badge "Anuncio") |
| `/whatsapp/analytics/` | GET `?action=data` | Devuelve `roi_ctwa` (agrupado por campaña/anuncio) + `por_canal` |
| `/whatsapp/meta_webhook/` | POST | Webhook entrante de Meta — captura el `referral` del anuncio |

Las acciones de sesión pasan por el dispatcher `_ACCIONES` en
`whatsapp/view_sesiones.py`.

---

## 4. Modelos y campos

### `ConfigMeta` (`whatsapp/models.py`) — por sesión
- `ad_account_id` — cuenta publicitaria (`act_XXXX`).
- `ads_access_token` — token con `ads_read` (encriptado, opcional; cae a `access_token`).
- `ads_ultima_sincronizacion` — auditoría de última lectura de la Marketing API.

### `ConversacionWhatsApp` — atribución capturada del webhook
- `ad_id`, `adset_id`, `campaign_id`, `ctwa_clid`, `origen_canal`,
  `referral_source_type`, `referral_headline`, `referral_body`,
  `referral_source_url`, `referral_medium`, `referral_payload_json`.
- `capi_lead_enviado`, `capi_purchase_enviado` — control de reporte a CAPI.

### `Contacto`
- `referral_meta` — JSON crudo del anuncio por el que entró el contacto.

### `AnuncioMetaCache` — caché de nombres (Fase 2)
- `ad_id` (único), `ad_name`, `adset_id`, `adset_name`, `campaign_id`,
  `campaign_name`, `effective_status`, `ultima_sync`.
- Se llena al abrir conversaciones con `ad_id`: si no está cacheado (o venció el
  TTL de 24 h) se consulta la Marketing API una vez y se guarda. Analytics lee
  solo de esta caché (no pega a Meta) para mantener el dashboard rápido.

> **No confundir** con el modelo `Campana` (`whatsapp/view_campanas.py`): eso
> son **envíos masivos salientes** (broadcast), no anuncios de Meta.

---

## 5. Servicio: `whatsapp/services_ads.py`

`MetaAdsService(config_meta)` — cliente de solo lectura de la Marketing API:

- `probar_conexion()` → valida el token y devuelve nombre/moneda/gasto de la cuenta.
- `info_anuncio(ad_id)` → nombre del anuncio + adset + campaña para un `ad_id`.
- `insights(date_preset|time_range, level='ad', ad_ids=None)` → gasto,
  impresiones, clicks, CPC, CPM y acciones por anuncio.

Helpers:
- `ads_service_para_sesion(sesion)`.
- `resolver_anuncio(config_meta, ad_id, refrescar=False)` → cache-first; resuelve
  y cachea nombres en `AnuncioMetaCache`. Best-effort (nunca lanza).
- `nombres_de_anuncios(ad_ids)` → lee solo de caché (para Analytics).

---

## 6. Conversions API (CAPI) — cerrar el loop con Meta

Ya implementada en `meta/capi.py`. Reporta **Lead** / **Purchase** de vuelta a
Meta usando el `ctwa_clid`, para que Ads Manager atribuya y optimice las
campañas.

**Checklist para que funcione:**
- Debe existir un `PixelMeta` configurado: `pixel_id` + `access_token` (scope
  `ads_management`) + (opcional) `test_event_code`.
- Sin fila `PixelMeta`, no se reporta nada.
- Cada evento se registra en `EventoCAPI` (auditoría: status, respuesta, error).

---

## 7. Requisito de despliegue

El módulo agrega campos a `ConfigMeta`, así que requiere migración:

```bash
python manage.py makemigrations whatsapp
python manage.py migrate
```

En producción, además: `collectstatic` + deploy de templates/JS.

---

## 8. Roadmap (fases)

- **Fase 1 — Conexión Marketing API** ✅ (`ad_account_id`, token, probar conexión).
- **Fase 2 — Nombres** ✅ al abrir una conversación con `ad_id` se resuelve y
  cachea el nombre de campaña/anuncio (`AnuncioMetaCache`); el chat muestra
  "Campaña: X" y Analytics reemplaza los IDs por nombres cuando están cacheados.
- **Fase 3 — Tablero de campañas:** vista que agrupe conversaciones por campaña
  cruzando `insights()` (gasto/CPL/ROAS) con leads/clientes propios.
- **Fase 4 — Filtro en `/conversaciones/`** por campaña/anuncio.
