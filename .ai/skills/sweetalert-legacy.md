# SweetAlert2 Legacy Syntax

**CRITICAL:** fastchatdj uses an OLD version of SweetAlert2 with different syntax than current documentation

---

## Key Differences from Modern Syntax

| Feature                | Old Syntax (fastchatdj) | Modern Syntax (docs) |
|------------------------|-----------------------|----------------------|
| Alert icon             | `type: 'success'`     | `icon: 'success'`    |
| Confirmation result    | `result.value`        | `result.isConfirmed` |
| Toast notification     | `type: 'error'`       | `icon: 'error'`      |

---

## Toast Notifications (Position: top-end)

### Success Toast
```javascript
Swal.fire({
    toast: true,
    position: "top-end",
    type: "success",  // ✅ CORRECT - NOT 'icon'
    title: "Operación exitosa",
    showConfirmButton: false,
    timer: 3500
});
```

### Error Toast
```javascript
Swal.fire({
    toast: true,
    position: "top-end",
    type: "error",  // ✅ CORRECT
    title: "Error al procesar",
    showConfirmButton: false,
    timer: 3500
});
```

### Warning Toast
```javascript
Swal.fire({
    toast: true,
    position: "top-end",
    type: "warning",  // ✅ CORRECT
    title: "Advertencia",
    showConfirmButton: false,
    timer: 3500
});
```

### Info Toast
```javascript
Swal.fire({
    toast: true,
    position: "top-end",
    type: "info",  // ✅ CORRECT
    title: "Información",
    showConfirmButton: false,
    timer: 3500
});
```

---

## Modal Alerts (Center Screen)

### Simple Success
```javascript
Swal.fire("", "Registro guardado correctamente", "success");
// Equivalent to:
Swal.fire({
    title: "",
    text: "Registro guardado correctamente",
    type: "success"  // ✅ NOT 'icon'
});
```

### Warning with Title
```javascript
Swal.fire({
    title: "Atención",
    text: "Verifique los datos ingresados",
    type: "warning"  // ✅ CORRECT
});
```

### Error with Title
```javascript
Swal.fire({
    title: "Error",
    text: "No se pudo completar la operación",
    type: "error"  // ✅ CORRECT
});
```

---

## Confirmation Dialogs

### Standard Confirmation
```javascript
Swal.fire({
    title: "¿Está seguro?",
    text: "Esta acción no se puede deshacer",
    type: "warning",  // ✅ CORRECT
    showCancelButton: true,
    confirmButtonColor: "#3085d6",
    cancelButtonColor: "#d33",
    confirmButtonText: "Sí, eliminar",
    cancelButtonText: "Cancelar"
}).then((result) => {
    if (result.value) {  // ✅ CORRECT - NOT 'isConfirmed'
        // User clicked confirm
        console.log("Confirmed");
    }
});
```

### Confirmation with Callback
```javascript
Swal.fire({
    title: "¿Continuar?",
    text: "Se procesará el registro",
    type: "question",  // ✅ CORRECT
    showCancelButton: true,
    confirmButtonText: "Continuar",
    cancelButtonText: "Cancelar"
}).then((result) => {
    if (result.value) {  // ✅ NOT 'isConfirmed'
        // Execute action
        $.post('/url/', data, function(resp) {
            if (resp.resp) {
                Swal.fire("", resp.mensaje, "success");
            }
        });
    }
});
```

---

## Success with Redirect

### After Confirmation
```javascript
Swal.fire({
    text: "Estudiante registrado correctamente",
    title: "",
    type: "success",  // ✅ CORRECT
    allowOutsideClick: false
}).then((result) => {
    if (result.value) {  // ✅ CORRECT
        location.reload();  // Or redirect
    }
});
```

### With URL Parameter
```javascript
function mensajeSuccessConfirm(mensaje, url = null) {
    Swal.fire({
        text: mensaje,
        title: "",
        type: "success",  // ✅ CORRECT
        allowOutsideClick: false
    }).then((result) => {
        if (result.value) {  // ✅ CORRECT
            if (url) {
                window.open(url, "_blank");
            } else {
                location.reload();
            }
        }
    });
}
```

