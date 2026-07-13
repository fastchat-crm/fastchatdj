# Asignación de asesores y motor del chatbot tradicional

Referencia técnica del modelo de **quién atiende** una conversación y del
**motor del flujo pregunta→respuesta**. Estado vigente tras la consolidación a
fuente única por sesión/número.

---

## 1. Regla de oro

**La fuente única de verdad de "qué asesor atiende" una conversación es el
NÚMERO/SESIÓN de WhatsApp.**

- Los asesores se configuran en la sesión vía `whatsapp.PerfilSesionWhatsApp`
  (roles `supervisor` y `asesor` — **ambos** reciben asignación).
- La disponibilidad (`whatsapp.DisponibilidadAgente`) es un **filtro
  ortogonal** (online + tope de carga), NO un pool aparte.
- Los **departamentos** (`crm.DepartamentoChatBot`) definen **solo el flujo del
  bot**, no quién atiende. El modelo `PerfilDepartamentoChatBot` fue eliminado.

UI para configurar el equipo del número: `whatsapp/view_sesiones.py`
(acciones `guardar_usuarios` / `eliminar_usuario`) + modal
`whatsapp/templates/whatsapp/sesiones/_modal_usuarios.html`.

---

## 2. Fuente única de selección

Todo punto de asignación lee de **una sola función**:

`crm/helpers_asignacion.py` → `candidatos_ordenados(conversacion)` →
`[(usuario, carga), ...]` ya filtrado por disponibilidad y ordenado por **menos
asignaciones recibidas en las últimas 24 horas** (`HistorialAsignacion`,
ventana `HORAS_VENTANA_REPARTO=24`). Empate → quien lleva más tiempo sin
recibir asignación; luego menor carga abierta.

```
candidatos_ordenados(conv)
   │
   ├─ agentes_candidatos(conv)
   │     ├─ _agentes_de_sesion(sesion)          → PerfilSesionWhatsApp (status=True, is_active)
   │     └─ (si vacío) _agentes_legacy_disponibilidad(conv)   ← fallback de migración
   │
   ├─ por cada agente: _carga_abierta(u)        → ConversacionWhatsApp abiertas asignadas
   ├─ _asignaciones_ultimas_24h(agentes)        → HistorialAsignacion en ventana 24h
   ├─ filtra con DisponibilidadAgente            → disponible=True y carga < max_conversaciones
   │     (sin registro = disponible, sin tope)
   └─ ordena por (asignaciones_24h asc, ultimo_asignado_en asc, carga asc)
```

### Quién la consume

| Punto de asignación | Archivo | Nota |
|---|---|---|
| Handoff del flujo / timeout | `crm/helpers_asignacion.py:auto_asignar_agente` | Setea `ai_activo=False` (pausa IA) + notifica |
| Nodo `fin` con `notificar_asesor` | `crm/motor_flujo_chatbot.py` (rama `tipo == 'fin'`) | Motivo `fin_flujo`. Si la conv no tiene `asignado_a`, llama `auto_asignar_agente` — el agente elegido recibe notificación interna + correo con el link del chat, y se OMITE el broadcast al departamento (`_fin_asignado_nodo_id`). Si no hay candidatos o ya estaba asignada, cae al broadcast normal |
| Round-robin automático | `whatsapp/services_round_robin.py:asignar_automaticamente` | Lock transaccional + traza `AsignacionAutomatica`. **No** toca `ai_activo` |
| Dropdown manual | `whatsapp/forms.py:AsignarAgenteForm` | Mismo pool; muestra rol + carga |
| Botón "Tomar" en el panel | `whatsapp/view_conversaciones.py` action `tomar-conversacion` | Pull-based: el primer asesor que lo toca gana (UPDATE condicional atómico). Setea `ai_activo=False` + `HistorialAsignacion` + broadcast al sessionroom. Para habilitarlo, el rol asesor ahora ve también las conversaciones SIN asignar (`filtro_conversaciones_por_rol` → `asignado_a=user OR asignado_a is null`) |

---

## 3. Árbol de decisión — ¿a quién se asigna?

