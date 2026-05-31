# Plan de trabajo y timeline — fastchat

> Doc vivo. Inicio: 2026-05-31. Sprints de 2 semanas.
> Basado en `estudio_proyecto.md` (auditoría + gaps competitivos).
> Marcá `[x]` al completar. Estados: ☐ pendiente · 🔄 en curso · ✅ hecho · ⏸ pausado.

---

## Leyenda de prioridad / esfuerzo
- **P0** crítico (bloquea venta/seguridad) · **P1** alto impacto · **P2** mejora · **P3** nice-to-have
- Esfuerzo: **S** (≤2 días) · **M** (3-5 días) · **L** (1-2 semanas) · **XL** (>2 semanas)

---

## Timeline general (vista macro)

| Fase | Objetivo | Sprints | Fechas aprox. |
|---|---|---|---|
| **0. Higiene técnica** | Seguridad prod + base estable | S1 | 2026-05-31 → 2026-06-13 |
| **1. Pulido de inbox** | Productividad de agente | S2-S3 | 2026-06-14 → 2026-07-11 |
| **2. Compliance + campañas** | Opt-out, drip, SLA | S4-S5 | 2026-07-12 → 2026-08-08 |
| **3. SaaS (tenancy + billing)** | Habilita venta multi-cliente | S6-S9 | 2026-08-09 → 2026-10-03 |
| **4. Expansión** | Canales + API + monitoreo | S10-S12 | 2026-10-04 → 2026-11-14 |

---

## Fase 0 — Higiene técnica (Sprint 1)
> Antes de construir features nuevas, cerrar riesgos de producción.

- [ ] **P0/S** Mover secretos de `credenciales.json` a variables de entorno / vault.
- [ ] **P0/S** Sacar SendGrid API key del settings en claro.
- [ ] **P0/S** Eliminar email hardcodeado `COTIZADOR_DEBUG_EMAIL` → config en settings/BD.
- [ ] **P1/M** Integrar monitoreo de errores (Sentry) + health check endpoint.
- [ ] **P1/M** Auditar listados con `select_related`/`prefetch_related` (N+1 en conversaciones/contactos).
- [ ] **P2/S** Backoff exponencial en `WebhookSaliente` (reintentos + expiración).
- [ ] **P2/M** Suite mínima de tests (motor de flujo, webhook Meta, asignación).

**Entregable:** sistema seguro para producción + visibilidad de errores.

---

## Fase 1 — Pulido de inbox (Sprints 2-3)
> Rápido, alto impacto percibido por agentes.

### 1.1 Detección de colisión
- [ ] **P1/M** Marcar "agente X está viendo/respondiendo" en conversación (lock visible).
- [ ] **P1/S** Broadcast WebSocket del lock al resto de agentes.
- [ ] **P2/S** Liberar lock por inactividad / al cerrar pestaña.

### 1.2 Snooze + estados
- [ ] **P1/M** Estado de conversación: agregar `pendiente` / `resuelto` (hoy solo activo/cerrado).
- [ ] **P1/M** Snooze con `snooze_until` + cron que reabre.
- [ ] **P2/S** Filtros de inbox por estado.

### 1.3 Respuestas rápidas globales
- [ ] **P1/M** Biblioteca global de atajos (no solo por sesión) con disparo `/atajo`.
- [ ] **P2/S** Variables en atajos (`{{contacto.nombre}}`).

### 1.4 Campos personalizados de contacto
- [ ] **P1/L** Modelo de campos custom (definición + valores por contacto).
- [ ] **P2/M** UI para definir y editar campos en ficha de contacto.

**Entregable:** inbox a nivel Chatwoot/Wati en productividad básica.

---

## Fase 2 — Compliance + campañas (Sprints 4-5)

### 2.1 Opt-out / consentimiento
- [ ] **P0/M** Flag de consentimiento + opt-out por contacto + fecha/origen.
- [ ] **P0/S** Footer "responde BAJA para no recibir más" en campañas.
- [ ] **P1/S** Excluir opt-outs automáticamente de audiencias.

### 2.2 Drip / secuencias
- [ ] **P1/L** Secuencias de mensajes temporizadas (trigger → pasos con delay).
- [ ] **P2/M** Condiciones de salida (respondió / clasificó).

### 2.3 SLA accionable
- [ ] **P1/M** Umbrales de SLA por departamento/sesión.
- [ ] **P1/M** Alertas + escalamiento automático al superar SLA.

**Entregable:** campañas legales + automatización temporal + SLA real.

---

## Fase 3 — SaaS: multi-tenancy + billing (Sprints 6-9)
> Bloqueante para vender como SaaS multi-cliente.

### 3.1 Multi-tenancy
- [ ] **P0/XL** Modelo `Organizacion` y enlazar `Empresa`/`IntegranteEmpresa` ya existentes.
- [ ] **P0/XL** `tenant_id` en modelos principales + filtrado por tenant en todas las queries.
- [ ] **P0/L** Row-level security / scoping en `ConsultasAjax` y vistas.
- [ ] **P1/M** Aislamiento de media por tenant.
- [ ] **P1/M** Roles a nivel organización (owner/admin/agente).

### 3.2 Billing
- [ ] **P0/L** Modelos de Plan + Suscripción + estado.
- [ ] **P0/L** Integración Stripe (checkout + webhooks de pago).
- [ ] **P1/M** Metering de uso (mensajes/contactos/sesiones) por tenant.
- [ ] **P1/M** Cuotas + bloqueo/aviso al superar plan.
- [ ] **P2/M** Facturas/recibos.

### 3.3 Onboarding
- [ ] **P1/L** Wizard de alta (crear org → conectar primera sesión WA → primer flujo).
- [ ] **P2/M** Estado de "setup completo" + guía contextual.

**Entregable:** producto vendible como SaaS multi-cliente.

---

## Fase 4 — Expansión (Sprints 10-12)

### 4.1 Canales
- [ ] **P1/L** Widget web / live chat embebible.
- [ ] **P2/L** Canal email.
- [ ] **P3/M** Canal SMS.

### 4.2 API e integraciones
- [ ] **P1/M** Documentación pública de API (OpenAPI/Swagger).
- [ ] **P2/L** Conectores Zapier/Make.
- [ ] **P3/L** Conectores HubSpot/Salesforce.

### 4.3 Plataforma
- [ ] **P1/L** Cron distribuido (Celery + Beat) reemplazando scripts por SO.
- [ ] **P2/M** i18n real (sacar hardcode `es-ec`/timezone).
- [ ] **P3/L** Completar voz (STT/TTS real).

**Entregable:** plataforma multicanal extensible y escalable.

---

## Backlog sin asignar a fase
- [ ] Deals/oportunidades como entidad propia (más allá del pipeline sobre conversación).
- [ ] Reportes exportables PDF + reportes programados por email.
- [ ] Sticky assignment (no reasignar si el agente sigue activo).
- [ ] TTL / limpieza de media antigua.
- [ ] Rate-limiting de login.

---

## Bitácora de avances
> Registrar aquí cada cierre relevante (fecha — qué — quién).

- 2026-05-31 — Creado el estudio del proyecto (`estudio_proyecto.md`) y este plan.
