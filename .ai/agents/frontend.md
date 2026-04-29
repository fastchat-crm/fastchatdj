# Frontend Agent - UI/UX Development

Guía templates + JavaScript en **fastchatdj** (CRM WhatsApp).

---

## Templates base

```django
{# Autenticado — Bootstrap 4 #}
{% extends 'base.html' %}

{% block head %}{# CSS específico #}{% endblock %}
{% block content %}{# Contenido #}{% endblock %}
{% block jscript %}{# JS específico #}{% endblock %}

{# Público #}
{% extends 'baseweb.html' %}
```

**CSS específico de página:** crear archivo en `static/stylenew/<pagina>.css` y enlazar:
```django
{% block head %}
    <link rel="stylesheet" href="/static/stylenew/plantillas.css">
{% endblock %}
```
Nunca CSS inline en templates.

---

## Listado con DataTable + modal

```django
{# templates/whatsapp/contacto_listado.html #}
{% extends 'base.html' %}
{% block content %}
    <form method="GET">
        <div class="form-row">
            <div class="col-md-6 col-sm-12 offset-md-6">
                <div class="input-group mb-3">
                    <input type="text" class="form-control" placeholder="Buscar"
                           name="criterio" value="{{ criterio }}">
                    <div class="input-group-append">
                        <button class="btn btn-primary" type="submit"><i class="fa fa-search"></i></button>
                        {% if url_vars %}
                            <a title="Ver todo" href="{{ request.path }}" class="btn btn-default">
                                <i class="fas fa-sync-alt"></i>
                            </a>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </form>

    <div class="mb-3">
        <a href="javascript:void(0)" onclick="formModal(0, 'Nuevo Contacto', 'add')"
           class="btn btn-success">
            <i class="fas fa-plus-circle mr-2"></i> Nuevo Contacto
        </a>
    </div>

    <div class="panel panel-default">
        <div class="panel-body">
            <div class="table-responsive">
                <span class="label label-primary">Total: {{ list_count }}</span>
                <table id="tabla" class="table table-bordered table-hover">
                    <thead>
                    <tr>
                        <th class="text-left">Nombre</th>
                        <th class="text-left">Número</th>
                        <th class="text-left">Sesión</th>
                        <th class="text-center">Acción</th>
                    </tr>
                    </thead>
                    <tbody>
                    {% for c in contactos %}
                        <tr>
                            <td class="text-left">{{ c.nombre }}</td>
                            <td class="text-left">{{ c.numero }}</td>
                            <td class="text-left">{{ c.sesion.nombre }}</td>
                            <td class="text-center" nowrap>
                                <div class="btn-group dropleft">
                                    <button type="button" class="btn btn-default btn-sm dropdown-toggle rounded-circle"
                                            data-toggle="dropdown">
                                        <i class="fa fa-ellipsis-v"></i>
                                    </button>
                                    <div class="dropdown-menu dropdown-menu-right">
                                        <a class="dropdown-item"
                                           onclick="formModal({{ c.pk }}, 'Editar {{ c.nombre }}', 'change')"
                                           href="javascript:void(0);">
                                            <i class="fas fa-edit"></i> Editar
                                        </a>
                                        <a class="dropdown-item"
                                           onclick="eliminarajax({{ c.pk }}, '{{ c.nombre }}', 'delete')"
                                           href="javascript:void(0);">
                                            <i class="fas fa-trash"></i> Eliminar
                                        </a>
                                    </div>
                                </div>
                            </td>
                        </tr>
                    {% endfor %}
                    </tbody>
                </table>
                {% include "paginacion.html" %}
            </div>
        </div>
    </div>

    <div class="modal fade" id="modalDetalle">
        <div class="modal-dialog modal-xl">
            <div class="modal-content">
                <form method="post" enctype="multipart/form-data" action="{{ ruta }}"
                      class="form-horizontal form-label-left">
                    {% csrf_token %}
                    <div class="modal-header">
                        <h4 class="modal-title"><b id="modalNombre"></b></h4>
                        <button type="button" class="close" data-dismiss="modal">×</button>
                    </div>
                    <div class="modal-body detalleProd"></div>
                </form>
            </div>
        </div>
    </div>
{% endblock %}

{% block jscript %}
    <script src="/static/js/forms.js?version=14"></script>
    <script>
        function formModal(id, text, action) {
            pantallaespera()
            $.ajax({
                type: "GET",
                url: `{{ request.path }}`,
                data: {'action': action, 'id': id},
                success: function (data) {
                    setTimeout($.unblockUI, 1);
                    if (data.result === true) {
                        $('#modalNombre').html(text);
                        $('.detalleProd').html(data.data);
                        $('#modalDetalle').modal({backdrop: 'static'}).modal('show');
                    } else {
                        mensajeWarning(data.message);
                    }
                },
                error: function () {
                    setTimeout($.unblockUI, 1);
                    mensajeWarning("Error de conexión.");
                },
                dataType: "json"
            });
        }
    </script>
{% endblock %}
```

---

## Form en modal

