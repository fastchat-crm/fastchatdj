# Code Conventions — fastchatdj

## Idioma

Todo el código en **español**: modelos, campos, funciones, variables, comentarios.
**Excepciones:** built-ins Django, APIs de terceros, archivos de configuración.

---

## Naming

| Elemento | Convención | Ejemplo |
|----------|-----------|---------|
| Modelos | PascalCase, singular | `MensajeWhatsApp`, `ConfigMeta` |
| Campos | snake_case descriptivo | `fecha_registro`, `numero_externo` |
| Foreign keys | sustantivo singular | `sesion`, `contacto` |
| ManyToMany | sustantivo plural | `etiquetas`, `agentes_ia` |
| Booleanos | prefijo `es_` / `tiene_` | `es_activo`, `tiene_ia` |
| Funciones/métodos | snake_case verbo-primero | `enviar_mensaje`, `procesar_webhook` |
| Vistas | `accion_sustantivo` | `listado_contactos`, `guardar_plantilla` |
| Variables | snake_case sin abrev | `lista_mensajes` no `m` |
| Constantes | UPPER_SNAKE_CASE | `ESTADOS_PLANTILLA`, `NODE_SECRET_KEY` |
| URLs | minúsculas-con-guiones | `whatsapp/enviar-mensaje/` |
| Templates | snake_case + sufijo | `contacto_listado.html` |

---

## Sufijos templates

| Sufijo | Propósito |
|--------|-----------|
| `*_listado.html` | Listado DataTables |
| `*_form.html` | Crear/editar (modal o página) |
| `*_detalle.html` | Vista solo lectura |

---

## Estructura de vista

Orden por convención:

1. Decoradores: `@login_required`, `@secure_module`
2. Inicializar `data = {'titulo':..., 'modulo':..., 'ruta': request.path}`
3. `addData(request, data)`
4. Branches por `request.method`
5. Queries con `select_related` / `prefetch_related`
6. `data['x'] = ...; return render(...)`

> Ver ejemplos reales en `whatsapp/view_*.py`, `seguridad/view_*.py`.

---

## Estructura modelo

Orden:

1. Choices (constantes a nivel módulo o atributo de clase)
2. Campos simples
3. Relaciones (FK, M2M)
4. `class Meta` con `verbose_name`, `ordering`
5. `__str__`
6. Métodos custom
7. `@property`

**Heredar siempre `ModeloBase`** y filtrar `status=True` en queries.

---

## Estructura form

Forms heredan de `ModelFormBase` (`core/custom_forms.py`).
Orden: `Meta` → `__init__` override → `clean_<field>` → `clean()`.

---

## Orden imports

1. Standard library
2. Django
3. Terceros (DRF, channels, langchain, etc.)
4. Apps locales (`core.*`, otras apps)
5. Imports relativos (`.models`, `.forms`)

---

## Estructura archivos por app

```
app_name/
├── models.py              # único si < 200 líneas
├── models/                # split por dominio si > 200
├── view_<feature>.py      # un archivo por dominio funcional
├── public_<feature>.py    # vistas públicas (sin login)
├── forms.py
├── urls.py                # lista de dicts (registrada en fastchatdj/urls.py)
├── consumers.py           # WebSocket (Channels) si aplica
├── services.py            # integraciones externas (WhatsApp, Meta, etc.)
└── utils.py
```

---

## Comentarios

- **Docstrings** en funciones no triviales: 1 línea + Args/Returns si complejo
- **Inline** explica *por qué*, nunca *qué*
- No `print()` en código commit (usar `logger`)

---

## Errores

`try/except` con tipos específicos primero, `Exception` como fallback genérico.
Logging con `logger = logging.getLogger(__name__)`.

---

## CSS

CSS específico de página → archivo en `static/stylenew/<pagina>.css`.
**Nunca** CSS inline en templates ni `<style>` en `block head`.

---

## JavaScript

- Funciones de negocio en español: `guardarPlantilla()`, `enviarMensaje()`
- Helpers genéricos jQuery/DataTables pueden usar inglés: `initDataTable()`
- Variables en español; no nombres de una letra fuera de loops
- SweetAlert2: sintaxis **legacy** (ver `skills/sweetalert-legacy.md`)

---

## Configuración

Secretos en `credenciales.json` (gitignored). Nunca hardcodear ni commitear.
Lectura en `fastchatdj/settings.py`.
