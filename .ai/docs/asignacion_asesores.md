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
`[(usuario, carga), ...]` ya filtrado por disponibilidad y ordenado por menor
carga (empate → quien lleva más tiempo sin recibir asignación).

```
candidatos_ordenados(conv)
   │
   ├─ agentes_candidatos(conv)
   │     ├─ _agentes_de_sesion(sesion)          → PerfilSesionWhatsApp (status=True, is_active)
   │     └─ (si vacío) _agentes_legacy_disponibilidad(conv)   ← fallback de migración
   │
   ├─ por cada agente: _carga_abierta(u)        → ConversacionWhatsApp abiertas asignadas
   ├─ filtra con DisponibilidadAgente            → disponible=True y carga < max_conversaciones
   │     (sin registro = disponible, sin tope)
   └─ ordena por (carga asc, ultimo_asignado_en asc)
```

### Quién la consume

| Punto de asignación | Archivo | Nota |
|---|---|---|
| Handoff del flujo / timeout | `crm/helpers_asignacion.py:auto_asignar_agente` | Setea `ai_activo=False` (pausa IA) + notifica |
| Round-robin automático | `whatsapp/services_round_robin.py:asignar_automaticamente` | Lock transaccional + traza `AsignacionAutomatica`. **No** toca `ai_activo` |
| Dropdown manual | `whatsapp/forms.py:AsignarAgenteForm` | Mismo pool; muestra rol + carga |

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
   Ordena por (menor carga, más antiguo sin asignación)
        ▼
   Elige el primero
        ├─ handoff/timeout  → asignado_a + ai_activo=False + Historial + Notificación
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

---

## 6. Generación de flujos con IA

- `crm/funciones_departamento_chatbot.py:_generar_departamento_con_ia` (action
  `generar_con_ia`) → delega en `agents_ai/ai_actions/dpchatbots_crm.py:generar`.
  Crea `DepartamentoChatBot` + árbol de nodos `menu`/`respuesta`/`cta_url` desde
  una descripción libre. **No** toca asesores.
- `explicar_flujo` genera/cachea una explicación narrativa del flujo existente.

Ambos están desacoplados del modelo de asesores: el refactor de asignación no
los afecta.

---

## 7. Archivos referenciados

| Archivo | Rol |
|---|---|
| `crm/helpers_asignacion.py` | Fuente única: `candidatos_ordenados`, `auto_asignar_agente`, `asesores_disponibles_sesion`, notificación |
| `whatsapp/services_round_robin.py` | Round-robin (lock + traza), delega el pool |
| `whatsapp/forms.py` (`AsignarAgenteForm`) | Dropdown manual, pool por sesión |
| `crm/helpers_correo_flujo.py` | Notificación del flujo a asesores disponibles de la sesión |
| `crm/motor_flujo_chatbot.py` | Motor del chatbot tradicional |
| `agents_ai/ai_actions/dpchatbots_crm.py` | Generación/explicación de flujos con IA |
| `whatsapp/models.py` | `PerfilSesionWhatsApp`, `DisponibilidadAgente`, `ConversacionWhatsApp`, `HistorialAsignacion`, `AsignacionAutomatica` |
| `whatsapp/view_sesiones.py` + `_modal_usuarios.html` | UI para configurar el equipo del número |