```
Mensaje / handoff / nueva conversación
        │
        ▼
¿conversacion.asignado_a ya existe?
   ├─ SÍ ──────────────────────────────────► no cambia (respeta al humano actual)
   └─ NO
        ▼
   Pool = asesores de la SESIÓN (PerfilSesionWhatsApp)
        │
        ├─ ¿pool vacío? ──► fallback legacy DisponibilidadAgente por sesión
        │                       └─ ¿también vacío? ──► NO asigna (queda en cola)
        ▼
   Filtra por disponibilidad:
        ├─ con registro DisponibilidadAgente: disponible=True Y carga < max
        └─ sin registro: se considera disponible
        ▼
   Ordena por (menos asignaciones en 24h, más antiguo sin asignación, menor carga)
        ▼
   Elige el primero
        ├─ handoff/timeout  → asignado_a + ai_activo=False + Historial + Notificación
        ├─ fin_flujo        → idem handoff; correo con link al agente; omite broadcast depto
        ├─ round-robin      → asignado_a + AsignacionAutomatica + Historial (NO toca ai_activo)
        └─ manual           → el operador elige del dropdown (mismo pool, ordenado por carga)
```

---

## 4. Notificaciones del flujo

Nodos con `config.notificar_asesor` o `config.envia_correo` disparan
`crm/helpers_correo_flujo.py:notificar_asesores_depto`, que ahora notifica a los
**asesores DISPONIBLES de la sesión** (correo + notificación interna), vía
`crm/helpers_asignacion.py:asesores_disponibles_sesion(conv)`.

Diferencia con la asignación: las notificaciones **no** filtran por tope de
carga — se avisa a todo el equipo que esté online. El departamento solo aporta
una etiqueta informativa en el texto.

---

## 5. Motor del chatbot tradicional (pregunta→respuesta)

`crm/motor_flujo_chatbot.py`. Máquina de estados sobre el árbol/DAG de nodos.
Entry point: `procesar_mensaje_tradicional(session, conversation, contacto,
texto, boton_id)`. Solo corre si `SesionWhatsApp.modo_bot == 'tradicional'`.

```
ChatBot tradicional
├── Ruteo a departamento (_elegir_departamento)
│     ├── palabras clave (sin tildes/mayúsculas vía _normalizar_texto)
│     ├── selector numérico
│     ├── departamento_default de la sesión
│     └── meta-menú si hay ambigüedad
│
├── Tipos de nodo (_procesar_nodo)
│     ├── respuesta / cta_url     envía texto (o botón link en Meta)
│     ├── menu                    presenta opciones, espera elección
│     ├── pregunta                pide dato, valida, captura en variable
│     ├── http / funcion          API externa / función Python, branch ok|error
│     ├── condicional / switch     ramas true|false|caso
│     ├── set_variable / loop      lógica interna
│     ├── handoff                  transfiere a asesor (auto_asignar_agente)
│     └── fin                      cierra el flujo
│
├── Robustez de entrada (mejoras recientes)
│     ├── _normalizar_texto       match sin tildes ni mayúsculas (keywords/menús)
│     ├── re-mostrar opciones      en menú/pregunta inválidos se reenvía el nodo
│     └── timeout → handoff        agotados los reintentos sin arista 'timeout',
│                                  _forzar_handoff transfiere a un humano
│
└── Anti-rebobinado (botones viejos de WhatsApp)
      ├── _marcar_historial        registra nodos visitados en variables['__historial']
      ├── _destinos_directos       nodos alcanzables desde el nodo actual
      └── guarda en salto boton_id  si el botón apunta a un nodo YA pasado y NO
                                    alcanzable desde el actual → ignora y re-orienta
```

### Reglas clave del motor
- **Reset por depto**: `DepartamentoChatBot.reset_triggers` reinicia el flujo
  del mismo depto; `RESET_KEYWORDS` (`menu`, `inicio`, `volver`, …) vuelve al
  meta-menú.
- **Estado runtime**: `crm.EstadoFlujoChatbot` (OneToOne por conversación):
  `nodo_actual`, `variables`, `intentos`, `en_handoff`, `finalizado`.
- **En handoff** (`en_handoff=True`) el motor no responde hasta que un humano
  libere la conversación.
- **Navegación de menús por texto/número**: al elegir una opción de un menú de
  varias opciones (árbol `opcion_padre`), el motor navega al **hijo elegido**
  puntualmente (no al primero). Lo resuelve `_hijo_menu_elegido` + `_avanzar`
  — clave para Baileys, donde no hay `boton_id` interactivo.

---

## 6. Generación de flujos con IA

