# Configuración de Credenciales Meta App — Guía Completa

> Documento autocontenido para pegar a un asistente IA y recibir guía paso a paso sobre cómo configurar la Meta App en Facebook Developers / Business Manager.

---

## 1. Contexto del Sistema

**FastChat DJ** es un CRM Django con WhatsApp + Instagram + Messenger. Una **única Meta App** administra todas las cuentas (WhatsApp Business, Instagram Business, Páginas de Facebook) de la organización. Las credenciales se cargan **una sola vez** en `/seguridad/credencial-meta/` y se almacenan cifradas (Fernet) en la tabla `seguridad_credencialmetaapp`.

**Relación:**
- `Configuracion` (singleton de la organización) → `CredencialMetaApp` (OneToOne).
- Cada `SesionWhatsApp` con `proveedor='meta'` → `ConfigMeta` (OneToOne) que contiene **WABA ID**, **Phone Number ID**, **access token específico de esa sesión**, **webhook verify token**, etc.
- Las credenciales en `CredencialMetaApp` (App ID, App Secret, System User Token, Embedded Signup Config ID) son a **nivel App** y son las que permiten:
  - Validar firmas HMAC de webhooks Meta (App Secret).
  - Listar WABAs/Páginas/IG accesibles.
  - Lanzar el flujo **Embedded Signup** para que el cliente conecte su WABA con un solo clic (Config ID).

---

## 2. Modelo de Datos: `CredencialMetaApp`

```python
class CredencialMetaApp(ModeloBase):
    configuracion       = OneToOneField(Configuracion)
    app_id              = CharField(max_length=50)                 # Meta App ID
    app_secret          = EncryptedTextField()                     # Cifrado Fernet
    config_id           = CharField(max_length=50, blank=True)     # Embedded Signup Config ID
    business_id         = CharField(max_length=50, blank=True)     # Business Manager ID
    system_user_id      = CharField(max_length=50, blank=True)
    system_user_token   = EncryptedTextField(blank=True, null=True) # Cifrado Fernet
    es_tech_provider    = BooleanField(default=False)              # Driver del modo de alta de sesiones
```

### 2.1 Modos de alta de sesión (driven by `es_tech_provider`)

El modal "Agregar conexión → WhatsApp Cloud API" en `/whatsapp/sesiones/` tiene tres caminos:

| `es_tech_provider` | `config_id` | `app_id`+`secret` | Modo | Comportamiento |
|---|---|---|---|---|
| — | — | falta | `sin_credenciales` | Alert rojo, botón disabled |
| `False` | cualquiera | OK | **`manual`** | Form de carga manual (WABA ID + Phone Number ID + token) |
| `True` | falta | OK | `manual` (degradado) | Idem manual |
| `True` | OK | OK | **`oauth`** | Popup Embedded Signup (un solo clic) |

**Cuando Meta apruebe Tech Provider**: marcar el checkbox `es_tech_provider` en `/seguridad/credencial-meta/` → cargar/verificar el `config_id` → guardar. El modal cambia automático.

---

## 3. Formulario en la UI

URL: `/seguridad/credencial-meta/`

| Campo | Obligatorio | Tipo | Notas |
|---|---|---|---|
| Meta App ID | Sí | text | ~16 dígitos |
| Meta App Secret | Sí | password | Se guarda cifrado |
| Business Manager ID | No | text | Se autodetecta |
| System User ID | No | text | Se autodetecta con token |
| System User Token | No (recomendado) | password | Long-lived, "never expires" |
| Embedded Signup Config ID | No (manual) | text | ~16 dígitos. Meta gatea la API |

Botones: **Auto-detectar desde Meta**, **Validar credenciales**, **Generar System User Token**, **Guardar**.

---

## 4. Cómo Obtener Cada Dato en Meta

### 4.1 Meta App ID + App Secret