```django
<div class="row">
    <input type="hidden" value="{{ filtro.id }}" name="pk">
    <input type="hidden" name="action" value="{{ action }}"/>
    {% for field in form %}
        {% if field.is_hidden %}
            {{ field }}
        {% else %}
            <div class="col-lg-{{ field.field.widget.attrs.col }}">
                <div class="form-group">
                    <label class="form-label" for="id_{{ field.name }}">{{ field.label }}:</label><br>
                    {{ field }}
                    <div class="invalid-feedback" id="errorMessage{{ field.name }}"></div>
                </div>
            </div>
        {% endif %}
    {% endfor %}
</div>

<div class="ln_solid"></div>

<div class="form-group">
    <div class="col-lg-12 text-right">
        <a href="javascript:;" class="btn btn-danger" data-dismiss="modal">
            <i class="fa fa-window-close"></i> Cancelar
        </a>
        <button type="submit" class="btn btn-success">
            <i class="fa fa-save"></i> Guardar
        </button>
    </div>
</div>

{{ form.media }}
<script>
    $(function () {
        $.fn.select2.defaults.set('language', 'es');
        $('.jselect2').select2({dropdownParent: $('#modalDetalle')});
    })
</script>
```

---

## Funciones JS globales (en `base.html`)

**SweetAlert2 LEGACY** — usar `type:` (no `icon:`) y `result.value` (no `isConfirmed`). Ver `skills/sweetalert-legacy.md`.

### Toasts (esquina superior derecha)

```javascript
alertaSuccess("Plantilla guardada");
alertaInfo("Procesando webhook");
alertaWarning("Sesión saturada");
alertaDanger("Error envío Meta");
```

### Modales

```javascript
mensajeSuccess("Conversación archivada");
mensajeWarning("Faltan datos");
mensajeDanger("No se pudo enviar");
mensajeSuccessConfirm("Listo", "/whatsapp/conversaciones/");
```

### Confirmación

```javascript
Swal.fire({
    title: "¿Eliminar contacto?",
    text: "Esta acción no se puede deshacer",
    type: "warning",
    showCancelButton: true,
    confirmButtonText: "Sí, eliminar",
    cancelButtonText: "Cancelar"
}).then((result) => {
    if (result.value) {
        $.post('/whatsapp/contacto/eliminar/', {id: 123}, function(resp) {
            if (resp.resp) alertaSuccess(resp.mensaje);
        });
    }
});
```

### Loading overlay

```javascript
pantallaespera();   // mostrar
$.unblockUI();      // ocultar
```

---

## AJAX submit auto (`forms.js`)

`static/js/forms.js` se incluye globalmente en `base.html` y captura todos los POST excepto `#frmEliminar`, `#excluirFormAjax`, `[method=GET]`. Backend devuelve formato esperado:

```python
return JsonResponse([{
    'error': False,
    'msg_reload': True,
    'msg_title': 'Guardado',
    'msg_body': 'Contacto registrado'
}])
```

Ver `skills/forms-ajax.md` para el contrato completo.

---

## Select2

Auto-aplicado por `ModelFormBase` a `ChoiceField` (clase `.jselect2`).

**Dentro de modal:** debe pasar `dropdownParent` para evitar que el dropdown quede oculto.

```javascript
$('.jselect2').select2({
    dropdownParent: $('#modalDetalle'),
    placeholder: 'Seleccione',
    allowClear: true
});
```

**AJAX (búsqueda remota):**

```javascript
$('#sesion').select2({
    ajax: {
        url: '/ajaxrequest/buscar_sesiones/',
        dataType: 'json',
        processResults: function(data) {
            return {results: data.map(s => ({id: s.id, text: s.nombre}))};
        }
    }
});
```

---

## DataTables

```javascript
$('#tabla').DataTable({
    pageLength: 30,
    responsive: true,
    searching: false,
    paging: false,
    bInfo: false,
    ordering: false,
    dom: 'Bfrtip',
    order: [[0, "desc"]],
    language: {url: '/static/js/i18n/Spanish.json'},
    buttons: [{extend: 'colvis', text: '<i class="fa fa-eye"></i> VER COLUMNAS'}]
});
```

---

## WebSockets — chat tiempo real

`whatsapp/consumers.py` define:
- `ChatConsumer` — chat por conversación. Broadcast HTML renderizado al recibir mensaje
- `SessionConsumer` / `SessionRoomConsumer` — estado sesión (QR, conexión)

Cliente JS conecta a `ws://<host>/ws/chat/<conversacion_id>/`. Escucha `event` y reemplaza/append HTML al DOM.

---

## Template tags

```django
{% load templatefunctions %}

{# Boolean iconos via NormalModel #}
{{ contacto.status_boolhtml }}    {# fa-check / fa-times #}
{{ contacto.status_yesorno }}     {# Sí / No #}

{# Money via NormalModel #}
{{ producto.precio_money }}

{# Fechas #}
{{ mensaje.fecha_registro|date:"d/m/Y H:i" }}
```

---

## Errores Bootstrap 4

```html
<div class="form-group">
    <label for="id_numero">Número *</label>
    <input type="text" id="id_numero" name="numero" class="form-control">
    <div id="errorMessagenumero" class="invalid-feedback" style="display:none;"></div>
</div>
```

`forms.js` automaticamente:
1. Añade `is-invalid` al campo
2. Renderiza msg en `#errorMessage<campo>`
3. Scroll al primer error

---

## Pitfalls

❌ NO:
- SweetAlert2 sintaxis nueva (`icon`, `isConfirmed`)
- CSS inline en templates → usar `static/stylenew/<pagina>.css`
- Olvidar `{% csrf_token %}`
- Mezclar Bootstrap 5 (proyecto = Bootstrap 4)
- Usar `dropdownParent` de Select2 fuera de modales sin necesidad

✅ SÍ:
- SweetAlert2 legacy: `type:`, `result.value`
- `{{ form.media }}` después de forms con Select2
- `pantallaespera()` antes de AJAX largos
- Mobile-first (responsive)

---

**Ver también:**
- `skills/sweetalert-legacy.md` — sintaxis legacy completa
- `skills/forms-ajax.md` — contrato AJAX detallado
