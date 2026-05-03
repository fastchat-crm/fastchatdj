# Roadmap CRM · Bandeja del asesor + Ficha 360 + Control

> **Propósito.** Inventariar lo que la plataforma **ya cubre** (mensajería + chatbot + IA + pipeline) y mapear los huecos que faltan para tener un **CRM operativo + control ejecutivo + asistencia humana** completos. Cada gap se documenta con: qué necesita, cómo se conecta con los modelos existentes, esfuerzo estimado y orden recomendado.
>
> **No es spec final**: es punto de partida para iterar.

---

## Índice

1. [Estado actual: qué ya tenemos](#estado-actual-qué-ya-tenemos)
2. [Huecos identificados](#huecos-identificados)
3. [Plan priorizado](#plan-priorizado)
4. [Detalle por iniciativa](#detalle-por-iniciativa)
   - [#1 Bandeja del asesor](#1-bandeja-del-asesor-inbox-unificado)
   - [#2 Ficha 360° del contacto](#2-ficha-360-del-contacto)
   - [#3 Dashboard de control ejecutivo](#3-dashboard-de-control-ejecutivo)
   - [#4 Tareas y recordatorios](#4-tareas-y-recordatorios-por-contacto)
   - [#5 Notas internas + adjuntos](#5-notas-internas--adjuntos-en-conversación)
   - [#6 Reportes exportables](#6-reportes-exportables)
   - [#7 Plantillas rápidas por asesor](#7-plantillas-de-respuesta-rápida-por-asesor)
   - [#8 Análisis de conversaciones con IA](#8-análisis-de-conversaciones-con-ia)
5. [Decisiones arquitectónicas](#decisiones-arquitectónicas)
6. [Riesgos y dependencias](#riesgos-y-dependencias)

---

## Estado actual: qué ya tenemos

### Capa de mensajería · `whatsapp/`

| Modelo | Cubre |
|---|---|
| `SesionWhatsApp` | Conexión a un número (Meta Cloud / Baileys / Instagram / Messenger) con modo de bot, depto default, agente IA, horario, pixel CAPI |
| `Contacto` + `PerfilContacto` | Identidad del cliente desde su número de WhatsApp (datos demográficos básicos) |
| `ConversacionWhatsApp` | Una conversación entre contacto y sesión (multi-canal) |
| `MensajeWhatsApp` | Cada mensaje individual con metadatos Meta/Baileys |
| `EtiquetaContacto` | Tags multi-selección sobre un contacto |
| `PipelineVenta` + `EtapaPipeline` + `ConversacionEnPipeline` + `HistorialEtapaPipeline` | **Kanban de ventas funcional** ya modelado |
| `HistorialAsignacion`, `DisponibilidadAgente`, `AsignacionAutomatica` | Round-robin a agentes humanos |
| `HorarioAtencion`, `ExcepcionHorario` | Reglas de horario por sesión |
| `PlantillaWhatsApp`, `TarifaPlantillaMeta` | Templates Meta + tarificación |
| `Campana`, `EnvioCampana` | Envíos masivos con tracking |
| `WebhookSaliente`, `EntregaWebhookSaliente` | Integración tipo Zapier |
| `PixelMeta`, `EventoCAPI` | Atribución Meta Ads + Conversions API |
| `MenuRapidoSesion` | Respuestas rápidas (¿por sesión?, no por asesor) |

### Capa CRM + IA · `crm/`

| Modelo | Cubre |
|---|---|
| `DepartamentoChatBot` + `OpcionDepartamentoChatBot` + `ConexionNodoChatbot` | Flujo de chatbot estilo n8n con grafo |
| `EstadoFlujoChatbot` | En qué nodo está cada conversación |
| `AgentesIA` + `DetalleAgentesAI` + `HerramientaAgente` + `LogHerramientaAgente` | Agente IA conversacional con tool-use |
| `ApiKeyIA`, `ConsumoTokenIA`, `AlertaConsumoIA` | Gestión de claves y consumo IA |
| `PerfilNegocioIA`, `ProductoIA`, `ServicioIA`, `RespuestaEntrenadaIA` | Knowledge base del negocio para el agente |
| `AuditoriaAgenteIA`, `FeedbackMensajeBot` | Telemetría + RLHF |
| `ReglaFinConversacion`, `AccionFinConversacion` | Automatizaciones post-cierre |
| `Industria`, `ActividadEconomica`, `EtapaVenta` | Catálogos |

### Capa de soporte

- `agents_ai/MessageStore` — memoria conversacional del agente IA
- `voz/LlamadaVoz`, `MensajeVoz` — canal voz
- `cron_jobs/` — tareas programadas
- `seguridad/` — auth, módulos, empresa multi-tenant

### Resumen ejecutivo

> La plataforma cubre extremo a extremo: **canal entrante → bot tradicional o IA → handoff humano → pipeline de ventas → atribución Meta Ads → webhooks salientes**. Lo que falta es **operativizar** esa potencia: que un asesor humano tenga "su pantalla" para trabajar y que la gerencia tenga "su tablero" para medir.

---

## Huecos identificados

| # | Hueco | Impacto | Esfuerzo |
|---|---|---|---|
| 1 | Bandeja del asesor (inbox unificado con SLA) | 🔥 Alto | M (3-5 días) |
| 2 | Ficha 360° del contacto | 🔥 Alto | M (3-5 días) |
| 3 | Dashboard de control ejecutivo | 🟡 Alto | M (2-4 días) |
| 4 | Tareas / recordatorios por contacto | 🟡 Medio | S (1-2 días) |
| 5 | Notas internas + adjuntos en conversación | 🟡 Medio | S (1 día) |
| 6 | Reportes exportables (CSV/Excel) | 🟢 Medio | S (1-2 días) |
| 7 | Plantillas rápidas por asesor | 🟢 Bajo | XS (4-6 hs) |
| 8 | Análisis de conversaciones con IA (sentimiento, abandono, intents fallidos) | 🟡 Medio | M (3-5 días) |

---

## Plan priorizado

```
Fase 1 (4-6 semanas) — Operación humana
  ├── #1 Bandeja del asesor          ← desbloquea la operación
  ├── #2 Ficha 360°                  ← lugar al que llega el asesor desde la bandeja
  ├── #5 Notas + adjuntos            ← se monta dentro de la ficha
  └── #4 Tareas + recordatorios      ← cierra el ciclo cuando humano debe seguir

Fase 2 (2-3 semanas) — Visibilidad
  ├── #3 Dashboard de control        ← ya hay actividad real para medir
  ├── #6 Reportes exportables        ← se conectan a las queries del dashboard
  └── #7 Plantillas por asesor       ← QoL para acelerar atención

Fase 3 (3-4 semanas) — Inteligencia
  └── #8 Análisis con IA             ← ya hay volumen de conversaciones para analizar
```

**Por qué este orden:** sin bandeja (#1) no hay flujo de trabajo humano; sin ficha (#2) la bandeja no tiene a dónde "saltar"; sin actividad medible (#1+#2 corriendo) los dashboards (#3) están vacíos; análisis con IA (#8) requiere histórico para ser útil.

---

## Detalle por iniciativa

### #1 · Bandeja del asesor (inbox unificado)

**Problema.** Hoy un asesor que recibe una conversación derivada por handoff no tiene una pantalla propia para trabajar: tiene que buscar el chat manualmente. No hay vista "lo que me toca ahora".

**Solución.** Una pantalla `/crm/bandeja/` que muestre, agrupado en pestañas:

- **Pendientes de mí** — `ConversacionWhatsApp` asignadas a `request.user` con último mensaje del cliente sin respuesta
- **Sin asignar** — derivadas por handoff o sin agente, esperando ser tomadas
- **En SLA crítico** — esperando respuesta hace > X minutos (umbral por sesión)
- **Mis tareas** — recordatorios pendientes (modelo nuevo, ver #4)

Cada fila muestra: avatar contacto, nombre, último mensaje (preview), canal (icono), depto/etapa pipeline, tiempo esperando, etiquetas, botón "abrir".

**Cómo se conecta con lo existente.**

- Lee de `ConversacionWhatsApp` (filtra por `agente_asignado`, `estado`, `ultimo_mensaje_at`)
- Usa `HistorialAsignacion` para detectar quién la tomó
- Cruza con `ConversacionEnPipeline` para mostrar etapa
- Usa `EtiquetaContacto` para badges
- Usa `Tarea` (modelo nuevo, ver #4) para la pestaña "mis tareas"
- Polling cada N segundos o WebSocket si hay infra ASGI

**Modelos nuevos.** Ninguno (puro queries sobre lo existente). Solo agregar un campo `sla_respuesta_minutos` en `SesionWhatsApp` si no existe ya.

**Endpoints nuevos.**
```
GET  /crm/bandeja/                           → render full page
GET  /crm/bandeja/?action=listado&tab=mias   → JSON con listado paginado
POST /crm/bandeja/?action=tomar&conv_id=X    → asigna a request.user
```

**Esfuerzo:** M (3-5 días).

---

### #2 · Ficha 360° del contacto

**Problema.** El dato del cliente vive desperdigado: identidad en `Contacto`, mensajes en `MensajeWhatsApp`, etapa en `ConversacionEnPipeline`, etiquetas en `EtiquetaContacto`, etc. Asesor pierde tiempo navegando.

**Solución.** Pantalla `/crm/contacto/<id>/` con layout de 3 columnas:

- **Izquierda (sticky):** datos del contacto, foto, número, etiquetas, etapa pipeline actual, asesor asignado, última actividad. Acciones rápidas: editar, etiquetar, mover de etapa, agregar tarea.
- **Centro (ancho):** timeline con tabs:
  - **Conversación** — chat completo (mensajes WhatsApp/IG/Messenger en orden cronológico, con burbujas tipo WA)
  - **Notas internas** — notas que no se envían al cliente (modelo nuevo, ver #5)
  - **Tareas** — recordatorios (modelo nuevo, ver #4)
  - **Archivos** — adjuntos (modelo nuevo, ver #5)
  - **Historial** — eventos del pipeline (`HistorialEtapaPipeline`), asignaciones (`HistorialAsignacion`), feedback bot, etc.
- **Derecha:** caja para enviar mensaje (con dropdown de plantillas rápidas, attach archivo) + métricas del contacto (mensajes totales, primera/última interacción, conversion rate si aplicable).

**Cómo se conecta con lo existente.**

- `Contacto` + `PerfilContacto` → datos de la columna izquierda
- `ConversacionWhatsApp` + `MensajeWhatsApp` → timeline central pestaña "Conversación"
- `ConversacionEnPipeline` + `HistorialEtapaPipeline` → estado y movimientos de pipeline
- `EtiquetaContacto` → badges
- `HistorialAsignacion` → quién atendió
- `FeedbackMensajeBot` → reseñas del bot
- Modelos nuevos: `NotaContacto`, `TareaContacto`, `ArchivoContacto` (ver #4 y #5)

**Modelos nuevos.** Solo los descritos en #4 y #5.

**Endpoints nuevos.**
```
GET  /crm/contacto/<id>/                          → render full page
GET  /crm/contacto/<id>/?action=timeline&tab=X    → JSON paginado del tab
POST /crm/contacto/<id>/?action=enviar_mensaje    → envía mensaje al canal correcto
POST /crm/contacto/<id>/?action=mover_etapa       → cambia etapa pipeline
POST /crm/contacto/<id>/?action=etiquetar         → toggle etiqueta
```

**Esfuerzo:** M (3-5 días) + 1-2 días por cada modelo nuevo de #4 y #5.

---

### #3 · Dashboard de control ejecutivo

**Problema.** Sin métricas agregadas, las decisiones operativas se toman a ciegas. El usuario lo llama "control": visibilidad de qué está pasando.

**Solución.** Pantalla `/crm/dashboard/` con widgets:

- **KPIs top:** conversaciones nuevas hoy, % respondidas, tiempo respuesta promedio, conversion rate (cerrado-ganado / total)
- **Volumen por canal** (barras WhatsApp/IG/Messenger/Voz, últimos 30 días)
- **Embudo de pipeline** (conteo por `EtapaPipeline`)
- **SLA tracker** — % de conversaciones respondidas dentro del umbral
- **Ranking de asesores** — atendidas, tiempo promedio respuesta, ganadas
- **Top intents fallidos del bot** — basado en `FeedbackMensajeBot` con thumb_down
- **Consumo IA** — tokens últimos 30 días, costo estimado, top modelos (lee `ConsumoTokenIA`)
- **Alertas activas** — `AlertaConsumoIA` no resueltas

Filtros globales: rango de fechas, canal, sesión, depto.

**Cómo se conecta con lo existente.**

- `EstadisticasConversacion` (existe ya, hay que ver qué guarda)
- `ConversacionWhatsApp` + `MensajeWhatsApp` con agregaciones (Count, Avg de tiempos)
- `ConversacionEnPipeline` agrupado por etapa
- `HistorialAsignacion` para tiempos de respuesta
- `ConsumoTokenIA`, `AlertaConsumoIA`
- `FeedbackMensajeBot` para top intents fallidos

**Modelos nuevos.** Idealmente ninguno, pero conviene agregar una tabla **denormalizada diaria** `MetricaDiaria(fecha, sesion, canal, conversaciones_nuevas, respondidas, tiempo_promedio_respuesta, ganadas, perdidas, tokens_ia, costo_estimado)` poblada por un cron job (#3.5). Sin esto, el dashboard pega queries de agregación pesadas en cada render.

**Endpoints nuevos.**
```
GET  /crm/dashboard/                          → render full page
GET  /crm/dashboard/?action=widget&w=kpis&...  → JSON del widget X
GET  /crm/dashboard/?action=export&w=embudo    → CSV del widget
```

**Esfuerzo:** M (2-4 días) + 0.5 día para el cron de denormalización.

---

### #4 · Tareas y recordatorios por contacto

**Problema.** Cuando el bot termina y el humano debe seguir (ej: "llamar mañana 11am", "enviar cotización"), no hay registro estructurado. Queda en la cabeza del asesor o en notas sueltas.

**Solución.** Modelo `TareaContacto` + UI dentro de la ficha 360 + pestaña "Mis tareas" en la bandeja.

```python
class TareaContacto(ModeloBase):
    contacto = ForeignKey(Contacto, on_delete=CASCADE)
    conversacion = ForeignKey(ConversacionWhatsApp, null=True, blank=True)  # opcional
    titulo = CharField(max_length=200)
    descripcion = TextField(blank=True)
    asignada_a = ForeignKey(Usuario, on_delete=PROTECT)
    vence_at = DateTimeField()
    completada_at = DateTimeField(null=True, blank=True)
    creada_por = ForeignKey(Usuario, related_name='+', on_delete=PROTECT)
    prioridad = CharField(choices=[('baja','Baja'),('media','Media'),('alta','Alta')], default='media')
```

**Cómo se conecta.**
- Listada en bandeja (#1) y en ficha 360 (#2)
- Cron job que envía notificación cuando vence (usar `seguridad.Notificacion`)
- Posible action en `AccionFinConversacion` para crear tarea automáticamente al cerrar

**Esfuerzo:** S (1-2 días).

---

### #5 · Notas internas + adjuntos en conversación

**Problema.** Asesor necesita registrar contexto interno ("cliente quiere descuento", "ya cotizamos vía mail") sin que el cliente lo vea, y subir archivos relacionados (foto del producto, ID escaneada, cotización PDF).

**Solución.** Dos modelos nuevos:

```python
class NotaContacto(ModeloBase):
    contacto = ForeignKey(Contacto, on_delete=CASCADE)
    conversacion = ForeignKey(ConversacionWhatsApp, null=True, blank=True)
    texto = TextField()
    autor = ForeignKey(Usuario, on_delete=PROTECT)
    # Visible solo para el equipo, NUNCA se envía al cliente

class ArchivoContacto(ModeloBase):
    contacto = ForeignKey(Contacto, on_delete=CASCADE)
    conversacion = ForeignKey(ConversacionWhatsApp, null=True, blank=True)
    archivo = FileField(upload_to='contactos/%Y/%m/')
    nombre_original = CharField(max_length=255)
    mime_type = CharField(max_length=100)
    subido_por = ForeignKey(Usuario, on_delete=PROTECT)
    es_interno = BooleanField(default=True)  # True=solo equipo / False=enviado al cliente
```

**Cómo se conecta.**
- Pestañas en la ficha 360 (#2)
- Aparecen en el timeline mezclado con mensajes (con badge "nota interna" diferenciado)

**Esfuerzo:** S (1 día).

---

### #6 · Reportes exportables

**Problema.** Auditoría externa (gerencia, legal, contabilidad) necesita CSV/Excel de conversaciones, leads, consumo IA. Hoy hay que pedírselo a TI.

**Solución.** Endpoints `?action=export&...` que devuelvan CSV con respuestas streaming (no cargar todo en memoria):

- `/crm/contactos/?export=csv&...filtros` → contactos con etapa, etiquetas, último mensaje
- `/crm/conversaciones/?export=csv&...` → conversaciones con timestamps + agente
- `/crm/dashboard/?action=export&w=consumo_ia` → consumo IA por día/modelo

**Cómo se conecta.** Solo lectura sobre modelos existentes.

**Esfuerzo:** S (1-2 días).

---

### #7 · Plantillas de respuesta rápida por asesor

**Problema.** `MenuRapidoSesion` existe pero (a confirmar) parece atado a la sesión, no al asesor. Cada asesor debería poder tener sus propias plantillas.

**Solución.** Validar si `MenuRapidoSesion` ya soporta esto. Si no, agregar:

```python
class PlantillaRapidaUsuario(ModeloBase):
    usuario = ForeignKey(Usuario, on_delete=CASCADE)
    atajo = CharField(max_length=20)  # ej: "/saludo"
    contenido = TextField()
    veces_usada = PositiveIntegerField(default=0)
```

UI: en la caja de envío de mensaje (en ficha 360 + bandeja) un dropdown que muestra plantillas matcheando lo que el asesor está escribiendo.

**Esfuerzo:** XS (4-6 hs).

---

### #8 · Análisis de conversaciones con IA

**Problema.** Tenés histórico de conversaciones pero no hay insights estructurados sobre qué pasa.

**Solución.** Job nightly que toma N conversaciones del día anterior y las pasa por LLM para extraer:

- **Sentimiento** (-1 a 1) y categoría (positivo/neutro/negativo/urgente)
- **Resumen** ejecutivo de la conversación
- **Intent principal** detectado (consulta precio, soporte técnico, queja, etc.)
- **Si abandonó el flujo del bot**, en qué nodo (cruzar con `EstadoFlujoChatbot`)
- **Topics** (tags semánticos: "precio", "envío", "garantía")

```python
class AnalisisConversacionIA(ModeloBase):
    conversacion = OneToOneField(ConversacionWhatsApp, on_delete=CASCADE)
    sentimiento_score = FloatField()  # -1 a 1
    sentimiento_categoria = CharField(...)
    resumen = TextField()
    intent_principal = CharField(max_length=80)
    abandono_nodo = ForeignKey(OpcionDepartamentoChatBot, null=True, blank=True)
    topics = JSONField(default=list)
    tokens_consumidos = IntegerField()
    apikey_usada = ForeignKey(ApiKeyIA, null=True, blank=True)
    fecha_analisis = DateTimeField()
```

**Cómo se conecta.**
- Insumo del dashboard (#3): heatmap de sentimiento, top intents, abandono por nodo
- Reportable en el CSV de conversaciones (#6)
- En la ficha 360 (#2), un badge "sentimiento" sobre cada conversación cerrada

**Esfuerzo:** M (3-5 días, depende de calibrar el prompt).

---

## Decisiones arquitectónicas

### A. Reutilizar `Contacto` como entidad CRM

Hoy `Contacto` está atado al concepto WhatsApp (campo `from_number` central). **No introducimos un modelo `Cliente` separado** — sería duplicación gratuita. En lugar de eso:

- Extendemos `PerfilContacto` con campos adicionales (RUC/CUIT, empresa, dirección, segmento) si hace falta
- La "ficha CRM" es la **vista** sobre `Contacto + PerfilContacto + relaciones`, no un modelo nuevo

**Tradeoff:** sigue acoplado al canal. Si en el futuro entran canales fuera de Meta (mail puro, web chat, llamada fría), habrá que abstraer. Por ahora innecesario.

### B. Pipeline ya está, solo hay que usarlo

`PipelineVenta` + `EtapaPipeline` + `ConversacionEnPipeline` cubren el kanban. Lo único que falta es la **UI que ya está parcialmente** (validar) y **acciones de cambio de etapa** desde la ficha 360 y bandeja.

### C. Notificaciones via `seguridad.Notificacion` (existe)

No reinventamos. Tareas vencidas, conversaciones en SLA crítico, alertas IA → todas usan `seguridad.Notificacion`.

### D. Dashboard sobre tabla denormalizada

Calcular agregaciones en cada render del dashboard mata la BD. Cron diario que pobla `MetricaDiaria` y el dashboard sólo lee de ahí. Para datos del día actual se hace agregación en vivo (volumen acotado).

### E. Multi-tenant: respetar `Empresa`

Todos los modelos nuevos (`TareaContacto`, `NotaContacto`, etc.) deben filtrar por empresa del usuario donde aplique, siguiendo el patrón existente. Si `seguridad.Empresa` ya scopa via `IntegranteEmpresa`, los nuevos modelos heredan ese scoping.

---

## Riesgos y dependencias

| Riesgo | Mitigación |
|---|---|
| Romper UI existente al cambiar `view_departamento_chatbot.py` o vistas de WA | Cada iniciativa es aditiva (rutas nuevas), no toca las existentes salvo agregar links |
| Migraciones bloqueantes en BD grande | Modelos nuevos son tablas nuevas (no ALTER sobre tablas con millones de filas). FKs `null=True` para no requerir backfill |
| Dashboard lento en BD grande | Tabla `MetricaDiaria` denormalizada (decisión D) |
| Costo IA del análisis nightly (#8) | Empezar con muestreo (10% conversaciones) o solo cerradas. Configurable |
| Notas/archivos internos enviados al cliente por error | `es_interno` flag por defecto `True`. UI con confirmación visual obvia |
| WebSockets para bandeja en tiempo real | Si el deploy no tiene ASGI, fallback a polling cada 15-30s |

---

## Próximo paso sugerido

Confirmar con el equipo:

1. **¿Arrancamos por #1 (Bandeja del asesor)?** — Es el unlock más grande.
2. **¿Hay restricción de no-modificar modelos existentes?** — Algunas iniciativas requieren campos opcionales sobre modelos actuales.
3. **¿Hay deploy ASGI o solo WSGI?** — Define si la bandeja usa WebSocket o polling.
4. **¿Multi-tenant activo hoy o es para más adelante?** — Define si los modelos nuevos llevan `empresa` desde el día 1.

Una vez resuelto, próximo doc: `update_crm_bandeja_spec.md` con wireframes, queries exactas y endpoints.
