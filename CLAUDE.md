# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastChat DJ is a Django-based WhatsApp CRM platform with AI chatbot capabilities. It manages WhatsApp sessions, conversations, and contacts, and integrates AI agents (via LangChain + Google Generative AI) for automated customer interaction.

## Setup

**Prerequisites:** Python 3.8+, PostgreSQL, Redis, wkhtmltopdf

```bash
# Install dependencies
pip install -r requirements.txt

# Create credentials file from template
cp credenciales_template.json credenciales.json
# Edit credenciales.json with real values (see below)

# Database setup
python manage.py migrate

# Run dev server (HTTP only)
python manage.py runserver

# Run with WebSocket support (required for chat)
daphne -b 0.0.0.0 -p 8000 fastchatdj.asgi:application
```

## Configuration

All secrets live in `credenciales.json` (gitignored). Required keys:

| Key | Purpose |
|-----|---------|
| `POSTGRES_HOST/PORT/DBNAME/PASSWORD` | Database |
| `SECRET_KEY` | Django secret |
| `DEBUG` | Boolean |
| `USE_SSL` | Enables HTTPS redirect |
| `DOMINIO_GENERAL` | Primary domain (no protocol) |
| `WINDOWS` | Set `true` on Windows dev machines |
| `REDIS_HOST/PORT` | Redis for channels and cache |
| `WHATSAPP_API_URL` | External WhatsApp API endpoint |
| `NODE_SECRET_KEY` | Shared secret with Node.js service |
| `EMAIL_HOST_USER/PASSWORD`, `SENDGRID_API_KEY` | Email via SendGrid |
| `WKHTMLTOPDF_CMD` | Absolute path to wkhtmltopdf binary |
| `ID_GRUPO_CLIENTE` | Django auth Group ID for client users |
| `CACHES_REDIS` | Boolean, enables Redis cache |

Additional gitignored files: `private_key_enc.pem`, `public_key_enc.pem`, `api_google_key.json`, `vapid.json`

## Running Tests

```bash
python manage.py test
python manage.py test <app_name>         # e.g. autenticacion
python manage.py test --keepdb           # reuse test DB
```

Note: Test files exist but are mostly empty stubs.

## Architecture

### Apps

| App | Responsibility |
|-----|----------------|
| `autenticacion` | Custom `Usuario` model (extends `AbstractUser`), client/admin profiles, login/logout/password recovery |
| `seguridad` | `Configuracion` singleton, role/module/URL access control (`Modulo`, `GroupModulo`), audit logs, companies, notifications, session tracking |
| `area_geografica` | Hierarchical geodata: País → Provincia → Ciudad → Parroquia |
| `whatsapp` | WhatsApp session management, contacts, conversations, messages, WebSocket consumers, webhook handler |
| `crm` | Business profile (`PerfilNegocioIA`), AI agents (`AgentesIA`), training data, products/services, chatbot departments |
| `agents_ai` | LangChain-based AI agents: `AgenteConsultor` (Q&A), `AgenteResumidor` (summarization), FAISS vector store management |
| `core` | Shared base models, helper functions, AJAX handler (`ConsultasAjax`), middleware, encryption utilities |
| `public` | Unauthenticated views: registration, login, password recovery |
| `cron_jobs` | Background scheduled tasks (farewell messages, scheduled dispatch) |

### Key Patterns

**URL Registration:** URLs are defined as dicts in each app's `urls.py` and registered centrally in `fastchatdj/urls.py`. The `urls_sistema` tuple drives both Django URL routing and the `Modulo` database table (which controls sidebar navigation and role-based access). When adding a new view, add it to both the app's `urls.py` list and ensure a `Modulo` record exists.

**AJAX API:** Most frontend interactions use the `ConsultasAjax` view at `/ajaxrequest/<accion>/` and the `consultas` view at `/consultas/`. These dispatch to handlers based on the `accion` parameter.

**Permissions / Role Access:** Access control is done via `GroupModulo` (which groups relate to which `Modulo` URLs). The `seguridad` app middleware checks if the user's group has access to the current URL.

**Singleton Config:** `Configuracion.get_instancia()` returns the single site-wide config row (company name, logos, email templates, etc.). It is accessed at module load time in `urls.py`.

