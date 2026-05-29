# CLAUDE.md — fastchat

## Project Overview

**fastchat** is a Django 4.2 monolithic SaaS for WhatsApp messaging. PostgreSQL 15 + Redis. Realtime chat runs over Django Channels (ASGI/Daphne); WhatsApp connectivity is dual-provider — a Node.js Baileys service for unofficial sessions, and Meta Cloud API for official ones.

## Tech Stack

- **Backend:** Python 3.9, Django 4.2.15, PostgreSQL 15, Redis (channel layer + cache), Daphne ASGI, Channels 4
- **Frontend:** Bootstrap 5 (`data-bs-*` API), jQuery, DataTables, SweetAlert2 (legacy syntax)
- **Auth:** Django session-based authentication; custom `AUTH_USER_MODEL = "autenticacion.Usuario"`
- **Environment:** virtualenv (activated via PyCharm), development server via PyCharm debug runner

## Apps

- `core/` — shared utilities: `ModeloBase` (soft-delete + auditing in `core/custom_models.py`), `ConsultasAjax` dispatcher (`core/ajax.py`), current-request middleware, validators (`core/validadores.py`)
- `autenticacion/` — `Usuario` (custom `AUTH_USER_MODEL`), login, profile, password recovery
- `seguridad/` — modules, groups, permissions, configuration, database backups, notifications
- `whatsapp/` — sessions, contacts, conversations, messages, campaigns, templates, tariffs, pipelines, analytics, traces; webhooks for Baileys + Meta; WebSocket consumers
- `crm/` — chatbot flow engine, AI endpoints, agent wizard, departments, training
- `agents_ai/` — AI agents (consultor/resumidor/auditor), tool builder, vector store, providers
- `voz/` — voice AI (Piper TTS demo lives in `scripts/`)
- `meta/` — Meta-specific integration helpers
- `public/` — public-facing portal pages (uses `baseweb.html`)
- `area_geografica/` — country / state / city catalog

## Module Documentation

Deep-dive technical references for specific modules live under `.ai/docs/`. **Always read the relevant doc before touching the corresponding module** — they capture views, templates, JS, WebSocket flows, and business rules that aren't obvious from the code alone.

- `.ai/docs/conversaciones.md` — `whatsapp/conversaciones/` and `whatsapp/conversaciones-finalizadas/`: views, helpers, GET/POST actions, listing filters, partials, JS patterns, WebSocket consumers (`ChatConsumer`, `SessionRoomConsumer`), webhook → broadcast flow, 6h reactivation window, Meta template flow, and rules for adding actions/filters/panels/message types.

## Server & Background Jobs

- **Do not run the server yourself.** The developer uses PyCharm, or `restart_daphne.bat <port>` (Windows) / `restart_daphne.sh <port>` (Bash). Default port 8000.
- WebSocket routing lives in each app's `routing.py` (e.g. `whatsapp/routing.py`, `voz/routing.py`); ASGI entry is `fastchatdj/asgi.py`.
- Background scripts live in `cron_jobs/` (campaigns, scheduled messages, reconnect sessions, etc.) and one-off seeders / demos in `scripts/`. Treat them as cron-driven; do not invoke them.

## Ajax Dispatch Convention

Most list/CRUD actions go through `core.ajax.ConsultasAjax` at `/ajaxrequest/<accion>` or `/ajaxrequest/<accion>/<pk>`. New CRUD logic should follow this pattern (an `accion` branch in the relevant view or in `ConsultasAjax`) rather than introducing one-off endpoints.

## How to Verify Your Changes

1. Run `pycheck` for indentation and syntax validation
2. The developer runs the server manually via PyCharm and reviews results
3. If corrections are needed, the developer will communicate them explicitly

**Do not run the server or any Django management commands yourself.**

## Template Conventions

Templates follow a strict inheritance and naming structure:

```
templates/
├── base.html        # Authenticated layout (Bootstrap 5) — use for internal views
├── base_chat.html   # Chat workspace layout (DM Sans, shadcn-inspired CSS vars)
├── baseweb.html     # Public portal layout — use for public-facing views
└── <app>/
    ├── *_listado.html   # DataTables listing views
    ├── *_form.html      # Create/edit forms (modal or full-page)
    └── *_detalle.html   # Read-only detail views
```

