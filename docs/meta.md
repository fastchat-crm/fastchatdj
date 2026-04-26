# Paquete `meta/` — integración con Meta (WhatsApp + Instagram + Messenger + Ads)

Toda llamada directa a Graph API vive en este paquete. La regla es simple:
**si tu código manda un `requests.get` o `requests.post` a `graph.facebook.com`,
debe estar en `meta/`** (o importar un helper del paquete).

## Por qué existe

Antes la lógica estaba dispersa:

```
whatsapp/services_meta.py        → envío WA Cloud
whatsapp/services_instagram.py   → DMs IG y FB
whatsapp/services_capi.py        → Conversions API
whatsapp/common_meta.py          → credenciales + HMAC + handshake
whatsapp/sesiones_common.py      → perfiles IG/FB/WA mezclados
seguridad/view_credencial_meta.py → autodetect + validador inline en la vista
```

Ahora está organizado por dominio para que cualquiera identifique en
segundos a qué API se está hablando — WhatsApp, IG, Messenger o Ads.

## Estructura

```
meta/
├── __init__.py          # re-exporta lo público
│
├── ── Núcleo compartido ──
├── urls.py              # build_graph_url(), build_fb_url(), GRAPH_API_VERSION
├── credenciales.py      # get_meta_app_credentials(), get_meta_config_id()
├── webhook.py           # validar_firma_hmac, handshake, extractores payload
├── autodetect.py        # auto_detectar_meta() — App+Business+config_id
├── validacion.py        # validar_credenciales() — checklist completo
├── perfiles.py          # validar_instagram/messenger/sincronizar_meta_desde_graph
│
└── ── Senders por canal ──
    ├── whatsapp.py      # MetaWhatsAppService → WA Cloud (envío, plantillas, media)
    ├── instagram.py     # InstagramService + MessengerService → DMs
    └── capi.py          # Conversions API → eventos Lead/Purchase para Ads Manager
```

## Cómo usar cada módulo

### `meta.urls` — armar URLs de Graph

```python
from meta.urls import build_graph_url, build_fb_url

build_graph_url('/me')                    # → https://graph.facebook.com/v22.0/me
build_graph_url(f'/{app_id}/businesses')  # → .../v22.0/{app_id}/businesses
build_fb_url('/dialog/oauth')             # → https://www.facebook.com/v22.0/dialog/oauth
```

La versión de la API se resuelve cada vez que llamás (lee `settings.META_API_VERSION`)
para que un upgrade global sea un solo cambio en `credenciales.json`.

### `meta.credenciales` — leer credenciales

```python
from meta.credenciales import (
    get_meta_app_credentials,   # → (app_id, app_secret)
    get_meta_app_secret,        # solo el secret, para HMAC
    get_meta_config_id,         # config_id del Embedded Signup
)
```

**Prioridad:**
1. `CredencialMetaApp` en BD (singleton vinculado a `Configuracion`).
2. Fallback a `settings.META_APP_ID` / `META_APP_SECRET` / `META_CONFIG_ID`
   (de `credenciales.json`) — esto permite bootstrap antes de que el admin
   complete el form en `/seguridad/credencial-meta/`.

Si tocás el form de credenciales, el helper levanta los nuevos valores
automáticamente — no hay que reiniciar.

### `meta.webhook` — recibir eventos firmados

```python
from meta.webhook import (
    validar_firma_hmac,
    responder_handshake,
    extraer_phone_number_id,
    extraer_ig_user_id,
    extraer_page_id,
    extraer_tipo_evento,
)

# 1) Verificar handshake GET (verify_token)
ok, body, status = responder_handshake(request, mi_verify_token)
if status:
    return HttpResponse(body, status=status)

# 2) Validar firma del POST
secret = get_meta_app_secret()
if not validar_firma_hmac(raw_body, request.headers.get('X-Hub-Signature-256'), secret):
    return HttpResponse(status=403)

# 3) Routing por canal
phone_id = extraer_phone_number_id(payload)   # → WA Cloud
ig_id    = extraer_ig_user_id(payload)        # → Instagram
page_id  = extraer_page_id(payload)           # → Messenger
tipo     = extraer_tipo_evento(payload)       # 'messages' | 'postback' | 'reaction' | …
```

### `meta.autodetect` — pre-llenar el form de credenciales

Detecta automáticamente App name, Business ID/name, System User ID, scopes,
expiración del token y — si Meta lo expone — el `config_id` del Embedded Signup.

```python
from meta.autodetect import auto_detectar_meta

resultado = auto_detectar_meta(app_id, app_secret, system_user_token)
# {
#   'error': False,
#   'detectado': {
#       'app_name': 'Mi App',
#       'business_id': '947754161299617',
#       'business_name': 'Mi Negocio',
#       'system_user_id': '122099870312601156',
#       'scopes': ['whatsapp_business_management', ...],
#       'expires_at': 0,    # 0 = never
#       'config_id': '1234567890',   # si lo encontró
#       'config_options': [...],     # si encontró varios — UI muestra picker
#       'hint': 'Mensaje HTML accionable si falta algo'
#   }
# }
```

Lo usa el botón **Auto-detectar** del form `/seguridad/credencial-meta/`.

### `meta.validacion` — checklist de credenciales

```python
from meta.validacion import validar_credenciales

checks = validar_credenciales(
    app_id, app_secret, business_id, system_user_id, system_user_token, config_id,
)
# [
#   {'label': 'App ID + Secret', 'ok': True, 'detalle': 'App: Mi App', 'severidad': 'ok'},
#   {'label': 'System User Token', 'ok': True, 'detalle': 'Never expires', 'severidad': 'ok'},
#   {'label': 'Scopes requeridos', 'ok': True, 'detalle': '3/3 presentes', 'severidad': 'ok'},
#   {'label': 'WABAs accesibles', 'ok': True, 'detalle': '2 encontrada(s): ...', 'severidad': 'ok'},
#   ...
# ]
```

