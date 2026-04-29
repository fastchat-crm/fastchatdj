# Chatbot tradicional (flujo tipo n8n)

Motor de flujos conversacionales con menús, captura de datos, llamadas HTTP a
APIs externas, condicionales y handoff humano. Convive con el agente IA
existente sin interferir.

---

## 1. Para ejecutar / probar rápido

```bash
# 1) Aplicar migraciones (crea modelos nuevos)
python manage.py migrate

# 2) Sembrar un flujo de ejemplo (Centro de Atención Estudiantil)
python manage.py seed_centro_estudiantil

#    Opciones:
python manage.py seed_centro_estudiantil --reset          # borra y recrea
python manage.py seed_centro_estudiantil --sesion <id>    # asocia a una SesionWhatsApp
                                                           # y setea modo_bot='tradicional'

# 3) Activar el motor en una sesión manualmente (si no usaste --sesion)
#    Admin de Django → SesionWhatsApp → elige la sesión →
#    modo_bot = 'tradicional' (o 'hibrido')
#    departamento_default = Centro de Atención Estudiantil
#    departamentos (M2M) agregar el mismo depto
```

**Script que llena las plantillas base**:
`crm/management/commands/seed_centro_estudiantil.py`

Se invoca con: `python manage.py seed_centro_estudiantil`

---

## 2. Arquitectura en capas

