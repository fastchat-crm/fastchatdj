# Estudio GoHighLevel — mapa, brechas y plan para fastchat

> Fecha: 2026-08-02. Fuentes: inventario de la API pública de GHL vía
> [GoHighLevel-MCP](https://github.com/mastanley13/GoHighLevel-MCP) (269 tools en 19 dominios),
> SDKs oficiales (`highlevel-api-python`, `highlevel-api-php`, `ghl-cli`, `ghl-sdk-examples`),
> documentación de producto 2026, y arquitectura de [EspoCRM](https://github.com/espocrm/espocrm)
> y [Twenty](https://github.com/twentyhq/twenty).
> Estado de fastchat según `.ai/docs/funcionalidades.md`.

---

## 1. Conclusión primero

**Fastchat no es una versión pobre de GoHighLevel: es un producto distinto que
ya lo supera en su propio terreno más difícil, y le falta casi toda la capa de
"plataforma de negocio" que GHL tiene alrededor.**

Donde fastchat está **por delante**: profundidad de mensajería multicanal
(WhatsApp con doble proveedor y capa anti-baneo propia, Instagram, Messenger,
TikTok, inbox de comentarios con reglas comentario→DM) y sobre todo el motor de
IA — RAG híbrido, tool-calling, humanización, auditor de agentes, FAQs
curables, trazas y control de consumo por token. GHL tiene "Conversation AI" y
"Voice AI" como features cerradas; fastchat tiene un motor de agentes
configurable con observabilidad real.

Donde fastchat está **muy por detrás**: no tiene modelo de datos extensible
(custom objects/fields), ni motor de automatización de propósito general, ni
nada del stack de monetización (facturación, productos, pagos, suscripciones),
ni constructor de funnels/sitios, ni multi-tenancy con facturación.

**La brecha no se cierra copiando 269 endpoints.** Se cierra con tres piezas
arquitectónicas que desbloquean el resto. Están en la Fase 1 del plan.

---

## 2. Superficie de GoHighLevel

### 2.1 API pública — 269 tools en 19 dominios

| Dominio | Tools | Qué cubre |
|---|---:|---|
| Invoices & Billing | 39 | Plantillas, facturas recurrentes, estimaciones, ciclo de vida completo, registro de pagos, numeración |
| Contact Management | 31 | CRUD, búsqueda, tags, tareas, notas, detección de duplicados, workflows, followers |
| Location Management | 24 | Sub-cuentas, tags, custom fields y values, plantillas, timezones |
| Messaging & Conversations | 20 | SMS/email, búsqueda de conversaciones, grabaciones y transcripciones de llamadas, typing indicators |
| Payments | 20 | Providers, órdenes, transacciones, suscripciones, cupones, gateways custom |
| Store Management | 18 | Zonas y tarifas de envío, carriers, configuración de tienda |
| Social Media Management | 17 | Publicación en Google Business, Facebook, Instagram, LinkedIn, Twitter, TikTok; bulk CSV |
| Calendar & Appointments | 14 | Grupos de calendario, disponibilidad, CRUD de citas, bloqueo de horarios |
| Opportunity Management | 10 | Pipelines, etapas, CRUD, estados, followers, upsert inteligente |
| Products | 10 | CRUD, precios, inventario, colecciones |
| Association Management | 10 | Relaciones entre objetos arbitrarios |
| Custom Objects | 9 | Schemas y records definidos por el usuario |
| Custom Fields V2 | 8 | Campos y carpetas por objeto |
| Blog | 7 | Posts, sitios, autores, categorías, slugs |
| Email Marketing | 5 | Campañas y plantillas |
| Media Library | 3 | Búsqueda, upload, borrado |
| Surveys | 2 | Encuestas y respuestas |
| Workflows | 1 | Descubrimiento de workflows |
| Email Verification | 1 | Deliverability y riesgo |

### 2.2 Capa de producto que la API no muestra

- **Funnels y websites**: builder drag-and-drop de sitios completos y embudos.
- **Workflow builder visual**: triggers (formulario enviado, tag agregado, cita
  creada) → acciones (SMS, email, esperar N días, asignar vendedor). Es
  transversal a todo el CRM, no solo al chat.
- **Memberships y cursos**.
- **Reputation management**: pedido automático de reseñas post-cita, ruteo de
  reseñas negativas al inbox.
- **SaaS Mode / white-label**: revender la plataforma con marca propia,
  facturación por sub-cuenta, provisioning automático de clientes.
- **Snapshots**: clonar la configuración completa de una sub-cuenta a otra.
- **IA de producto**: Conversation AI, Voice AI, Content AI, Workflow AI.

---

## 3. Análisis de brechas

Leyenda: **★** fastchat está mejor · **=** paridad · **~** parcial · **✗** no existe

### 3.1 Donde fastchat gana

| Capacidad | GHL | fastchat | |
|---|---|---|---|
| Canales de mensajería | SMS, email, y redes vía integraciones | WhatsApp (Cloud API **+ Baileys no oficial**), Instagram DM, Messenger, TikTok, todos sobre el mismo motor | ★ |
| Anti-bloqueo WhatsApp | No aplica (usa proveedores oficiales) | Módulo propio: verificación de número, rampa de calentamiento, cuotas de contactos fríos, espaciado, manejo de 403/440/411/500 | ★ |
| Motor de IA conversacional | Conversation AI (caja cerrada) | Agentes configurables: RAG híbrido BM25+FAISS con umbral, Weaviate multi-tenant, tool-calling HTTP, humanización en burbujas, memoria RAG entre conversaciones | ★ |
| Observabilidad de IA | — | Trazas por etapa, consumo y costo por token, alertas, auditor que propone mejoras, evaluación con juez LLM | ★ |
| Inbox de comentarios sociales | Publicación, no moderación conversacional | Comentarios IG/FB/TikTok con respuesta pública, ocultar, private reply y **reglas comentario→DM** | ★ |
| Chatbot determinista | Workflows genéricos | Motor de flujos tipo n8n con matching sin acentos, timeout→handoff, anti-rewind | ★ |
| Asignación de asesores | Round-robin | Cadena de candidatos por carga y disponibilidad, con notificaciones | ★ |

### 3.2 Paridad o casi

| Capacidad | fastchat | |
|---|---|---|
| CRM de contactos | Contactos, etiquetas, segmentos guardados, importación | ~ falta detección de duplicados y campos custom |
| Pipeline de oportunidades | Kanban en `/crm/pipeline/` | = |
| Calendario y citas | App `agenda/` con recursos, servicios, horarios, excepciones, recordatorios | ~ falta disponibilidad pública y grupos de calendario |
| Campañas | Campañas masivas WhatsApp con throttle, tiers, opt-out, ROI CTWA | ~ solo WhatsApp; falta email marketing real |
| API pública | REST v1 con API key y rate limit + webservice IA | ~ superficie mucho menor |
| Multi-empresa | Modelo `Empresa` | ~ sin aislamiento fuerte ni facturación |

### 3.3 Lo que falta — ordenado por impacto

| # | Capacidad ausente | Por qué importa | Esfuerzo |
|---|---|---|---|
| 1 | **Custom objects y custom fields en runtime** | Es el cimiento. Sin esto cada vertical (inmobiliaria, clínica, concesionaria) exige tocar `models.py`. GHL tiene 9+8+10 tools solo para esto | Alto |
| 2 | **Motor de automatización transversal** | Hoy el motor de flujos vive dentro del chat. Falta trigger→acción sobre cualquier entidad: "cita cumplida → esperar 2 días → pedir reseña" | Alto |
| 3 | **Facturación, productos y pagos** | 39+20+10 = 69 tools en GHL, el bloque más grande de su API. Es lo que convierte un CRM en plataforma de negocio | Alto |
| 4 | **Email marketing** | Existe mailing masivo en `seguridad/` pero sin plantillas, segmentación ni métricas de campaña | Medio |
| 5 | **Formularios y encuestas** | Puerta de entrada de leads que hoy no existe; alimentaría los growth links que ya tenemos | Medio |
| 6 | **Publicación en redes** | Ya leemos posts y comentarios de IG/FB; publicar y programar es incremental sobre `meta/` | Medio-bajo |
| 7 | **Reputation management** | Muy alineado con lo que ya hay: cita cumplida → pedir reseña. Depende de (2) | Medio-bajo |
| 8 | **Funnels y websites** | Alto costo, baja diferenciación: hay builders open source integrables | Muy alto |
| 9 | **Memberships y cursos** | Vertical propio, evaluable aparte | Alto |
| 10 | **SaaS mode / white-label** | Depende de multi-tenancy real y facturación (1 y 3) | Alto |
| 11 | **Snapshots de configuración** | Clonar una cuenta lista para un cliente nuevo. Depende de (1) | Medio |
| 12 | **Media library, blog, email verification, store/shipping** | Complementarios | Bajo c/u |

---

## 4. Referencia de arquitectura

### 4.1 EspoCRM — metadata-driven

Backend PHP con REST + SPA. La lección aplicable: **las entidades, campos y
relaciones se describen en metadata JSON (con JSON Schema), no en código**. El
usuario crea entidades y campos custom sin tocar el core ni migrar a mano.
Backend con SOLID, DI e interfaces; sistema de extensiones que evita modificar
el núcleo.

**Qué copiar:** el modelo declarativo. Una tabla de definiciones + un motor que
las interpreta, en vez de una clase Django por entidad.

### 4.2 Twenty — code-first con SDK

TypeScript, NestJS + PostgreSQL + Redis + BullMQ, React con Jotai. Los objetos,
campos y vistas **se definen como código** con un SDK, se versionan junto al
repo y se publican como apps privadas al workspace.

**Qué copiar:** que la configuración del CRM sea versionable. Twenty resuelve
en Git lo que GHL resuelve con snapshots.

### 4.3 Cómo aterriza en Django

Las dos opciones reales para custom objects:

| Enfoque | Cómo | Pro | Contra |
|---|---|---|---|
| **EAV** (`ObjetoCustom` + `CampoCustom` + `ValorCampo`) | Tres tablas genéricas | Sin DDL en runtime, migraciones normales | Consultas caras, filtros y orden complicados |
| **JSONB por objeto** | Una tabla `RegistroCustom` con `datos JSONB` + índices GIN | Postgres 15 indexa y filtra JSONB bien; una sola tabla | Menos integridad referencial, validación en aplicación |

**Recomendación: JSONB.** Ya corremos PostgreSQL 15, el proyecto usa JSONB en
varios modelos, y evita la explosión de joins del EAV. El schema del objeto vive
en una tabla de metadata (como EspoCRM) y se valida en la capa de aplicación.

---

## 5. Plan por fases

### Fase 1 — Los cimientos (desbloquea todo lo demás)

**1.1 Objetos y campos custom**
- `ObjetoPersonalizado` (nombre, slug, ícono, perfil) y `CampoPersonalizado`
  (tipo, label, requerido, opciones, orden).
- `RegistroPersonalizado` con `datos JSONB` + índice GIN.
- Motor genérico de listado/form/detalle que interpreta la metadata y respeta
  las convenciones del proyecto (`ConsultasAjax`, `ModeloBase`, soft-delete).
- Campos custom sobre las entidades que ya existen (Contacto, Conversación,
  Cliente) — GHL los tiene en todas.

**1.2 Asociaciones**
- Tabla de relaciones entre registros de cualquier tipo, con etiqueta de rol.

**1.3 Motor de automatización transversal**
- `Automatizacion` (trigger + condiciones + acciones ordenadas) sobre eventos de
  dominio, no solo de chat: contacto creado, etiqueta agregada, cita cumplida,
  oportunidad ganada, formulario enviado.
- Reusar el editor visual que ya existe en `/crm/departamentos_chatbots/`.
- Ejecución en cron (ya hay infraestructura en `cron_jobs/`), con acción
  `esperar N días` persistida.

> Con 1.1 + 1.3 resueltos, las fases siguientes son incrementales.

### Fase 2 — Captación y monetización

**2.1 Formularios y encuestas** — builder simple, página pública, submit crea
Contacto y dispara automatización. Se integra con los growth links existentes.

**2.2 Email marketing** — plantillas, listas segmentadas (reusar
`SegmentoGuardado`), envío por lotes sobre el `core/email_config.py` ya
endurecido, métricas de apertura y clic.

**2.3 Productos, facturas y pagos** — `Producto`, `Factura` con estados,
`Pago`, integración con una pasarela. Es el bloque más grande de GHL y el que
convierte fastchat en plataforma de negocio.

### Fase 3 — Amplificación

**3.1 Publicación y programación en redes** — incremental sobre `meta/`, que ya
lee publicaciones de IG y FB.

**3.2 Reputation management** — pedido de reseña automático post-cita vía la
automatización de la Fase 1; reseñas negativas al inbox.

**3.3 Media library** — biblioteca central de archivos reutilizables.

### Fase 4 — Escala como plataforma

**4.1 Multi-tenancy real** — aislamiento fuerte por `Empresa`, no solo filtros.

**4.2 SaaS mode** — planes, límites por plan, facturación de sub-cuentas,
provisioning automático.

**4.3 Snapshots** — exportar/importar la configuración completa de una cuenta
(objetos custom, automatizaciones, agentes, plantillas).

### Fuera de alcance por ahora

**Funnels y websites**: mucho esfuerzo, poca diferenciación. Evaluar integrar un
builder open source antes que construirlo. **Memberships y cursos**: vertical
propio, decidir por demanda real de clientes.

---

## 6. Dónde ganamos, y cómo no perderlo

GHL es enorme en superficie pero superficial en cada cosa. La ventaja de
fastchat es **la profundidad en mensajería multicanal e IA**, y hay que
protegerla mientras se construye lo demás:

1. **Ningún vertical nuevo debe degradar el motor de IA.** El Centro de IA y la
   cascada de parámetros que acabamos de construir van en esa dirección.
2. **El anti-baneo es un diferenciador real.** GHL no puede ofrecer WhatsApp no
   oficial; nosotros sí, con red de seguridad.
3. **Las trazas y el control de consumo son argumento de venta.** Ningún
   competidor muestra qué le costó cada conversación.
4. **La IA debe atravesar cada feature nueva**, no quedar en el chat: escribir
   el email de campaña, redactar la descripción del producto, sugerir la
   automatización. Es lo que GHL llama Content AI y Workflow AI.

---

## 7. Siguiente paso concreto

Empezar por **1.1 (objetos y campos custom con JSONB)**. Es la pieza de la que
dependen 6 de las 12 brechas, y es la que hoy obliga a tocar código cada vez que
entra un cliente de un rubro nuevo.
