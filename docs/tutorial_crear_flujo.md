# Tutorial — Cómo crear y operar un flujo de chatbot

Este documento es la versión escrita del tutorial in-app accesible desde
`/crm/departamentos_chatbots/?action=change&id=<id>&full=1` → botón
**Tutorial** en la barra superior.

---

## Glosario rápido

| Concepto | Qué es |
|---|---|
| **Departamento** | Unidad ejecutable del chatbot. Contiene el flujo completo. |
| **Nodo** | Paso individual del flujo. Cada uno tiene un tipo (menú, pregunta, HTTP…). |
| **Conexión** | Une un nodo con el siguiente según una etiqueta (`ok`, `error`, valor del menú, `true`/`false`). |
| **Variable** | Dato capturado durante la conversación. Disponible vía `{{variables.nombre}}`. |
| **Endpoint** | URL externa registrada en `/crm/endpoints_api/` que un nodo HTTP puede llamar. |

---

## Indicadores visuales por nodo

En el editor y el diagrama, cada nodo puede mostrar:

- 🏁 **Termina flujo** — El nodo es de tipo `fin`. Cierra la conversación.
- 📧 **Envía correo** — El nodo dispara una notificación por email como
  side-effect (configurado con `config.envia_correo: true`).

Ejemplo: en el flujo ARIA, el nodo `340 — POST proxy → webhook ARIA + email
asesores` está marcado con ambos indicadores porque dispara una notificación
por email a los asesores del departamento.

---

## Nivel 1 — Básico (lo mínimo para arrancar)

Lo que necesitas para tener un flujo corriendo:

1. **Crear el departamento**: Nombre, color, mensaje de saludo. El primer
   guardado lo persiste.
2. **Agregar un nodo raíz**: Botón "Agregar opción raíz" en el editor.
3. **Marcar el inicio**: `es_inicio=true` en el nodo desde donde arranca el
   flujo. Solo uno por depto.
4. **Encadenar nodos**: En el modal de cada nodo, sección "Conexiones" →
   elige el nodo siguiente. Etiqueta vacía es la conexión default.
5. **Terminar el flujo**: Nodo tipo `fin` con un mensaje de despedida. El
   editor lo marca con el badge **🏁 Termina flujo**.
6. **Probar**: Botón "Preview" para simular el chat sin tocar WhatsApp.

---

## Nivel 2 — Intermedio (variables, validaciones, menús)

- **Capturar respuestas**: Tipo `pregunta` con `variable_destino` (ej.
  `cedula`). El contenido del cliente queda en `{{variables.cedula}}`.
- **Validaciones**: regex (`^\d{10}$`), email, teléfono — el bot reintenta
  hasta `reintentos_max` veces y luego salta a la rama de error.
- **Menús**: Tipo `menu`. Opciones estáticas (etiqueta → nodo siguiente) o
  dinámicas (`opciones_fuente` desde una variable JSON-array).
- **Condicionales**: Tipo `condicional` con expresiones tipo
  `{{variables.encontrado}} == true` → bifurca a ramas `true` / `false`.
- **Asignar variables**: Tipo `set_variable` para calcular o resetear
  valores. El último paso suele resetear todo antes del nodo `fin`.
- **Plantillas en mensajes**: Cualquier texto puede interpolar:
  - `{{contacto.nombre}}` — nombre del contacto.
  - `{{contacto.numero}}` — número WhatsApp.
  - `{{conversacion.id}}` — id de la conversación actual.
  - `{{sesion.nombre}}` — nombre de la sesión.
  - `{{variables.foo}}` — cualquier variable capturada.

---

## Nivel 3 — Avanzado (HTTP, side-effects, integraciones)

- **Llamadas HTTP**: Tipo `http` con un endpoint registrado. El path soporta
  templates: `buscar/{{variables.cedula}}/`.
- **Funciones internas**: Tipo `funcion` ejecuta código Python registrado
  con `@registrar_funcion('codigo')` en `crm/funciones_chatbot.py`. Reemplaza
  un nodo HTTP cuando la lógica vive dentro de Django (orquestar webhooks
  externos, DB lookups, side-effects). El operador asocia un
  `EndpointApiChatbot` opcional → la URL externa queda 100% configurable
  sin tocar código.
- **Extraer variables del response**:
  ```json
  "extraer": [
    {"variable": "cotpk",    "jsonpath": "data.cotpk"},
    {"variable": "cliente",  "jsonpath": "data.cliente_id"}
  ]
  ```
  JSONPath es relativo al body de respuesta.
