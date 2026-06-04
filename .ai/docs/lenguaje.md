# Lenguaje — español obligatorio en UI

Estándar del proyecto para texto visible al usuario. Sobreescribe cualquier convención previa.

## Regla

Todo lo que el usuario ve en pantalla — labels, botones, encabezados de columnas, badges, mensajes flash, alertas SweetAlert, toasts, modales, tooltips, placeholders, copys de ayuda, mensajes vacíos, títulos, sub-títulos — debe escribirse en **español**.

## Aplica a

| Capa | Qué traducir |
|------|--------------|
| Templates `*.html` | `<label>`, texto de `<button>`, `<th>` headers, `placeholder`, `title`, copy descriptivo, badges, alertas, mensajes vacíos de tabla |
| JS inline o `*.js` | `Swal.fire({title, text, confirmButtonText, cancelButtonText})`, `mensajeSuccess`, `mensajeWarning`, `alert`, `confirm`, `toast`, textos dinámicos que se inyectan al DOM |
| Backend Python | Strings de `messages.success/error/info`, `JsonResponse({'message': ...})`, `JsonResponse([{'error': True, 'message': ...}])`, strings que arroja `raise`, mensajes del helper `log()` que aparecen en auditoría |
| Forms | `verbose_name` en modelos nuevos, `help_text`, `label` cuando se sobreescribe, mensajes de validación |

## No aplica a

| | |
|--|--|
| Nombres de variables Python | Pueden seguir en español (`criterio`, `filtro`, `listado`, `usuarios`) o inglés, libre. Convención del proyecto es español. |
| Nombres de campos de modelo | Igual — neutral. |
| Slugs, paths URL, nombres de acciones AJAX | En inglés / kebab-case (`/seguridad/webpush-broadcast/`, `action=enviar_prueba`). |
| Términos técnicos universales | No se traducen: `push`, `URL`, `endpoint`, `service worker`, `payload`, `tag`, `webhook`, `API`, `Meta`, `WhatsApp`, `Baileys`, `JWT`, `cron`, `JSON`. |
| Identificadores CSS / JS | `chkUsuario`, `frmEnviarPrueba`, clases CSS — libres. |
| Templates ya existentes en inglés | Solo traducí lo que estás modificando ahora; no entres a refactorear todo el archivo "de paso". |

## Ejemplos

### Bien

```html
<button class="btn btn-success">
    <i class="fa fa-paper-plane me-1"></i> Enviar push de prueba
</button>

<th>Usuario</th>
<th>Documento</th>
<th class="text-center">Dispositivos</th>

<td colspan="6" class="text-center text-muted py-3">No hay dispositivos suscriptos.</td>
```

```python
return JsonResponse([{'error': False, 'message': 'Dispositivo eliminado.'}], safe=False)
messages.success(request, 'Configuración guardada correctamente.')
log(f'Push de prueba enviado a {n} usuarios', request, 'add')
```

```js
Swal.fire({
    title: '¿Eliminar este dispositivo?',
    text: 'Se revoca la suscripción. El usuario tendrá que volver a aceptar.',
    confirmButtonText: 'Sí, eliminar',
    cancelButtonText: 'Cancelar'
});
```

### Mal

```html
<button>Send test push</button>          <!-- inglés -->
<th>User</th>                              <!-- inglés -->
<td>No devices found.</td>                 <!-- inglés -->
```

```python
return JsonResponse([{'error': True, 'message': 'No users selected.'}], safe=False)   # inglés
messages.error(request, 'Save failed.')                                                # inglés
```

## Default copy útiles

Cuando agregás formularios de prueba (envío de notificaciones, mensajes de demo, etc.), poné un texto por defecto en español + emojis comunes para que el usuario solo tenga que hacer clic en "Enviar" para probar:

- Título: `🔔 Notificación de prueba`
- Cuerpo: `✅ Hola, esta es una notificación de prueba.`

Variantes:
- `📣 Aviso para todos` (broadcast)
- `📱 Ping de prueba a un dispositivo específico.` (dispositivo único)
- `🚀 Mensaje masivo enviado a todos los dispositivos suscriptos.`

## Memoria de Claude

Esta regla también está guardada como feedback en la memoria persistente del modelo (`feedback_textos_espanol.md`) — sobrevive entre sesiones de Claude.