Devuelve lista para que la UI pinte cada item con su severidad
(`ok` / `warning` / `error`).

### `meta.perfiles` — verificar perfil de cada canal

Cada función pingea Graph con las credenciales guardadas y persiste lo
visible (username, page_name, display_phone) + `ultima_sincronizacion`.

```python
from meta.perfiles import (
    sincronizar_meta_desde_graph,        # WhatsApp — actualiza display_phone, quality, tier
    validar_instagram_desde_graph,       # IG — actualiza username
    validar_messenger_desde_graph,       # Messenger — actualiza page_name
)

ok, info = sincronizar_meta_desde_graph(session, session.config_meta)
ok, info = validar_instagram_desde_graph(session, session.config_instagram)
ok, info = validar_messenger_desde_graph(session, session.config_messenger)
```

### `meta.whatsapp` — envío WhatsApp Cloud API

```python
from meta.whatsapp import MetaWhatsAppService

svc = MetaWhatsAppService(sesion)
svc.send_text_message(numero, texto)
svc.send_media_message(numero, archivo, tipo='image')
svc.send_template(numero, plantilla, variables)
svc.send_presence_update(numero, 'composing')

# Plantillas
svc.crear_plantilla_en_meta(plantilla)
svc.sincronizar_plantillas()
svc.descargar_media(media_id)
```

El helper `whatsapp.services.get_whatsapp_service(sesion)` devuelve esta
clase si `sesion.proveedor == 'meta'` o `WhatsAppService` (Baileys) si es
`'baileys'`. Las dos clases tienen la misma interfaz pública.

### `meta.instagram` — DMs Instagram + Messenger

```python
from meta.instagram import InstagramService, MessengerService

ig = InstagramService(sesion)
ig.send_text_message(igsid_destinatario, texto)
ig.send_media_message(igsid, archivo, tipo='image')

fb = MessengerService(sesion)   # hereda de InstagramService
fb.send_text_message(psid_destinatario, texto)
```

### `meta.capi` — Conversions API (Ads)

Dispara eventos al Pixel/Dataset de Meta para que Ads Manager pueda
optimizar y atribuir campañas (especialmente CTWA — click-to-WhatsApp).

```python
from meta.capi import (
    enviar_evento,
    reportar_lead_si_corresponde,
    reportar_purchase,
)

# Lead — disparar cuando un nuevo contacto entra al CRM por CTWA
reportar_lead_si_corresponde(conversacion)

# Purchase — disparar cuando se cierra una venta
reportar_purchase(conversacion, value=Decimal('59.90'), currency='USD')

# Genérico
enviar_evento(conversacion, event_name='CompleteRegistration', custom_data={...})
```

Cada llamada se registra en `EventoCAPI` para auditoría y reintento.

## Compatibilidad con código viejo

Los archivos legacy siguen funcionando como shims que re-exportan de
`meta/`. Si encontrás algo viejo importando así, no rompe nada:

| Legacy | Reexporta de |
|---|---|
| `whatsapp/services_meta.py` | `meta.whatsapp` |
| `whatsapp/services_instagram.py` | `meta.instagram` |
| `whatsapp/services_capi.py` | `meta.capi` |
| `whatsapp/common_meta.py` | `meta.credenciales` + `meta.webhook` |
| `whatsapp/sesiones_common.py` (sólo las `validar_*`) | `meta.perfiles` |
| `seguridad/view_credencial_meta.py` aliases `_auto_detectar_meta` / `_validar_credenciales` | `meta.autodetect` + `meta.validacion` |

**Para código nuevo**, siempre preferí la forma directa:

```python
# antes (sigue funcionando):
from whatsapp.services_meta import MetaWhatsAppService

# después (preferido):
from meta.whatsapp import MetaWhatsAppService
```

## Cómo agregar una nueva llamada a Graph

1. Identificá el canal: ¿es WA Cloud, IG, Messenger o CAPI?
2. Abrí el módulo correspondiente (`meta/whatsapp.py`, etc.) y agregá tu
   función o método.
3. **Siempre** usá `meta.urls.build_graph_url()` — no escribas
   `https://graph.facebook.com/v22.0/...` literal.
4. **Siempre** leé credenciales con los helpers de `meta.credenciales` —
   no leas `settings.META_*` directo.
5. Si es un endpoint nuevo y reusable, agregalo al `__init__.py` para
   exportarlo.

## Troubleshooting

### "Faltan credenciales Meta"
Falta cargar `App ID + App Secret + Embedded Signup Config ID` en
`/seguridad/credencial-meta/`. El fallback a `credenciales.json` solo es
para bootstrap inicial — preferí siempre BD.

### "Auto-detect no encontró el config_id"
Meta gatea ese endpoint. Abrí
`developers.facebook.com/apps/{app_id}/whatsapp-business/wa-embedded-signup/`,
copiá el Configuration ID y pegalo manualmente en el form.

### Quiero subir la versión de Graph (v22 → v23)
Editá `META_API_VERSION` en `credenciales.json` y reiniciá. Todo
`meta/*` lo levanta vía `meta.urls`.

### Quiero ver qué eventos llegaron por webhook
Cada POST a `/whatsapp/meta_webhook/` se registra en `EventoMetaRecibido`
(`whatsapp/models.py`) con payload, validez de HMAC y flag de procesado.
La UI está en el admin Django.

## Migraciones recientes

| Migration | Cambio |
|---|---|
| `seguridad.0011_credencialmetaapp_config_id` | Agrega `config_id` al modelo `CredencialMetaApp` |