```
┌─────────────────────────────────────────────────────────────┐
│  WhatsApp (Node.js) → webhook_handler (whatsapp/view_...)   │
│                        │                                     │
│                        │ if session.modo_bot in              │
│                        │   ('tradicional','hibrido'):        │
│                        ▼                                     │
│           crm/motor_flujo_chatbot.py                         │
│           procesar_mensaje_tradicional(...)                  │
│                        │                                     │
│     ┌──────────────────┼──────────────────┐                  │
│     ▼                  ▼                  ▼                  │
│  Resolver         Validador          EjecutorHTTP            │
│  expresiones      (email,cédula…)    (requests+auth)         │
│     └──────────────────┼──────────────────┘                  │
│                        ▼                                     │
│               Modelos de grafo (crm/models.py)               │
│   DepartamentoChatBot → OpcionDepartamentoChatBot            │
│      ↑                      │                                │
│      │                      ├── ConexionNodoChatbot (aristas)│
│      │                      └── EndpointApiChatbot →         │
│      │                             CredencialApiChatbot      │
│      │                                                       │
│   EstadoFlujoChatbot ← 1:1 → ConversacionWhatsApp            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Modelos (qué guarda cada uno)

| Modelo | Rol |
|---|---|
| `DepartamentoChatBot` | Workflow completo. Campos: `nombre`, `mensaje_saludo`, `palabras_clave`, `es_default`, `activo_tradicional`. |
| `OpcionDepartamentoChatBot` | **Nodo** del grafo. Campos clave: `tipo_nodo`, `config` (JSON), `endpoint`, `variable_destino`, `validacion_tipo`, `reintentos_max`, `es_inicio`. Mantiene `opcion_padre` como fallback legacy (árbol). |
| `ConexionNodoChatbot` | **Arista** origen→destino con `etiqueta` (vacía=default, `true`/`false`, `ok`/`error`, `opcion_X`, `timeout`…). |
| `CredencialApiChatbot` | Credencial reusable (`none`/`bearer`/`basic`/`apikey_header`/`apikey_query`/`custom_header`). Secretos en JSON. |
| `EndpointApiChatbot` | Endpoint HTTP reusable: `base_url`, `credencial`, `headers_default`, `timeout_seg`. |
| `EstadoFlujoChatbot` | 1:1 con `ConversacionWhatsApp`. Guarda `nodo_actual`, `variables` (JSON), `intentos`, `finalizado`. |

**Switch global en `whatsapp.SesionWhatsApp`**:
- `modo_bot`: `ia` (default) / `tradicional` / `hibrido` / `ninguno`
- `departamento_default`: depto al que va si no hay match por palabras clave.

---

## 4. Tipos de nodo

| Tipo | Qué hace | Config principal | Etiquetas de salida |
|---|---|---|---|
| `menu` | Lista opciones, espera elección por número/texto | `{mensaje, opciones:[{etiqueta,valor,salida}]}` | la `salida` de cada opción, `timeout` |
| `pregunta` | Pide dato, valida, guarda en `variable_destino` | `{pregunta}` + `validacion_tipo` del nodo | `''` ok, `timeout` tras N fallos |
| `respuesta` | Envía texto y avanza | `{mensaje}` | `''` |
| `http` | Llama API externa | `{metodo, path, query, body, extraer[], plantilla_respuesta}` + `endpoint` FK | `ok`, `error` |
| `condicional` | If/Else | `{operador: and/or, condiciones:[{izq,op,der}]}` | `true`, `false` |
| `switch` | Branch por valor | `{valor, casos:[{match,salida}]}` | salida del caso o `default` |
| `set_variable` | Asigna variables | `{asignaciones:[{variable,expresion}]}` | `''` |
| `handoff` | Transfiere a humano | `{mensaje}` | termina turno |
| `esperar` | Delay | `{segundos}` | `''` |
| `fin` | Cierra flujo | `{mensaje}` | marca `finalizado=True` |
| `inicio` | Arranque explícito | — | `''` |

### Operadores de `condicional`

`==`, `!=`, `>`, `<`, `>=`, `<=`, `contiene`, `no_contiene`, `vacio`, `no_vacio`.

### Validaciones de `pregunta`

`email`, `numero`, `telefono`, `fecha` (YYYY-MM-DD), `cedula` (EC, algoritmo verificador), `ruc`, `regex` (con `validacion_expresion`).

---

## 5. Expresiones `{{...}}` (resolver)

En cualquier string de `config` puedes usar placeholders. Contexto disponible:

| Expresión | Valor |
|---|---|
| `{{variables.X}}` | Variable capturada o extraída (cédula, respuesta HTTP…) |
| `{{contacto.numero}}` | Número del contacto |
| `{{contacto.nombre}}` | Nombre del contacto |
| `{{conversacion.id}}` | ID de la conversación |
| `{{sesion.numero}}` / `{{sesion.nombre}}` / `{{sesion.session_id}}` | Datos de la sesión |
| `{{mensaje.texto}}` | Último mensaje del usuario |

Soporta paths anidados: `{{_last_http.body.data[0].nombre}}`.
Si la cadena completa es una expresión (`"{{variables.n}}"`), se preserva el tipo original (útil para JSON bodies con números/booleans).

---

## 6. Ciclo de vida de un mensaje

```
llega mensaje → webhook_handler guarda MensajeWhatsApp
                    │
                    ▼
       session.modo_bot in ('tradicional','hibrido') ?
                    │ sí
                    ▼
        procesar_mensaje_tradicional()
                    │
                    ▼
       ¿existe EstadoFlujoChatbot para esta conversación?
         └── no o finalizado → crear / resetear
                    │
                    ▼
       ¿estado.nodo_actual es None?
         └── sí (primer turno):
              1. _elegir_departamento()
                   a. match por palabras_clave
                   b. selector numérico 1,2,3…
                   c. session.departamento_default
                   d. departamento con es_default=True
              2. enviar depto.mensaje_saludo
              3. nodo_actual = depto.nodo_inicio()
              4. _run_loop(consumir_mensaje=False)
         └── no:
              _run_loop(consumir_mensaje=True)
                    │
                    ▼
       _run_loop:
         while nodo_actual and not finalizado and not handoff:
             si es menu/pregunta sin mensaje → presentar prompt y SALIR
             ejecutar nodo → etiqueta de salida
             si reintento pendiente → SALIR (estado guardado)
             avanzar: buscar ConexionNodoChatbot con esa etiqueta
             (fallback a árbol legacy si etiqueta='' y no hay conexión)
             consumir_mensaje = False  (sólo el primero consume)
                    │
                    ▼
       Retorna ResultadoFlujo(manejado, fallback_ia, handoff, finalizado, respuestas)
                    │
                    ▼
       Webhook decide:
         - manejado → return (corta ahí)
         - modo='tradicional' sin match → return (no IA)
         - modo='hibrido' sin match → cae al bloque IA existente
