# Stack Técnico & Dependencias — fastchatdj

CRM WhatsApp con IA. Stack y versiones críticas.

---

## Core Framework

### Django
**Versión:** 4.x
**Settings clave:**
- `LANGUAGE_CODE = 'es-mx'` (o `es`)
- `TIME_ZONE = 'America/Guayaquil'` (UTC-5)
- `USE_TZ = True`
- `AUTH_USER_MODEL = 'autenticacion.Usuario'`

### Python
3.8+ (recomendado 3.10/3.11)

---

## Real-time (Channels)

### Django Channels + Daphne
WebSocket consumers en `whatsapp/consumers.py`:
- `ChatConsumer` — chat por conversación
- `SessionConsumer` / `SessionRoomConsumer` — estado sesión / QR

**Servidor dev:**
```bash
daphne -b 0.0.0.0 -p 8000 fastchatdj.asgi:application
```

`runserver` no soporta WebSockets — usar Daphne para chat real.

### Channel Layer = Redis
```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [(REDIS_HOST, REDIS_PORT)]}
    }
}
```

---

## Base de datos

### PostgreSQL (única)
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        # ATOMIC_REQUESTS = True (vistas envueltas en transacción)
    }
}
```

Driver: `psycopg2-binary>=2.9`.

---

## Cache & Sessions

### Redis
```python
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': f'redis://{REDIS_HOST}:{REDIS_PORT}/1',
    }
}
```

Toggle por `credenciales['CACHES_REDIS']`. Usado para:
- Channel layer (chat)
- Cache flags (rate-limit `wa_rate_limited_<sid>`, heartbeat Node)
- Sesiones Django

---

## IA / LangChain

### LangChain + proveedores
- `langchain` + `langchain-google-genai` (Gemini)
- `langchain-openai` (alternativa)
- `langchain-community` (FAISS, loaders)

Configurado por agente vía `crm.AgentesIA.apikey` (M2M con `ApiKeyIA.provider`).

### Vectorstore
- `faiss-cpu` (índice on-disk por agente)
- `VectorStoreManager` en `agents_ai/vectorstore_manager.py`
- Carga PDF/CSV/JSON/XLSX, embeddings (Gemini default, OpenAI opcional)
- Cache en memoria por `mtime` (`agente_consultor.py:_faiss_cache`)

### Memoria conversación
`agents_ai/memoria_django.py` → `DjangoChatMessageHistory`. Persiste turnos en DB por `ConversacionWhatsApp.id`. Sólo últimos `_HISTORY_TURNS=4` van al prompt.

---

## WhatsApp — proveedores

### Baileys (legacy)
Vía servicio Node.js externo (`WHATSAPP_API_URL`). Auth compartida con `NODE_SECRET_KEY`.

### Meta Cloud API
Directo a Graph API (`graph.facebook.com/v<x>`). Auth por `ConfigMeta.access_token`.
Webhook firmado HMAC-SHA256 con `ConfigMeta.app_secret`.

Switch de transporte: `services.get_whatsapp_service(sesion)` retorna `WhatsAppService` o `MetaWhatsAppService` según `sesion.proveedor`.

---

## Frontend

### Bootstrap 4.x
**CRÍTICO:** NO Bootstrap 5. Componentes: cards, modals, tables, forms, badges, grid.

### jQuery 3.x
DOM, AJAX, eventos.

### DataTables 1.10.x
Listados. i18n: `/static/js/i18n/Spanish.json`.

### Select2 4.x
Auto-aplicado por `ModelFormBase` a ChoiceFields (clase `.jselect2`).

### SweetAlert2 LEGACY (~7.x)
**CRÍTICO:** sintaxis vieja. `type:` (no `icon:`), `result.value` (no `isConfirmed`). Ver `skills/sweetalert-legacy.md`.

### BlockUI
Loading overlay: `pantallaespera()` / `$.unblockUI()`.

### Switchery
Toggle switches para `BooleanField` (auto-aplicado por `ModelFormBase`).

---

## Generación documentos

### PDF — wkhtmltopdf
Binario externo. Path en `credenciales['WKHTMLTOPDF_CMD']`.
Wrapper Python: `pdfkit`.

### Excel
`openpyxl>=3.0` para reportes/exports.

### Imágenes
`Pillow>=9.0` — uploads, thumbnails, conversiones.

---

## Email

### SendGrid
- `SENDGRID_API_KEY` en credenciales
- SMTP: `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
- Templates HTML
- Threaded delivery

---

## Seguridad / Auth

### Hashing
PBKDF2 (default Django).

### Encriptación a nivel campo
Claves RSA: `private_key_enc.pem` / `public_key_enc.pem` (gitignored).
JS frontend usa `doRSA(...)` para encriptar inputs marcados `data-datoseguro="true"` antes de submit. Backend descifra.

### CSRF
Habilitado por defecto. Todo POST requiere token.

### VAPID (web push)
`vapid.json` para notificaciones browser push.

### Google API
`api_google_key.json` — credenciales servicio (Drive, Sheets, etc.).

---

## Despliegue

### Web server
Gunicorn (HTTP) + Daphne (WebSockets) detrás de Nginx.

### Reverse proxy
Nginx — SSL termination, static files, buffering.

### Process management
systemd: servicios separados para Gunicorn (HTTP) y Daphne (WS).

### OS
Ubuntu 20.04+ / 22.04 LTS

---

## Static files

```python
STATIC_ROOT = '...'
MEDIA_ROOT = '...'
STATICFILES_DIRS = [BASE_DIR / 'static']
```

```bash
python manage.py collectstatic --noinput
```

CSS específico de página → `static/stylenew/<pagina>.css`.

---

## Dev tools

- **Django Debug Toolbar** — sólo DEBUG=True
- **Django Extensions** — `shell_plus`, `show_urls`

---

## Configuración runtime

Todo via `credenciales.json` (gitignored). Sin variables de entorno.

```json
{
  "POSTGRES_HOST": "...", "POSTGRES_PORT": "...",
  "POSTGRES_DBNAME": "...", "POSTGRES_PASSWORD": "...",
  "SECRET_KEY": "...", "DEBUG": true,
  "USE_SSL": false, "DOMINIO_GENERAL": "...",
  "WINDOWS": true, "REDIS_HOST": "...", "REDIS_PORT": 6379,
  "WHATSAPP_API_URL": "...", "NODE_SECRET_KEY": "...",
  "EMAIL_HOST_USER": "...", "EMAIL_HOST_PASSWORD": "...",
  "SENDGRID_API_KEY": "...", "WKHTMLTOPDF_CMD": "C:/.../wkhtmltopdf.exe",
  "ID_GRUPO_CLIENTE": 1, "CACHES_REDIS": true
}
```

Otros gitignored: `private_key_enc.pem`, `public_key_enc.pem`, `api_google_key.json`, `vapid.json`.

---

## Pinning

`requirements.txt` con versiones exactas.

---

## Browsers

Chrome/Edge, Firefox, Safari (últimas 2 versiones). Móviles iOS/Chrome.
Bootstrap 4 = soporte amplio.

---

## Performance

- `select_related` / `prefetch_related` en queries
- `defer()` para campos pesados (media, payloads)
- Cache Redis para flags, heartbeat, sesiones
- FAISS in-memory cache por `mtime` del índice
- Límite turnos historial chat (`_HISTORY_TURNS=4`)

---

**Última revisión:** 2026-04-23