---

## Input Dialogs

### Text Input
```javascript
Swal.fire({
    title: "Ingrese el motivo",
    input: "text",
    inputPlaceholder: "Escriba aquí...",
    showCancelButton: true,
    confirmButtonText: "Aceptar",
    cancelButtonText: "Cancelar"
}).then((result) => {
    if (result.value) {  // ✅ CORRECT - value contains input text
        console.log("Input:", result.value);
    }
});
```

### Select Dropdown
```javascript
Swal.fire({
    title: "Seleccione una opción",
    input: "select",
    inputOptions: {
        'opcion1': 'Opción 1',
        'opcion2': 'Opción 2',
        'opcion3': 'Opción 3'
    },
    inputPlaceholder: "Seleccione",
    showCancelButton: true
}).then((result) => {
    if (result.value) {  // ✅ Selected value
        console.log("Selected:", result.value);
    }
});
```

---

## Available Alert Types

| Type        | Usage                          |
|-------------|--------------------------------|
| `success`   | Successful operations          |
| `error`     | Errors and failures            |
| `warning`   | Warnings and confirmations     |
| `info`      | Informational messages         |
| `question`  | Questions and prompts          |

---

## Global Helper Functions (in base.html)

**These are available project-wide:**

```javascript
// Toast alerts
alertaSuccess(mensaje);
alertaInfo(mensaje);
alertaWarning(mensaje);
alertaDanger(mensaje);

// Modal alerts
mensajeSuccess(mensaje);
mensajeWarning(mensaje);
mensajeDanger(mensaje);
mensajeSuccessConfirm(mensaje, url);
```

**Usage:**
```javascript
// Simple toast
alertaSuccess("Registro guardado");

// Modal with reload
mensajeSuccessConfirm("Proceso completado");

// Modal with redirect
mensajeSuccessConfirm("Documento generado", "/reporte/descargar/123/");
```

---

## Common Patterns

### AJAX Success/Error Handling
```javascript
$.post('/url/', data, function(resp) {
    if (resp.resp) {
        alertaSuccess(resp.mensaje);
        $('#modal').modal('hide');
        location.reload();
    } else {
        alertaDanger(resp.mensaje);
    }
}).fail(function() {
    alertaDanger("Error de conexión");
});
```

### Delete Confirmation Pattern
```javascript
function eliminar(id) {
    Swal.fire({
        title: "¿Eliminar registro?",
        text: "Esta acción no se puede deshacer",
        type: "warning",  // ✅ CORRECT
        showCancelButton: true,
        confirmButtonText: "Sí, eliminar",
        cancelButtonText: "Cancelar",
        confirmButtonColor: "#d33"
    }).then((result) => {
        if (result.value) {  // ✅ CORRECT
            $.post('/eliminar/', {id: id}, function(resp) {
                if (resp.resp) {
                    alertaSuccess("Registro eliminado");
                    $('#tabla').DataTable().ajax.reload();
                } else {
                    alertaDanger(resp.mensaje);
                }
            });
        }
    });
}
```

---

## CRITICAL REMINDERS

⚠️ **NEVER use modern syntax:**
```javascript
// ❌ WRONG - Will NOT work
Swal.fire({
    icon: 'success',  // ❌ Use 'type' instead
    text: 'Message'
});

// ❌ WRONG - Will NOT work
.then((result) => {
    if (result.isConfirmed) {  // ❌ Use 'result.value' instead
        // ...
    }
});
```

✅ **ALWAYS use old syntax:**
```javascript
// ✅ CORRECT
Swal.fire({
    type: 'success',  // ✅
    text: 'Message'
});

// ✅ CORRECT
.then((result) => {
    if (result.value) {  // ✅
        // ...
    }
});
```

---

## Why This Matters

The current SweetAlert2 documentation online uses the MODERN syntax. If you copy examples directly from the docs, **alerts will silently fail** or produce unexpected behavior.

**ALWAYS** refer to this file when implementing SweetAlert2 in fastchatdj.