1. Ir a [developers.facebook.com/apps](https://developers.facebook.com/apps/) (con la cuenta Facebook del admin del negocio).
2. **Create App** (si no existe) → tipo **"Business"** → agregar productos:
   - **WhatsApp** (obligatorio para Cloud API)
   - **Facebook Login for Business** (necesario para Embedded Signup)
   - **Instagram** y **Messenger** (opcional, según canales).
3. Menú izquierdo → **App settings → Basic**:
   - **App ID** → arriba a la izquierda, debajo del nombre de la app (~16 dígitos).
   - **App Secret** → campo "App secret" → pulsar **Show** (Meta pedirá password de Facebook).
4. Configurar también en esa misma pantalla:
   - **App Domains**: dominio del CRM (ej. `app.miempresa.com`).
   - **Privacy Policy URL** + **Terms of Service URL** (obligatorios para pasar a modo Live).
   - **Category**: ej. "Business and Pages".

> ⚠️ **Modo App**: para producción, la app debe estar en **Live** (no **Development**). Toggle arriba a la derecha. Live exige Privacy Policy + verificación de business si se usan permisos avanzados.

### 4.2 Business Manager ID

1. Ir a [business.facebook.com/settings](https://business.facebook.com/settings).
2. Arriba a la izquierda, debajo del nombre del negocio, aparece el **Business ID**.
3. **Pre-requisitos**:
   - Business **verificado** o en proceso de verificación (Meta verifica documentos legales del negocio).
   - La Meta App debe estar **asociada al Business**: Business Settings → **Apps** → **Add** → buscar la App por ID.

### 4.3 System User ID + System User Token

1. [business.facebook.com/settings/system-users](https://business.facebook.com/settings/system-users).
2. Si no hay ninguno: **Add** → tipo **Admin** → nombre descriptivo (ej. "fastchat-system-user").
3. **Asignar activos al System User**: botón **Add Assets**:
   - **WhatsApp Accounts** → seleccionar la WABA → permiso **Full control**.
   - **Pages** (si Messenger) → permiso **Full control**.
   - **Instagram Accounts** (si IG) → permiso **Full control**.
   - **Apps** → seleccionar la Meta App del paso 4.1 → permiso **Develop**.
4. **System User ID**: aparece al lado del nombre del system user.
5. **Generate New Token**:
   - Seleccionar la **App** del paso 4.1.
   - **Token expiration**: **Never** (long-lived).
   - **Permissions/Scopes** (marcar todos los aplicables):
     - `whatsapp_business_management` ✅ obligatorio
     - `whatsapp_business_messaging` ✅ obligatorio
     - `business_management` ✅ obligatorio
     - `pages_messaging` (Messenger)
     - `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata` (Messenger)
     - `instagram_basic`, `instagram_manage_messages` (Instagram)
     - `ads_management`, `ads_read` (Meta CAPI / Pixel)
   - **Generate Token** → **copiar una sola vez** (Meta no lo vuelve a mostrar).

> 🔒 El token se guarda **cifrado** en la base de datos del CRM (Fernet via `EncryptedTextField`). No queda en logs ni en backups planos.

### 4.4 Embedded Signup Config ID

Es el ID de la configuración de **Embedded Signup de WhatsApp** — el flujo que abre el popup de Meta para que el cliente final conecte su propia WABA al CRM con un solo clic (sin que el operador del CRM tenga que pedirle credenciales).

> ⚠️ **Meta gatea este dato vía API**: sólo cuentas con rol **Tech Provider** lo ven a través de Graph. Para todos los demás, hay que sacarlo a mano.

**Pasos:**

1. [developers.facebook.com/apps](https://developers.facebook.com/apps/) → tu App.
2. Menú izquierdo → **WhatsApp → Embedded Signup** (en algunas cuentas: **WhatsApp → Configuration**).
3. Si no hay configuration creada: pulsar **Create configuration**:
   - **Setup type**: `WhatsApp Business App Onboarding`
   - **Features**: `cloud_api` + `marketing_messages_lite` + `conversions_api`
   - **Permissions**:
     - `whatsapp_business_management`
     - `whatsapp_business_messaging`
     - `business_management`
   - **Save**.
4. Copiar el **Configuration ID** (~16 dígitos) y pegarlo en el campo del formulario.

**Si el menú no aparece:**
- Verificar que la app tenga el producto **WhatsApp** agregado.
- Verificar que el rol del usuario en la app sea **Admin** o **Developer**.
- Verificar que la app esté asociada al Business Manager (algunas opciones aparecen solo así).

---

## 5. Auto-Detect (Endpoint `/seguridad/credencial-meta/?action=auto_detect`)

El backend (`meta/autodetect.py`) llama a Graph API con los datos parciales que tenga y rellena el resto. Endpoints que prueba:

| Dato | Endpoint Graph | Auth |
|---|---|---|
| App name | `GET /{app_id}?fields=id,name,namespace,category` | App access token (`{app_id}|{app_secret}`) |
| Business ID (owner) | `GET /{app_id}?fields=business{id,name}` | App access token |
| Business ID (owner alt) | `GET /{app_id}?fields=owner_business{id,name}` | App access token |
| Business ID (fallback) | `GET /me/businesses?fields=id,name` | System User Token |
| System User ID + scopes + expiración | `GET /debug_token?input_token=<sysToken>&access_token=<appToken>` | App access token |
| Embedded Signup configs | `GET /{app_id}/whatsapp_business_solution_configurations` | App access token |
| Embedded Signup configs (alt) | `GET /{app_id}/whatsapp_solution_configurations` | App access token |

**Limitación**: los endpoints de configurations devuelven **403/404** salvo para Tech Providers. El sistema captura el error y muestra hint con instrucciones manuales (sección 4.4).

---

## 6. Validador (Endpoint `/seguridad/credencial-meta/?action=validar`)

Corre 7 verificaciones (`meta/validacion.py`) y muestra resultado en un modal:

| # | Check | Endpoint Graph | Falla si... |
|---|---|---|---|
| 1 | **App ID + Secret** | `GET /{app_id}?fields=id,name` con app token | Meta rechaza credenciales |
| 2 | **System User Token** | `GET /debug_token` | Token inválido o expirado |
| 3 | **Scopes requeridos** | (de la respuesta de debug_token) | Faltan `whatsapp_business_management`, `whatsapp_business_messaging` o `business_management` |
| 4 | **System User ID coincide** | (compara `data.user_id` del debug_token con el del form) | Discrepancia |
| 5 | **Business Manager ID** | `GET /{business_id}?fields=id,name` con system user token | Token sin acceso al business |
| 6 | **WABAs accesibles** | `GET /{business_id}/owned_whatsapp_business_accounts` | El business no tiene WABAs asociadas |
| 7 | **Embedded Signup Config ID** | `GET /{app_id}/whatsapp_business_solution_configurations` | El config_id no aparece, **o** Meta gatea el endpoint (warning, no error) |

Severidades: `ok` / `warning` (campo opcional sin configurar, o no verificable) / `error` (rechazo duro de Meta).

---

## 7. Pre-requisitos en Meta antes de Conectar

- [ ] Business Manager creado y **verificado** (o en proceso).
- [ ] Meta App en modo **Live** (no Development) para producción.
- [ ] Producto **WhatsApp → Cloud API** agregado a la App.
- [ ] WABA creada y al menos un **número de teléfono** verificado.
- [ ] System User con permiso **Admin** sobre la WABA y la App.
- [ ] Privacy Policy URL y Terms of Service URL configurados en App Settings → Basic.
- [ ] Webhooks: configurar la URL `https://<tu-dominio>/whatsapp/meta_webhook/` con verify token (se setea por sesión en `ConfigMeta.webhook_verify_token`) y suscribir a los eventos `messages`, `message_template_status_update`, `account_review_update`, `phone_number_quality_update`.

---

## 8. Errores Comunes

| Error | Causa | Solución |
|---|---|---|
| `(#100) Param app_id must be a valid app id` | App ID mal pegado | Re-copiar de App Settings → Basic |
| `Invalid OAuth access token signature` | App Secret mal pegado o app token mal armado | Verificar copia del Secret |
| `(#10) Permissions error` | System User no tiene permiso sobre la WABA | Business Settings → System Users → Add Assets → WhatsApp Accounts |
| `Token has expired` | Token NO es "never expires" | Regenerar con expiración Never |
| Embedded Signup endpoints devuelven `403` | Cuenta no es Tech Provider | Pegar Config ID a mano |
| Webhook verify falla | `webhook_verify_token` distinto entre Meta y `ConfigMeta` | Sincronizar el valor exacto |
| Firma HMAC inválida en webhooks | App Secret mal cargado | Re-cargar el Secret |
| Business Manager ID rechazado | App no asociada al Business | Business Settings → Apps → Add |

---

## 9. Pregunta para el Asistente

**Necesito ayuda para:**
1. _(describir aquí lo que falla — ej. "No encuentro el menú WhatsApp → Embedded Signup en mi app")_
2. _(o pegar el error exacto que devuelve Meta)_
3. _(o pegar el resultado del botón "Validar credenciales" del CRM)_

**Datos que ya tengo cargados:**
- App ID: `_______` (puedo pegarlo, no es secreto)
- Business ID: `_______`
- System User ID: `_______`
- Scopes detectados en el token: `_______`
- Config ID: `_______` (o "no lo encuentro")

**Lo que NO comparto** (son secretos): App Secret, System User Token.
