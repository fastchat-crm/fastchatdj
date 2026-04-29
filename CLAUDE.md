# CLAUDE.md — fastchat

## Project Overview

**fastchat** is a Django 4.0 monolithic web application. It uses PostgreSQL 15 as its database.

## Tech Stack

- **Backend:** Python 3.9, Django 4.0, PostgreSQL 15
- **Frontend:** Bootstrap 4, jQuery, DataTables, SweetAlert2 (legacy syntax)
- **Auth:** Django session-based authentication
- **Environment:** virtualenv (activated via PyCharm), development server via PyCharm debug runner

## How to Verify Your Changes

1. Run `pycheck` for indentation and syntax validation
2. The developer runs the server manually via PyCharm and reviews results
3. If corrections are needed, the developer will communicate them explicitly

**Do not run the server or any Django management commands yourself.**

## Template Conventions

Templates follow a strict inheritance and naming structure:

```
templates/
├── base.html        # Authenticated layout (Bootstrap 4) — use for internal views
├── baseweb.html     # Public portal layout — use for public-facing views
└── <app>/
    ├── *_listado.html   # DataTables listing views
    ├── *_form.html      # Create/edit forms (modal or full-page)
    └── *_detalle.html   # Read-only detail views
```

**Static files:** Always use absolute paths — never `{% load static %}` or `{% static '...' %}`.

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
```

## Language & Copy

All visible text in views and templates must be in **English**: `titulo`, alert messages, button labels, column headers, log messages, `messages.success/error`, and exception strings. Backend variable names may remain in Spanish (`criterio`, `filtro`, `listado`) for consistency with the existing codebase.

## Soft Delete

Models inherit from `ModeloBase` and use a `status` BooleanField for soft-delete. Deletions always set `filtro.status = False; filtro.save(request)` — never `.delete()`. List queries always filter by `Q(status=True)`. Never render `status` as a column, helper, or form field.

## File Uploads

Every `FileField`/`ImageField` uploaded via a form must be validated in the backend using `validar_archivo` from `core.funciones` (returns `(ok, archivo_or_msg)`). Apply in both `add` and `change` actions. Infer allowed extensions from the model's `FileExtensionValidator`.

## Hard Rules

These apply to every task, no exceptions:

- **Never modify existing migrations** — create new ones only if explicitly instructed
- **Never run** `makemigrations`, `migrate`, `runserver`, or any management command
- **Never execute** `git commit`, `git push`, or any destructive git operation
- **Never read or modify** `credentials.json` or any secrets/credentials file
- **Never auto-format or lint** — the developer handles code style verification
- **Run** `git add <file>` immediately after creating a new `.html`, `.css`, or `.py` file — never for existing or modified files
- **Grid** Always use Bootstrap 4 grid system (`row` + `col-*` classes) for any multi-column layout — never use CSS Grid or custom Flexbox for structural grids, unless otherwise specified.