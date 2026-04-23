# Contrato AJAX Forms — fastchatdj

Sistema automático de submisión AJAX vía `static/js/forms.js`.

---

## Resumen

`static/js/forms.js` (incluido globalmente en `base.html`) captura todo POST automáticamente. **No hace falta JS por form.**

**Features:**
- FormData (soporta files)
- Encriptación RSA para campos sensibles
- Validación Bootstrap 4 (clase `is-invalid` + div `#errorMessage<campo>`)
- SweetAlert2 legacy
- BlockUI (`pantallaespera()`)
- Hooks: `funcionAntesDeGuardar()`, `funcionDespuesDeGuardar()`, `funcionSiFallaElPost()`
- Auto-scroll al primer error

---

## Captura automática

Se engancha a todo `form` POST excepto:
- `#frmEliminar` (formularios delete)
- `#excluirFormAjax`
- `[method=GET]` (búsquedas/filtros)

```html
<form method="post" action="{% url 'guardar_plantilla' %}">
    {% csrf_token %}
    {{ form.as_p }}
    <button type="submit" id="submit">Guardar</button>
</form>
```

No se necesita más JS. `forms.js` lo maneja.

---

## Request

Construcción:

```javascript
$('form:not(#frmEliminar, #excluirFormAjax, [method=GET])').submit(function(e) {
    e.preventDefault();
    if (typeof funcionAntesDeGuardar === 'function') funcionAntesDeGuardar();

    $('input, textarea, select').removeClass('is-invalid');
    $('.invalidFeedback').html('');

    var _form = new FormData($(this)[0]);

    // RSA para campos data-datoseguro="true"
    for (var f of inputsEncrypted.split('|')) {
        if (_form.has(f)) _form.set(f, doRSA(_form.get(f)));
    }

    // Arrays JS como JSON
    try { _form.append('lista_items1', JSON.stringify(lista_items1)); } catch (e) {}

    $.ajax({
        type: 'POST',
        url: $(this).attr('action') || window.location,
        data: _form,
        dataType: 'json',
        enctype: $(this).attr('enctype'),
        cache: false,
        contentType: false,
        processData: false,
        beforeSend: function() {
            btnSubmit.html(cargando);
            btnSubmit.attr('disabled', true);
            pantallaespera();
        }
    });
});
```

---

## Contrato Response

**Backend siempre devuelve LISTA** — `forms.js` itera.

### Éxito

```python
{
    'error': False,
    'msg_reload': bool,    # muestra msg y reload
    'msg_to': bool,        # muestra msg y redirect
    'reload': bool,        # reload silencioso
    'to': str,             # redirect silencioso
    'function_js': str,    # eval() en el cliente
    'msg_title': str,
    'msg_body': str
}
```

#### Guardar + reload

```python
return JsonResponse([{
    'error': False,
    'msg_reload': True,
    'msg_title': 'Guardado',
    'msg_body': 'Plantilla registrada'
}])
```

#### Guardar + redirect

```python
return JsonResponse([{
    'error': False,
    'msg_to': True,
    'to': '/whatsapp/plantillas/',
    'msg_title': 'Listo',
    'msg_body': 'Plantilla creada'
}])
```

#### Ejecutar JS cliente

```python
return JsonResponse([{
    'error': False,
    'function_js': 'cargarTabla(); cerrarModal();'
}])
```

### Error

```python
{
    'error': True,
    'input_id': str,      # id del input inválido (un solo campo)
    'div_id': str,        # id del div error
    'message': str,       # mensaje general
    'form': [             # errores por campo
        {'campo1': 'mensaje'},
        {'campo2': 'mensaje'}
    ]
}
```

#### Error campo único

```python
return JsonResponse([{
    'error': True,
    'input_id': 'id_numero',
    'div_id': 'errorMessagenumero',
    'message': 'Número inválido'
}])
```

#### Errores de form

```python
errores = [{f: errs[0]} for f, errs in form.errors.items()]
return JsonResponse([{
    'error': True,
    'message': 'Corrija los errores',
    'form': errores
}])
```

---

## Manejo cliente

### Éxito