```

**Dato clave**: un solo mensaje puede ejecutar una cadena larga de nodos (ej: `pregunta → http → set_variable → condicional → respuesta → fin`), porque todos los que no requieren input corren en cascada hasta topar con `menu`/`pregunta` o con `fin`/`handoff`.

Tope de seguridad: `MAX_NODOS_POR_TURNO = 25`.

---

## 7. Matriz `modo_bot`

| Modo | Motor tradicional | Agente IA | Caso de uso |
|---|---|---|---|
| `ia` (default) | ❌ | ✅ | Comportamiento previo, sin cambios |
| `tradicional` | ✅ | ❌ | Flujo estricto con APIs |
| `hibrido` | ✅ | ✅ si motor no matcheó | FAQ por flujo, el resto a IA |
| `ninguno` | ❌ | ❌ | Sólo humanos |

El bloque nuevo en `whatsapp/webhook_baileys_view.py` **corta** antes de llegar al pipeline IA cuando el motor manejó la conversación. Genera trazas `etapa='motor_flujo'`.

---

## 8. Recetas de `config` por tipo de nodo

### `menu`
```json
{
  "mensaje": "¿Qué deseas?",
  "opciones": [
    {"etiqueta": "Consultar saldo", "valor": "saldo",  "salida": "saldo"},
    {"etiqueta": "Hablar con asesor","valor": "asesor", "salida": "asesor"}
  ]
}
```
Conexiones: `ConexionNodoChatbot(origen=menu, destino=nodo_saldo, etiqueta='saldo')`, etc.

### `pregunta`
```json
{"pregunta": "Dime tu cédula (10 dígitos):"}
```
Campos del nodo: `variable_destino='cedula'`, `validacion_tipo='cedula'`, `reintentos_max=3`, `mensaje_error='Cédula inválida'`.

### `http`
```json
{
  "metodo": "POST",
  "path": "/clientes/{{variables.cedula}}/saldo",
  "query": {"periodo": "2026-1"},
  "body": {
    "cedula": "{{variables.cedula}}",
    "canal": "whatsapp"
  },
  "extraer": [
    {"variable": "saldo",   "jsonpath": "data.saldo"},
    {"variable": "cliente", "jsonpath": "data.nombre"}
  ],
  "plantilla_respuesta": "Hola {{variables.cliente}}, tu saldo es ${{variables.saldo}}"
}
```
Campo del nodo: `endpoint` FK al `EndpointApiChatbot`.
Salidas: `ok` (2xx) / `error` (no-2xx, timeout, conexión).

### `condicional`
```json
{
  "operador": "and",
  "condiciones": [
    {"izq": "{{variables.saldo}}", "op": ">",        "der": "0"},
    {"izq": "{{variables.tipo}}",  "op": "contiene", "der": "VIP"}
  ]
}
```

### `switch`
```json
{
  "valor": "{{variables.tipo_cliente}}",
  "casos": [
    {"match": "vip",     "salida": "vip"},
    {"match": "regular", "salida": "regular"}
  ]
}
```

### `set_variable`
```json
{
  "asignaciones": [
    {"variable": "saludo_fmt", "expresion": "Hola {{contacto.nombre}}"},
    {"variable": "timestamp",  "expresion": "2026-04-15"}
  ]
}
```

### `handoff`
```json
{"mensaje": "Te conecto con un asesor…"}
```

### `fin`
```json
{"mensaje": "Gracias por tu consulta."}
```

---

## 9. Credenciales (autenticación de APIs)

`CredencialApiChatbot.secretos` es un JSON cuyo shape depende de `tipo`:

| Tipo | Shape de `secretos` |
|---|---|
| `none` | `{}` |
| `bearer` | `{"token": "eyJ..."}` |
| `basic` | `{"usuario": "x", "password": "y"}` |
| `apikey_header` | `{"nombre_header": "X-API-Key", "valor": "abc123"}` |
| `apikey_query` | `{"nombre_param": "api_key", "valor": "abc123"}` |
| `custom_header` | `{"headers": {"X-Tenant": "a", "X-Env": "prod"}}` |

> Se guardan en texto plano (igual que `ApiKeyIA.descripcion` del módulo IA).
> Si se necesita cifrado más adelante, migrar a un campo cifrado y adaptar
> `_aplicar_credencial()` en el motor.

---

## 10. Ejemplo: el seed del Centro Estudiantil

`crm/management/commands/seed_centro_estudiantil.py` crea:

- **1 departamento** `Centro de Atención Estudiantil` (`es_default=True`).
- **1 credencial demo** + **2 endpoints demo** (`jsonplaceholder`, `httpbin`).
- **18 nodos**, **23 conexiones**.

Grafo:

```
[Menú principal] (menu: matricula, notas, horarios, becas, asesor)
 ├── matricula → [Pedir cédula] → [HTTP matrícula] ─ok→ [Fin]
 │                                                 └─error/timeout→ [Handoff]
 ├── notas     → [Pedir cédula] → [HTTP notas] ─ok→ [Fin notas]
 │                                             └─error→ [Aviso] → [Fin notas]
 ├── horarios  → [Menú carrera] → [HTTP horario] ─ok→ [Fin horario]
 │                                               └─error→ [Handoff]
 ├── becas     → [Info becas] → [¿Aplicar?] → [Condicional aplica]
 │                                                ├─true →[Set promedio]→[POST becas] ─ok→[Fin becas]
 │                                                │                                    └─error→[Handoff]
 │                                                └─false→[Mensaje "ok"]→[Fin becas]
 └── asesor    → [Handoff humano]