**WebSockets:** Django Channels handles three WebSocket consumers in `whatsapp/`:
- `ChatConsumer` — real-time chat per conversation, broadcasts rendered HTML partials on new messages
- `SessionConsumer` / `SessionRoomConsumer` — WhatsApp session status (QR code, connect/disconnect)

**AI Pipeline:** `agents_ai` uses LangChain with Google Generative AI embeddings stored in FAISS vector stores. `AgentesIA` records in `crm` configure which agent handles each WhatsApp session. Training documents uploaded via `EntrenamientosIA` are embedded and stored per agent. The FAISS index is cached in-memory keyed by `mtime` to avoid reloads between messages (`agente_consultor.py:_faiss_cache`). Each agent can also have a `contexto_estatico` field (plain text injected directly into the prompt without embedding, for small documents like FAQs).

**Base Models:** `core.custom_models.ModeloBase` (abstract) and `NormalModel` are the base classes for most models. `ModeloBase` adds `usuario_creacion`, `fecha_registro`, `usuario_modificacion`, `fecha_modificacion`, `status` (soft-delete flag). It auto-populates audit fields from the current request via `core.custom_middleware.get_current_request()`. `NormalModel` adds convenience attributes like `<field>_boolhtml`, `<field>_yesorno`, `<field>_money` dynamically on `__init__`.

### WhatsApp Integration Flow

```
External WhatsApp API (Node.js service)
    ↓ webhook POST to /whatsapp/webhook_handler/
    ↓ NODE_SECRET_KEY verified
webhook_handler creates/updates:
    MensajeWhatsApp, ConversacionWhatsApp, Contacto, EstadisticasConversacion
    ↓
async_to_sync → channel_layer.group_send → ChatConsumer broadcasts rendered HTML to frontend
    ↓ (if AI enabled: SesionWhatsApp.agente_ia is set)
AgenteConsultor.responder() → FAISS similarity search → LangChain prompt → Google Generative AI
    ↓
WhatsAppService.send_message() → WHATSAPP_API_URL (Node.js)
```

**Webhook event types handled:** `qr_code`, `ready`, `authenticated`, `auth_failure`, `disconnected`, `rate_limited`, `message`, `message_sent`, `message_reaction`, `message_revoked`, `message_ack`, `contact_changed`, `group_join`, `group_leave`.

**Rate-limit handling:** When the Node.js service hits its per-session send cap, it emits a `rate_limited` event with `{count, max, windowMs, retryAfterMs, windowStart}`. Django stores a cache flag `wa_rate_limited_<session_id>` (TTL = `retryAfterMs`) and notifies superusers (throttled). While the flag is active, `process_incoming_message` short-circuits before bienvenida/IA/avisos to avoid amplifying saturation, and replies once per conversation per window with a soft "estamos saturados" message. The pause is logged as `node_rate_limited` traza.

### REST API Endpoint

`POST /api/enviar-mensaje/` — sends a WhatsApp message. Rate limited to 30 req/min. Requires active session and valid contact. Defined in `seguridad/api_mensajeria.py`.

### AI Agent Configuration

`AgentesIA` (in `crm/models.py`) is the central config for each chatbot:
- `perfil` → links to `PerfilNegocioIA` (business context: products, services, company description)
- `vectorstore_path` → FAISS index on disk built from uploaded training documents
- `contexto_estatico` → raw text injected directly into the LLM prompt (no embedding needed)
- `prompt_template` → Jinja-style template; default Spanish template is in `core/constantes.py:PROMPT_TEMPLATES`
- `apikey` (M2M) → `ApiKeyIA` with `provider` field (`"gemini"` or `"openai"`) and API key

`VectorStoreManager` (`agents_ai/vectorstore_manager.py`) handles building FAISS indexes from PDF, CSV, JSON, or XLSX files. Supported embedding providers: `"gemini"` (default) and `"openai"`.

### Conversation Memory

`agents_ai/memoria_django.py` implements `DjangoChatMessageHistory`, a LangChain-compatible message history backend that persists conversation turns in the database (keyed by `ConversacionWhatsApp` ID). Only the last `_HISTORY_TURNS` (default: 4) turns are passed to the LLM prompt to control token usage.