**Static files:** Always reference assets with absolute paths (`/static/...`, `/media/...`). Never use the `{% static '...' %}` URL helper. Templates may still `{% load %}` other tag libraries (e.g. `templatefunctions`) — that's not the same thing.

```html
<!-- Correct -->
<link rel="stylesheet" href="/static/css/file.css">

<!-- Never do this -->
{% load static %}
<link rel="stylesheet" href="{% static 'css/file.css' %}">
```

**CSS — no inline styles in templates:** Never use `<style>` blocks inside templates. Instead, create a dedicated `.css` file under `static/css/<django-app>/` (where `<django-app>` is the Django app name the template belongs to, e.g. `regulated`, `seguridad`, `sitio`) and link it with an absolute path.

```html
<!-- Correct — template in the "estudiante" app -->
<link rel="stylesheet" href="/static/css/estudiante/mi_vista.css">

<!-- Never do this -->
<style>
    .mi-clase { ... }
</style>
```

Name the file after the template or feature it belongs to (e.g. `navbar.css`, `listado_servicio.css`). Run `git add static/css/<django-app>/<file>.css` immediately after creating it.

**CSS cache busting:** Every time you modify an existing `.css` file, increment the `?v` query string on its `<link>` tag in the template. Use a simple incremental version (`?v1.1`, `?v1.2`, `?v1.3`, …). If no version exists yet, add `?v1.0`.

```html
<link rel="stylesheet" href="/static/css/regulated/listado_servicio.css?v1.2">
```

Always check the current version in the template before incrementing.

**No comments in templates, CSS, or JS:** Never write comments in any file you create or modify. This applies to all comment syntaxes:

- HTML: `<!-- comment -->`
- Django templates: `{# comment #}`
- CSS: `/* comment */`
- JS: `// comment` and `/* comment */`

## Language & Copy

Todo texto visible para el usuario en views y templates debe estar en **español**: `titulo`, mensajes de alertas y SweetAlert, labels de botones, encabezados de columnas, mensajes de log, `messages.success/error`, strings de excepciones, copys de ayuda, badges, tooltips y `JsonResponse({'message': ...})`. Los nombres de variables backend se mantienen en español (`criterio`, `filtro`, `listado`, `usuarios`) — siempre fue la convención. Términos técnicos universales (push, URL, endpoint, service worker, API, Meta, WhatsApp) no se traducen.

Detalles y ejemplos en `.ai/docs/lenguaje.md`.

## Soft Delete

Models inherit from `ModeloBase` and use a `status` BooleanField for soft-delete. Deletions always set `filtro.status = False; filtro.save(request)` — never `.delete()`. List queries always filter by `Q(status=True)`. Never render `status` as a column, helper, or form field.

## File Uploads

Every `FileField`/`ImageField` must declare allowed extensions on the model via `FileExtensionValidator` and a size validator from `core/validadores.py` (`validate_file_size_2mb`, `validate_file_size_3mb`, `validate_file_size_20mb`, …). Validate on both `add` and `change` actions; infer allowed extensions from the model's `FileExtensionValidator`.

## Hard Rules

These apply to every task, no exceptions:

- **Never modify existing migrations** — create new ones only if explicitly instructed
- **Never run** `makemigrations`, `migrate`, `runserver`, or any management command
- **Never execute** `git commit`, `git push`, or any destructive git operation
- **Never read or modify** `credenciales.json` (the real credentials file at the repo root) or any other secrets file. `credenciales_template.json` shows the required keys.
- **Never auto-format or lint** — the developer handles code style verification
- **Run** `git add <file>` immediately after creating a new `.html`, `.css`, or `.py` file — never for existing or modified files
- **Grid** Always use the Bootstrap 5 grid system (`row` + `col-*` classes) for any multi-column layout — never use CSS Grid or custom Flexbox for structural grids, unless otherwise specified.