```javascript
data.forEach(function(value) {
    if (!value.error) {
        if (value.msg_reload) {
            Swal.fire({
                title: value.msg_title,
                text: value.msg_body,
                type: 'success',               // LEGACY, NO 'icon'
                confirmButtonText: 'OK',
                allowOutsideClick: false
            }).then((r) => { if (r.value) location.reload(); });  // LEGACY, NO 'isConfirmed'
        }
        if (value.msg_to) {
            Swal.fire({...}).then((r) => { if (r.value) location.href = value.to; });
        }
        if (value.reload) location.reload();
        if (value.to) location = value.to;
        if (value.function_js) eval(value.function_js);

        if (typeof funcionDespuesDeGuardarValores === 'function') funcionDespuesDeGuardarValores(value);
        if (typeof funcionDespuesDeGuardar === 'function') funcionDespuesDeGuardar();
    }
});
```

### Error

```javascript
if (value.error) {
    // Un campo
    if (value.input_id) {
        $('#' + value.input_id).addClass('is-invalid');
        $('#' + value.div_id).html(value.message);
    }
    // Form completo
    else if (value.form) {
        Swal.fire({
            toast: true, position: 'top-end',
            type: 'error',                    // LEGACY
            title: 'Complete los datos requeridos',
            showConfirmButton: false, timer: 1000
        });
        value.form.forEach(function(val) {
            Object.keys(val).forEach(function(k) {
                $('#id_' + k).addClass('is-invalid');
                $('#errorMessage' + k).html(val[k]).show();
            });
        });
        if (value.message) Swal.fire(value.message, '', 'error');
    }
    else {
        Swal.fire(value.message, '', 'error');
    }
}
```

### Error de red

```javascript
.fail(function(jqXHR, textStatus, errorThrown) {
    btnSubmit.html(error_btn);
    btnSubmit.attr('disabled', false);
    $.unblockUI();

    if (typeof funcionSiFallaElPost === 'function') {
        funcionSiFallaElPost(jqXHR, textStatus, errorThrown, _form, window.location.toString());
    } else {
        Swal.fire('Error de conexión', '', 'error');
    }
});
```

---

## SweetAlert2 LEGACY

**CRÍTICO:** `type:` (no `icon:`), `result.value` (no `isConfirmed`). Ver `skills/sweetalert-legacy.md`.

---

## Encriptación RSA (campos sensibles)

```html
<input type="password" name="password" data-datoseguro="true" class="form-control">
```

`forms.js` recolecta los nombres de campos marcados y cifra con `doRSA()` antes del submit. Backend descifra con clave privada (`private_key_enc.pem`).

---

## Hooks

### Antes del submit

```javascript
function funcionAntesDeGuardar() {
    // Validación custom, ajustes
    $('#campo_oculto').val(calcularValor());
}
```

### Después éxito (sin params)

```javascript
function funcionDespuesDeGuardar() {
    $('#modalDetalle').modal('hide');
}
```

### Después éxito (con data)

```javascript
function funcionDespuesDeGuardarValores(value) {
    console.log('Guardado:', value);
}
```

### Falla de red

```javascript
function funcionSiFallaElPost(jqXHR, textStatus, errorThrown, formData, url) {
    console.error('POST fail:', textStatus);
}
```

---

## File upload

```html
<form method="post" enctype="multipart/form-data" action="{% url 'upload_plantilla_media' %}">
    {% csrf_token %}
    <input type="file" name="header_archivo" class="form-control" required>
    <button type="submit" id="submit">Subir</button>
</form>
```

Backend:

```python
@require_http_methods(['POST'])
def upload_plantilla_media(request):
    if 'header_archivo' in request.FILES:
        f = request.FILES['header_archivo']
        # procesar
        return JsonResponse([{
            'error': False,
            'msg_reload': True,
            'msg_title': 'Subido',
            'msg_body': f'Archivo {f.name} cargado'
        }])
```

---

## Bootstrap 4 validation display

```html
<div class="form-group">
    <label for="id_numero">Número *</label>
    <input type="text" id="id_numero" name="numero" class="form-control">
    <div id="errorMessagenumero" class="invalid-feedback" style="display:none;"></div>
</div>
```