- **Generador rápido** (botón "Menú rápido"):
  `crm/funciones_departamento_chatbot.py:_generar_departamento_con_ia` (action
  `generar_con_ia`) → `agents_ai/ai_actions/dpchatbots_crm.py:generar`. Crea
  `DepartamentoChatBot` + árbol de nodos `menu`/`respuesta`/`cta_url` desde una
  descripción libre.
- **Asistente Q&A** (botón "Armar proceso (Q&A)"):
  `_generar_departamento_wizard` (action `generar_con_ia_wizard`) →
  `dpchatbots_crm.generar_wizard`. Toma respuestas guiadas (objetivo, datos a
  pedir, opciones de menú, cuándo handoff) y arma un proceso **pregunta→respuesta**
  con nodos `pregunta` (captura + validación: email/cédula/teléfono/fecha/número)
  y `handoff`. Persistencia: `_crear_nodos_wizard` (respeta el `tipo` explícito
  de cada nodo). Prompt: `dpchatbots_wizard` en `agents_ai/ai_actions/prompts.py`.
  UI: modal `modalCrearConIA` en `templates/crm/departamento_chatbots/view.html`.
- **Asistente conversacional (chat)** (botón "Asistente IA (chat)"):
  `_wizard_chat` (action `wizard_chat`) → `dpchatbots_crm.conversar` (multi-turno:
  recibe historial + borrador, devuelve `{respuesta, flujo, listo}`) y
  `_wizard_crear` (action `wizard_crear`) → `dpchatbots_crm.crear_desde_borrador`.
  El frontend mantiene el historial y el borrador y los reenvía cada turno (el
  servidor es sin estado). Prompt: `dpchatbots_chat`. Persistencia compartida:
  `_persistir_flujo` + `_crear_nodos_wizard`. UI: modal `modalAsistenteChat` +
  `static/css/crm/asistente_chat.css`.
- **Editar un departamento por chat** (menú ⋮ → "Editar con chat (IA)"):
  GET `wizard_cargar_borrador` → `dpchatbots_crm.serializar_a_borrador` precarga
  el flujo actual como borrador (reverso de `_crear_nodos_wizard`, solo árbol
  `opcion_padre`). Al guardar, POST `wizard_actualizar` →
  `dpchatbots_crm.actualizar_desde_borrador`: **reemplaza** el flujo (soft-delete
  de nodos + aristas, recrea desde el borrador, resetea `EstadoFlujoChatbot` en
  vuelo del depto). Limitación: flujos con aristas complejas del canvas se
  aproximan al serializar — para esos, editar en el canvas.
- `explicar_flujo` genera/cachea una explicación narrativa del flujo existente.

Todos están desacoplados del modelo de asesores: el refactor de asignación no
los afecta.

---

## 7. Archivos referenciados

| Archivo | Rol |
|---|---|
| `crm/helpers_asignacion.py` | Fuente única: `candidatos_ordenados`, `auto_asignar_agente`, `asesores_disponibles_sesion`, notificación. `notificar_agente_asignado` dispara TRIPLE aviso: Notificacion interna (+push), correo con link, y WhatsApp al teléfono del agente (`_avisar_agente_por_whatsapp`, usa la sesión de la conversación; normaliza 09XXXXXXXX → 593...; en Meta puede fallar fuera de la ventana 24h — best-effort logueado). **Cada intento (los 3 canales, éxito o fallo con detalle) se persiste en `crm.LogNotificacionAsignacion`** (`_log_notif`) — visible en el modal "Avisos al asesor" del inbox (action GET `logs-notificaciones`) y del kebab del tablero de sesiones (action `logs_notificaciones`) |
| `whatsapp/services_round_robin.py` | Round-robin (lock + traza), delega el pool |
| `whatsapp/forms.py` (`AsignarAgenteForm`) | Dropdown manual, pool por sesión |
| `crm/helpers_correo_flujo.py` | Notificación del flujo a asesores disponibles de la sesión |
| `crm/motor_flujo_chatbot.py` | Motor del chatbot tradicional |
| `agents_ai/ai_actions/dpchatbots_crm.py` | Generación/explicación de flujos con IA |
| `whatsapp/models.py` | `PerfilSesionWhatsApp`, `DisponibilidadAgente`, `ConversacionWhatsApp`, `HistorialAsignacion`, `AsignacionAutomatica` |
| `whatsapp/view_sesiones.py` + `_modal_usuarios.html` | UI para configurar el equipo del número |
