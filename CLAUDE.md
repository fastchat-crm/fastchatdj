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
- `ChatConsumer` — real-time chat per conversation
- `SessionConsumer` / `SessionRoomConsumer` — WhatsApp session status

**AI Pipeline:** `agents_ai` uses LangChain with Google Generative AI embeddings stored in FAISS vector stores. `AgentesIA` records in `crm` configure which agent handles each WhatsApp session. Training documents uploaded via `EntrenamientosIA` are embedded and stored per agent.

**Base Models:** `core.ModeloBase` and `core.NormalModel` are the base classes for most models (providing `created_at`, `updated_at`, soft delete, etc.).

### WhatsApp Integration Flow

```
External WhatsApp API (Node.js service)
    ↓ webhook POST
whatsapp/webhook_handler/
    ↓
MensajeWhatsApp created → ConversacionWhatsApp updated
    ↓
ChatConsumer broadcasts via WebSocket to frontend
    ↓ (if AI enabled on session)
agents_ai.AgenteConsultor → LangChain → Google Generative AI → reply sent via WHATSAPP_API_URL
```

### REST API Endpoint

`POST /api/enviar-mensaje/` — sends a WhatsApp message. Rate limited to 30 req/min. Requires active session and valid contact. Defined in `seguridad/api_mensajeria.py`.