```

Ejemplos demostrados en el seed:
- Validación real de cédula ecuatoriana.
- GET con query templates (`{{variables.cedula}}`).
- POST con body templates (`{{contacto.numero}}`, `{{conversacion.id}}`).
- Extracción JSONPath (`args.cedula`, `address.city`).
- Condicional `or` con `contiene`.
- `set_variable` inyectando dato antes de un POST.
- Rama `timeout` cuando se agotan reintentos.
- Rama `error` cuando el HTTP falla.

### Flujo de prueba end-to-end

1. WhatsApp → `hola` → menú principal.
2. → `1` → pide cédula.
3. → `1710034065` → valida, hace GET a httpbin, extrae echo, responde `"Matrícula ACTIVA…"`, cierra flujo.

---

## 11. Archivos principales

| Archivo | Rol |
|---|---|
| `crm/models.py` | Modelos del grafo (extiende `OpcionDepartamentoChatBot`, agrega `Credencial/Endpoint/Conexion/Estado`) |
| `crm/motor_flujo_chatbot.py` | **Motor de ejecución** (único entry: `procesar_mensaje_tradicional`) |
| `crm/admin.py` | Admin de Django para editar el grafo manualmente |
| `crm/management/commands/seed_centro_estudiantil.py` | **Seed base — comando a ejecutar para plantillas** |
| `whatsapp/webhook_baileys_view.py` | Enganche del motor (bloque nuevo antes del pipeline IA) |
| `whatsapp/models.py` | `SesionWhatsApp.modo_bot` + `departamento_default` |

---

## 12. Edición manual de flujos

Mientras no exista editor visual:

- **Admin de Django** (`/admin/crm/`):
  - `Departamentos ChatBot` → crear + `es_default`, palabras clave.
  - `Nodos de Flujo ChatBot` → crear cada nodo, `tipo_nodo`, `config` (JSON), marcar `es_inicio` en el primero.
  - `Conexiones entre nodos` → aristas con `etiqueta`.
  - `Endpoints API ChatBot` / `Credenciales API ChatBot` → catálogo de APIs externas.
  - `Sesiones WhatsApp` → `modo_bot`, `departamento_default`, M2M `departamentos`.

- **Seed programático**: replicar el patrón de `seed_centro_estudiantil.py` (`_nodo()` y `_conectar()`), es la forma más rápida para flujos medianos/grandes.

---

## 13. Extensiones futuras (no hechas)

- Cifrado de `CredencialApiChatbot.secretos`.
- Editor visual del grafo (drag-and-drop).
- Nodo `ia` para delegar a agente IA a mitad del flujo y volver.
- Retries/backoff automáticos en nodo `http`.
- Plantillas de flujos exportables (JSON).