Convención estricta:
- Field ID = `id_<nombre>`
- Error div = `#errorMessage<nombre>`

`forms.js`:
1. Añade `is-invalid` al input
2. Inyecta `html` al div
3. Scroll al primer inválido

---

## Arrays JS → backend

Definir en la página:

```javascript
var lista_items1 = [
    {id: 1, nombre: 'Item A'},
    {id: 2, nombre: 'Item B'}
];
```

`forms.js` lo agrega automáticamente como JSON al FormData. Backend:

```python
import json
def vista(request):
    items = json.loads(request.POST.get('lista_items1', '[]'))
```

---

## Ejemplo completo

### Vista

```python
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from whatsapp.forms import PlantillaWhatsAppForm

@login_required
@require_http_methods(['POST'])
def guardar_plantilla(request):
    try:
        form = PlantillaWhatsAppForm(request.POST, request.FILES)
        if form.is_valid():
            p = form.save()
            return JsonResponse([{
                'error': False,
                'msg_reload': True,
                'msg_title': 'Guardado',
                'msg_body': f'Plantilla {p.nombre} creada'
            }])
        errores = [{f: errs[0]} for f, errs in form.errors.items()]
        return JsonResponse([{
            'error': True,
            'message': 'Corrija los errores',
            'form': errores
        }])
    except Exception as e:
        return JsonResponse([{'error': True, 'message': str(e)}])
```

### Template

```django
<form method="post" enctype="multipart/form-data" action="{% url 'guardar_plantilla' %}">
    {% csrf_token %}

    <div class="form-group">
        <label for="id_nombre">Nombre *</label>
        <input type="text" id="id_nombre" name="nombre" class="form-control" required>
        <div id="errorMessagenombre" class="invalid-feedback"></div>
    </div>

    <div class="form-group">
        <label for="id_categoria">Categoría *</label>
        <select id="id_categoria" name="categoria" class="form-control jselect2">
            <option value="UTILITY">Utilidad</option>
            <option value="MARKETING">Marketing</option>
            <option value="AUTHENTICATION">Autenticación</option>
        </select>
        <div id="errorMessagecategoria" class="invalid-feedback"></div>
    </div>

    <div class="form-group">
        <label for="id_cuerpo">Cuerpo *</label>
        <textarea id="id_cuerpo" name="cuerpo" class="form-control" rows="4" required></textarea>
        <div id="errorMessagecuerpo" class="invalid-feedback"></div>
    </div>

    <button type="submit" id="submit" class="btn btn-success">
        <i class="fa fa-save"></i> Guardar
    </button>
</form>

<script>
    function funcionDespuesDeGuardar() {
        $('#modalPlantilla').modal('hide');
    }
</script>
```

---

## Patrones comunes

```python
# Guardar + reload
JsonResponse([{'error': False, 'msg_reload': True, 'msg_title': 'Guardado', 'msg_body': 'Registro actualizado'}])

# Guardar + redirect
JsonResponse([{'error': False, 'msg_to': True, 'to': '/lista/', 'msg_title': 'Listo', 'msg_body': 'OK'}])

# JS cliente
JsonResponse([{'error': False, 'function_js': 'recargarTabla(); cerrarModal();'}])

# Errores validación
JsonResponse([{'error': True, 'form': [{'numero': 'Inválido'}, {'nombre': 'Requerido'}]}])
```

---

## Troubleshooting

**No submitea via AJAX:**
- ¿Está excluido? (revisa línea ~29 de `forms.js`)
- `method="post"` (minúsculas)
- Botón con `id="submit"`

**Errores no se muestran:**
- Div debe ser `#errorMessage<campo>`
- Input debe ser `id_<campo>`
- Response incluye clave `form`

**File no se sube:**
- `enctype="multipart/form-data"` en el form
- `request.FILES` en backend

**RSA no cifra:**
- Input con `data-datoseguro="true"`
- Función `doRSA()` definida globalmente

---

**Ver también:**
- `skills/sweetalert-legacy.md`
- `agents/frontend.md`
- `agents/backend.md`