- **Ramificación ok / error**:
  - Status `2xx` con `success: true` (o sin ese campo) → rama `ok`.
  - Status `4xx` / `5xx`, `success: false`, o timeout → rama `error`.
- **Envío de correo**: Marca el nodo con `config.envia_correo: true` para
  que aparezca con el badge **📧 Envía correo** en el editor. El motor
  dispara el correo a los asesores del depto cuando el nodo retorna `ok`.
- **Side-effects con lógica Django**: cuando necesités orquestar DB lookup
  + email + log + webhook externo, usá un nodo `funcion` apuntando a una
  función registrada propia (no hace falta crear un proxy HTTP intermedio).
- **Handoff humano**: Tipo `handoff` pausa la IA. La conv queda abierta
  para que un asesor responda manualmente.
- **Deep-links a conversaciones**: En un correo o CTA podés generar
  `/whatsapp/conversaciones/?conv=<token>` con
  `encrypt_sesion_id(conv.id)`. La URL abre la conv si está activa, o
  redirige a la página de finalizadas si ya cerró.

---

## Referencia rápida — tipos de nodo

| Tipo | Qué hace |
|---|---|
| `respuesta` | Manda un mensaje y avanza al siguiente nodo (sin esperar al cliente). |
| `pregunta` | Espera la respuesta del cliente y la guarda en `variable_destino`. |
| `menu` | Lista de opciones. Cada opción tiene su propio nodo destino. |
| `http` | POST/GET a una API. Extrae datos de la respuesta a variables. |
| `condicional` | Evalúa una expresión sobre variables y bifurca. |
| `set_variable` | Setea o limpia variables del contexto. |
| `cta_url` | Botón que abre una URL externa al cliente. |
| `ubicacion` | Manda lat/lng como pin de WhatsApp. |
| `handoff` | Pausa la IA; un asesor toma la conversación. |
| `fin` | Cierra la conversación. Marcado con **🏁 Termina flujo**. |

---

## Buenas prácticas

- **Numeración**: Numerá los nodos en saltos de 10 (10, 20, 30…) para
  insertar pasos intermedios sin renumerar.
- **Toda rama de error → un `fin`**: Con un mensaje claro tipo
  *"Inténtalo más tarde"*. No dejes ramas sin destino.
- **Limpia variables antes del fin**: Usá `set_variable` para vaciar
  cedula, placa, etc. por si el cliente reabre la conv.
- **Timeouts realistas**: En nodos HTTP ajustá `timeout_seg` — un POST a
  un cotizador puede tardar 30-60s.
- **Probar en preview**: Las URLs externas y los mensajes con
  `{{variables.foo}}` se resuelven en runtime; usá Preview antes de
  exponerlo a un cliente real.
- **Marca side-effects**: Si un nodo dispara correos / notificaciones /
  webhooks externos, marcá `config.envia_correo = true` (o un flag
  análogo) para que el operador lo vea como tal en el editor.

---

## Caso completo de ejemplo: ARIA Cotizador (v3)

El flujo `ARIA — Cotizador de seguros` (creado por
`python manage.py seed_cotizador`) ilustra estos conceptos:

1. **Nivel básico**: saludo → pedir placa → pedir cédula → confirmar.
2. **Nivel intermedio**: catálogos (tipos, provincias) en menús dinámicos
   construidos desde variables JSON traídas con HTTP.
3. **Nivel avanzado**: nodo final `340` que llama a un proxy Django
   interno. Ese proxy:
   - POSTea al webhook externo `https://fguerrero.mgaseguros.ec/webhook/cotizar/`
   - Si 202 → envía email a los asesores del departamento.
   - Devuelve `{success: true|false}` para que el flujo elija rama `ok` o
     `error`.

El nodo `340` está marcado con **📧 Envía correo** en el editor.
El nodo `999` (despedida) está marcado con **🏁 Termina flujo**.

---

## Atajos de teclado

| Combo | Acción |
|---|---|
| `Esc` | Cierra el modal de edición sin guardar. |
| `Ctrl + Enter` (en modal) | Guarda y cierra. |
| Click en `Tutorial` | Abre esta guía in-app. |
| Click en `Preview` | Simula el flujo en una vista WhatsApp-like. |
| Click en `Diagrama` | Vista de árbol con todas las ramas. |
| Click en `JSON` | Snapshot del flujo completo + cookbook para seed. |
