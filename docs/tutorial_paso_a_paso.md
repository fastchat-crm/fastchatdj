# Tutorial paso a paso · FastChat DJ

> Guía práctica para aprender a usar la plataforma de principio a fin, con **casos de uso reales** por tipo de negocio. Cada caso tiene el setup completo, los textos exactos que vas a usar y los tiempos estimados.

---

## Índice

- [Parte 1 · Primer arranque (45 min)](#parte-1--primer-arranque-45-min)
- [Parte 2 · Tu primera conversación con IA (20 min)](#parte-2--tu-primera-conversación-con-ia-20-min)
- [Parte 3 · Organizar contactos con etiquetas (10 min)](#parte-3--organizar-contactos-con-etiquetas-10-min)
- [Parte 4 · Armar el pipeline de ventas (15 min)](#parte-4--armar-el-pipeline-de-ventas-15-min)
- [Parte 5 · Lanzar una campaña masiva (20 min)](#parte-5--lanzar-una-campaña-masiva-20-min)
- [Parte 6 · Atribución Meta Ads (30 min)](#parte-6--atribución-meta-ads-30-min)
- [Parte 7 · Agregar Instagram + Messenger (20 min)](#parte-7--agregar-instagram--messenger-20-min)
- [Parte 8 · Casos de uso por tipo de negocio](#parte-8--casos-de-uso-por-tipo-de-negocio)
  - [8.1 · E-commerce: tienda online](#81--e-commerce-tienda-online)
  - [8.2 · Restaurante / delivery](#82--restaurante--delivery)
  - [8.3 · Inmobiliaria](#83--inmobiliaria)
  - [8.4 · Clínica médica / estética](#84--clínica-médica--estética)
  - [8.5 · Instituto educativo](#85--instituto-educativo)
  - [8.6 · Agencia de servicios (marketing, contable, legal)](#86--agencia-de-servicios-marketing-contable-legal)
  - [8.7 · Empresa B2B con equipo comercial](#87--empresa-b2b-con-equipo-comercial)
- [Parte 9 · Operación diaria: el día a día de un agente](#parte-9--operación-diaria-el-día-a-día-de-un-agente)
- [Parte 10 · Reportes y KPIs](#parte-10--reportes-y-kpis)
- [Solución de problemas](#solución-de-problemas)

---

## Parte 1 · Primer arranque (45 min)

Lo que consigues al final: servidor corriendo, sesión WhatsApp conectada, IA respondiendo mensajes básicos.

### 1.1 · Instalar el servidor

```bash
# Dependencias del sistema
# Windows: asegúrate de tener Python 3.8+, PostgreSQL, Redis y wkhtmltopdf instalados

# Clonar o actualizar
git clone <tu-repo> fastchatdj
cd fastchatdj

# Entorno virtual + dependencias
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate    # Linux/Mac
pip install -r requirements.txt
```

### 1.2 · Configurar credenciales

Copia el template y edítalo:

```bash
cp credenciales_template.json credenciales.json
```

Edita `credenciales.json` con tus valores reales:

```json
{
  "POSTGRES_HOST":     "localhost",
  "POSTGRES_PORT":     5432,
  "POSTGRES_DBNAME":   "fastchatdj",
  "POSTGRES_PASSWORD": "tu-password",
  "SECRET_KEY":        "genera-una-con-secrets.token_urlsafe(50)",
  "DEBUG":             true,
  "DOMINIO_GENERAL":   "localhost:8000",
  "WINDOWS":           true,
  "REDIS_HOST":        "localhost",
  "REDIS_PORT":        6379,
  "WHATSAPP_API_URL":  "http://localhost:3000",
  "NODE_SECRET_KEY":   "una-clave-compartida-con-node",
  "EMAIL_HOST_USER":     "tu@correo.com",
  "EMAIL_HOST_PASSWORD": "tu-password-smtp",
  "SENDGRID_API_KEY":    "SG.xxx",
  "WKHTMLTOPDF_CMD":     "C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe",
  "ID_GRUPO_CLIENTE":    2,
  "CACHES_REDIS":        true,
  "USE_SSL":             false
}
```

### 1.3 · Base de datos + superusuario

```bash
python manage.py migrate
python manage.py createsuperuser
# Te pide username, email, password
```

### 1.4 · Levantar el servidor

**Opción A (sin WebSockets — solo para probar):**
```bash
python manage.py runserver
```

**Opción B (recomendado, incluye chat en tiempo real):**
```bash
daphne -b 0.0.0.0 -p 8000 fastchatdj.asgi:application
```

Abre **http://localhost:8000** y haz login con tu superusuario.

### 1.5 · Levantar el servicio Node.js (Baileys)

Si usas WhatsApp no oficial (Baileys), necesitas el servicio Node corriendo en paralelo:

```bash
# En otro terminal, dentro del repo Node
cd ../fastchat-node    # o como se llame
npm install
NODE_SECRET_KEY="la-misma-clave-de-credenciales.json" npm start
```

Si vas a usar **solo Meta Cloud API** (oficial), este paso es opcional.

### 1.6 · Conectar tu primera sesión WhatsApp

**Ruta:** `/whatsapp/sesiones/`

**Opción A — Baileys (gratis, no oficial):**
1. Clic en **Nueva sesión** (o botón `+`).
2. Escanea el QR con tu teléfono (WhatsApp → Dispositivos vinculados → Vincular dispositivo).
3. Espera a que el estado pase a **Conectado**.

**Opción B — Meta Cloud API (oficial, recomendado para producción):**
1. Sigue la guía [`docs/meta_setup.md`](meta_setup.md) para obtener tu `phone_number_id`, `waba_id` y `access_token`.
2. Desde `/whatsapp/sesiones/`, crea una sesión Meta, pega las credenciales.
3. Configura el webhook en Meta Developer Portal apuntando a `https://tu-dominio.com/whatsapp/meta_webhook/`.
4. Clic en **Verificar conexión con Meta** para validar.

**Listo — ya tienes WhatsApp conectado.**

---

## Parte 2 · Tu primera conversación con IA (20 min)

Lo que consigues: un bot que responde con info de tu negocio usando Gemini/OpenAI.

### 2.1 · Crear un perfil de negocio

**Ruta:** `/crm/perfil-negocio/`

Rellena:
- **Nombre del negocio:** "Tienda Camisetas Quito"
- **Descripción:** "Vendemos camisetas estampadas con diseños únicos. Envíos a todo Ecuador."
- **Horario:** "Lunes a viernes 9am-6pm"
- **Dirección:** "Av. 10 de Agosto N32-45"
- **Métodos de pago:** "Transferencia, tarjeta, efectivo contra entrega"

### 2.2 · Configurar una API Key de IA

**Ruta:** `/crm/api-keys/` (o similar, depende del proyecto)

1. **Nueva API Key**
2. Proveedor: `gemini` (gratis 1500 req/día) o `openai`
3. Pega tu API key.

Dónde conseguirla:
- Gemini: https://aistudio.google.com/app/apikey (gratis)
- OpenAI: https://platform.openai.com/api-keys (requiere saldo)

### 2.3 · Crear un agente IA

**Ruta:** `/crm/agentes-ia/`

- **Nombre:** "Vendedor Camisetas"
- **Perfil:** selecciona el que creaste en 2.1
- **API Key:** la que creaste en 2.2
- **Prompt template:** deja el default (en español, ya viene configurado)
- **Contexto estático** (opcional): copia ahí un FAQ de 5-10 preguntas comunes:

```
Preguntas frecuentes:

¿Hacen envíos fuera de Quito?
Sí, enviamos a todo Ecuador por Servientrega. El costo depende de la ciudad.

¿Cuánto demora el envío?
2-3 días hábiles en Quito, 3-5 días al resto del país.

¿Tienen talla L?
Tenemos tallas XS, S, M, L, XL y XXL en todos los modelos.

¿Puedo pagar contra entrega?
Sí, solo en Quito. Para el resto del país requerimos transferencia previa.

¿Dónde puedo ver el catálogo?
En nuestro Instagram @camisetasquito o en el sitio web camisetasquito.com
```

### 2.4 · Asignar el agente a la sesión

**Ruta:** `/whatsapp/sesiones/` → edita tu sesión

- **Modo del bot:** `Agente IA`
- **Agente IA:** "Vendedor Camisetas"
- **Mensaje de bienvenida:** "¡Hola! 👋 Bienvenido a Camisetas Quito. ¿En qué puedo ayudarte?"
- **Minutos de sesión:** 60 (cuánto tiempo una conversación sigue "abierta")

Guarda.

### 2.5 · Probar

Desde otro teléfono, mándale un WhatsApp a tu número. El bot debería responder usando el contexto del negocio.

Si no responde:
1. Ve a `/whatsapp/trazas/` — busca por número → verás el pipeline paso a paso y dónde falló.
2. Revisa que la API key tenga créditos.
3. Asegúrate que la sesión esté **Conectada**.

---

## Parte 3 · Organizar contactos con etiquetas (10 min)

**Ruta:** `/whatsapp/etiquetas/`

### 3.1 · Etiquetas sugeridas según tu negocio

**Para cualquier negocio:**
- `VIP` (rojo) · clientes frecuentes o de alto ticket
- `Newsletter OK` (verde) · autorizó recibir promociones
- `No molestar` (gris) · pidió no recibir más mensajes
- `Lead caliente` (naranja) · interesado reciente

**Extras por rubro:**

| Rubro | Etiquetas útiles |
|---|---|
| E-commerce | `Compró 1 vez`, `Compró 3+`, `Abandonó carrito`, `Devolución pendiente` |
| Restaurante | `Cliente habitual`, `Delivery`, `Reserva`, `Alergias` |
| Inmobiliaria | `Comprador`, `Vendedor`, `Arriendo`, `Presupuesto alto`, `Solo Quito Norte` |
| Clínica | `Primera consulta`, `Seguimiento`, `Paciente crónico`, `Estética`, `Médico` |
| Instituto | `Interesado curso X`, `Matriculado`, `Graduado`, `Exalumno` |

### 3.2 · Aplicar etiquetas

**Opción A · Manual desde la conversación:** abre una conversación → sección "Etiquetas" → marca las que apliquen.

**Opción B · Bulk via API** (ideal para cargar 500 contactos desde Excel):

```bash
curl -X POST http://localhost:8000/whatsapp/api/v1/etiquetas/aplicar/ \
     -H "X-API-Key: TU_NODE_SECRET_KEY" \
     -H "Content-Type: application/json" \
     -d '{"contacto_ids":[12,34,56], "etiqueta_ids":[1,3]}'
```

---

## Parte 4 · Armar el pipeline de ventas (15 min)

**Ruta:** `/whatsapp/pipeline/`

### 4.1 · Crear el pipeline

Clic en **Nuevo pipeline** → nombre: "Ventas 2026" → Crear.

### 4.2 · Definir las etapas

Dale clic a **Agregar etapa** por cada columna. Para una tienda típica:

| Etapa | Color | Probabilidad | ¿Ganado? | ¿Perdido? |
|---|---|---|---|---|
| Nuevo contacto | gris `#6c757d` | 10% | No | No |
| Interesado | azul `#0dcaf0` | 30% | No | No |
| Cotización enviada | amarillo `#ffc107` | 50% | No | No |
| Negociación | naranja `#fd7e14` | 70% | No | No |
| **Cerrado ganado** | verde `#198754` | 100% | **Sí** ⭐ | No |
| Perdido | rojo `#dc3545` | 0% | No | **Sí** |

⭐ Las etapas con `es_ganado=True` disparan automáticamente **Purchase** a Meta CAPI cuando mueves una tarjeta ahí.

### 4.3 · Agregar conversaciones al pipeline

Desde una conversación activa: botón **Agregar al pipeline** → selecciona etapa inicial → pon `valor_estimado` (lo que esperas vender) y `moneda`.

### 4.4 · Mover tarjetas en el Kanban

- Arrastra la tarjeta entre columnas para mover el deal.
- Cada movimiento queda registrado en `HistorialEtapaPipeline` (visible en admin) → útil para medir funnel.

---

## Parte 5 · Lanzar una campaña masiva (20 min)

**Ruta:** `/whatsapp/campanas/`

### 5.1 · Preparar

**Requisitos:**
1. Tener al menos una **etiqueta** aplicada a los contactos objetivo (ej. `Newsletter OK`).
2. Si vas a usar Meta Cloud API fuera de la ventana 24h, necesitas una **plantilla aprobada** en Meta (ver `/whatsapp/plantillas/`).
3. El cron `ejecutar_campanas.py` debe estar corriendo.

### 5.2 · Configurar el cron

**Linux (crontab -e):**
```cron
* * * * * cd /ruta/fastchatdj && /ruta/.venv/bin/python cron_jobs/ejecutar_campanas.py >> /var/log/fastchat-campanas.log 2>&1
```

**Windows (Task Scheduler):**
1. Abre **Programador de tareas**.
2. Crear tarea → Desencadenador: diario, cada 1 minuto indefinidamente.
3. Acción: iniciar programa
   - Programa: `E:\DESARROLLO\FREELANCER\fastchat\fastchatdj\.venv\Scripts\python.exe`
   - Argumentos: `cron_jobs\ejecutar_campanas.py`
   - Iniciar en: `E:\DESARROLLO\FREELANCER\fastchat\fastchatdj`

### 5.3 · Crear la campaña

1. **Nueva campaña** →
   - Nombre: "Promo semana santa"
   - Sesión: tu sesión WhatsApp
   - Tipo: `texto`
   - Throttle: `20 msg/min` (seguro para Baileys; Meta permite más)
2. **Mensaje** (usa placeholders):
   ```
   Hola {nombre}, esta semana tenemos 30% de descuento
   en toda la tienda. Usa el código SS30 al momento
   de pagar. Solo hasta el domingo.
   ```
3. **Etiquetas a incluir:** `Newsletter OK`
4. **Etiquetas a excluir:** `No molestar`, `VIP` (si quieres tratarlos distinto)
5. **Canales permitidos:** `whatsapp` (o agrega IG/Messenger si ya los tienes)
6. Crear → queda en **borrador** con audiencia calculada.

### 5.4 · Lanzar

En el listado, botón **Enviar**. El cron arranca la campaña en el próximo tick (≤1 min).

### 5.5 · Monitorear

Clic en el ícono de lista → **Detalle** → verás:
- Progreso visual (% enviados).
- Tabla de últimos 200 envíos con estado (pendiente/enviado/fallido/respondido).
- Errores detallados.

### 5.6 · Tips de deliverability

- **WhatsApp Baileys:** nunca excedas 20 msg/min o te bloquean la cuenta.
- **Meta Cloud API:** respeta el tier (`TIER_1K`, `TIER_10K`, etc.) visible en `/whatsapp/sesiones/`.
- **Mensaje inicial masivo:** usa plantilla aprobada (`categoria=MARKETING`) — si no, Meta bloqueará envíos fuera de la ventana 24h.
- **Evita palabras-trampa:** "GRATIS!!!", "URGENTE!!!", todo mayúsculas → más probabilidad de reporte como spam.
- **Personaliza:** siempre usa `{nombre}` y segmenta — nunca broadcast general.

---

## Parte 6 · Atribución Meta Ads (30 min)

Este es el **caso de uso estrella**: convertir anuncios en Instagram/Facebook en ventas medibles por WhatsApp.

### 6.1 · Por qué importa

Antes sin esta funcionalidad, los ads de "Click to WhatsApp" terminaban en una conversación anónima — Meta no sabía si generó venta. Con CAPI conectado, **cada venta se reporta de vuelta al píxel** y el algoritmo puede optimizar la pauta.

### 6.2 · Preparar el pixel

1. Meta Business Manager → **Fuentes de datos** → crea un pixel (o usa uno existente).
2. Configuración del pixel → **API de conversiones** → genera un **Access Token**.
3. (Opcional) Genera un **Test Event Code** para probar sin contaminar data real.

### 6.3 · Registrar el pixel en FastChat

**Ruta admin:** `/admin/whatsapp/pixelmeta/add/`

- Nombre: "Pixel principal"
- Pixel ID: `1234567890`
- CAPI Access Token: `EAAG...`
- Test event code: déjalo vacío (o pon el de test)
- Activo: ✓

### 6.4 · Vincular el pixel a una sesión

**Ruta:** `/whatsapp/sesiones/` → edita la sesión → **Pixel Meta (CAPI)** → selecciona el pixel que creaste.

### 6.5 · Crear el anuncio CTWA

En **Meta Ads Manager** (fuera de FastChat):

1. Crear campaña → objetivo: **Engagement** → **Messaging**.
2. Click destination: **WhatsApp**.
3. Número: el que registraste como sesión.
4. Creativo: foto + texto + botón "Enviar mensaje".
5. Publica.

### 6.6 · Probar el flujo completo

1. Desde **otra cuenta**, toca el anuncio en Instagram/Facebook.
2. WhatsApp se abre con tu número.
3. Envía un "Hola".
4. **En FastChat** → `/whatsapp/conversaciones/` → abre la nueva → verás que tiene `ctwa_clid`, `campaign_id` y `ad_id` rellenados.
5. **En admin** → **Eventos CAPI** → verás un evento `Lead` enviado automáticamente con `exitoso=True`.
6. **En Meta Events Manager** → pixel → Test Events → verás el Lead llegar.

### 6.7 · Reportar la venta (Purchase)

Cuando la conversación termine en venta:

1. Abre el Kanban en `/whatsapp/pipeline/`.
2. Mueve la tarjeta a la etapa "Cerrado ganado".
3. Antes de soltarla, edita el `valor_estimado` con el monto real (ej. $87.50).
4. Al moverla, FastChat dispara automáticamente **Purchase** a CAPI con ese valor.
5. En Meta Ads Manager verás la conversión atribuida al `campaign_id` original.

### 6.8 · Ver ROI en tiempo real

**Ruta:** `/whatsapp/analytics/` → tabla **ROI por campaña CTWA**:

| Campaign ID | Ad ID | Conversaciones | Leads | Clientes | Conv. % |
|---|---|---|---|---|---|
| 120210... | 120220... | 45 | 23 | 8 | 17.8% |

→ "De 45 personas que vinieron del anuncio X, 8 compraron = 17.8% conversión."

---

## Parte 7 · Agregar Instagram + Messenger (20 min)

### 7.1 · Instagram DM

**Pre-requisitos:**
- Cuenta Instagram Business (no personal).
- Vinculada a una FB Page.
- App en Meta Developer Portal con el producto **Instagram Graph API** activado.

**Setup:**

1. `/whatsapp/sesiones/` → **Nueva sesión** → proveedor: `Instagram DM`.
2. Admin → `/admin/whatsapp/configinstagram/add/`:
   - Sesión: la que creaste.
   - IG User ID: `17841400000000000` (sacado de Graph API Explorer).
   - Page ID: el de la FB Page vinculada.
   - Username: `@tuhandle`.
   - Access Token: Page access token con permiso `instagram_manage_messages`.
   - App Secret: de tu app Meta.
   - Webhook Verify Token: genera uno con `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. En Meta Developer Portal → tu app → Webhooks → suscríbete a **Instagram** → callback:
   - URL: `https://tu-dominio.com/whatsapp/instagram_webhook/`
   - Verify Token: el que generaste.
   - Campos: `messages`, `messaging_postbacks`, `message_reactions`.

**Probar:** manda un DM a la cuenta IG Business desde otra cuenta personal. Debería aparecer en `/whatsapp/conversaciones/` con `origen_canal=instagram`.

### 7.2 · Messenger (Facebook Page)

Idéntico pero usando `ConfigMessenger`, URL `/whatsapp/messenger_webhook/`, permiso `pages_messaging`.

---

## Parte 8 · Casos de uso por tipo de negocio

### 8.1 · E-commerce: tienda online

**Problema:** responder consultas 24/7, recuperar carritos abandonados, campañas segmentadas por compras previas.

**Setup específico:**

1. **Agente IA** con `contexto_estatico` que incluya:
   - Top 20 productos con precios.
   - Políticas de envío, devolución, pago.
   - Link al catálogo.
2. **Etiquetas:**
   - `Primera compra` (aplicar cuando completa pedido)
   - `Recurrente` (2+ compras)
   - `VIP` (5+ compras o ticket > $500)
   - `Abandonó carrito` (interactuó pero no compró en 7 días)
   - `Reembolso pendiente`
3. **Pipeline:**
   - Nuevo → Interesado → Carrito armado → Pagó → Enviado → Entregado
4. **Campañas típicas:**
   - **Recuperación carrito:** a etiqueta `Abandonó carrito`, 48h después, con descuento 10%.
   - **Lanzamiento producto:** a etiqueta `Recurrente` + `Newsletter OK`, un día antes del lanzamiento público.
   - **VIP exclusivo:** a `VIP` con un código único.
5. **Ads CTWA:**
   - Uno por categoría de producto (ropa, accesorios, calzado).
   - Cada ad tiene su `campaign_id` → ves cuál genera más ventas en analytics.

**Flujo diario de un agente:**
1. Abre `/whatsapp/conversaciones/` → lista conversaciones asignadas.
2. Prioriza las que tienen el ícono 🔔 de CTWA (leads pagados).
3. Contesta dudas sobre productos.
4. Si el cliente pide cotización → crea tarjeta en Kanban, etapa "Cotización enviada".
5. Cuando confirma pago → mueve a "Pagó" → y cuando llega → "Entregado" (que idealmente es la etapa `es_ganado=True` para disparar Purchase a CAPI).

---

### 8.2 · Restaurante / delivery

**Problema:** tomar pedidos, reservas, y responder "¿está abierto?" 100 veces al día.

**Setup específico:**

1. **Horarios de atención** (`/whatsapp/horarios/`):
   - Lunes cerrado (excepción todo el mes).
   - Martes-jueves 12:00-22:00.
   - Viernes-sábado 12:00-24:00.
   - Domingo 12:00-20:00.
   - Mensaje fuera de horario: "Estamos cerrados. Abrimos martes 12pm. Puedes hacer tu reserva para mañana y te confirmamos al abrir."
2. **Agente IA** con `contexto_estatico`:
   - Menú completo con precios y descripción.
   - Opciones veganas/celíacas/sin TACC.
   - Zonas de delivery + costos.
   - Forma de pedir reserva (cuántas personas, fecha, hora).
3. **Etiquetas:**
   - `Habitual` (pidió 5+ veces)
   - `Alergia gluten`, `Vegano`, etc. (guardar en `nota_interna` del contacto)
   - `Reserva grupo` (10+ personas)
4. **Pipeline "Pedidos":**
   - Nuevo → Confirmado → Preparando → En camino → Entregado (ganado)
5. **Campañas típicas:**
   - **Happy hour 2x1:** a `Habitual`, los jueves 4pm.
   - **Nuevo plato:** a `Vegano` cuando agregan menú plant-based.

**Tip:** si activas `auto_asignar_round_robin` entre 3 meseros "agentes", cada pedido nuevo se les reparte automáticamente.

---

### 8.3 · Inmobiliaria

**Problema:** calificar leads rápido (presupuesto, zona, urgencia) antes de gastar tiempo de un bróker humano.

**Setup específico:**

1. **Agente IA** con instrucciones de calificar:
   ```
   Al inicio de la conversación, pregunta:
   1. ¿Compra o arriendo?
   2. ¿Zona preferida?
   3. ¿Presupuesto máximo?
   4. ¿Cuándo necesita mudarse?

   Cuando tengas las 4 respuestas, transfiere a un asesor humano
   con el resumen.
   ```
2. **Regla de fin de conversación** (`crm/reglas-fin`): al detectar "quiero ver" o "quiero visita", dispara acción "Asignar a humano".
3. **Etiquetas:**
   - `Comprador`, `Arrendatario`
   - `Presupuesto <50k`, `50-150k`, `150-300k`, `>300k`
   - `Urgente 30 días`, `3-6 meses`, `Explorando`
   - Por zonas: `Cumbayá`, `Valle Tumbaco`, `Norte Quito`...
4. **Pipeline "Comercial":**
   - Lead calificado → Visita agendada → Visita realizada → Oferta → Firma (ganado) → Cerrada

**Campañas:**
- **Nueva propiedad en zona X:** a `Cumbayá` + `Presupuesto 150-300k`, cuando listas una propiedad.
- **Ads CTWA segmentados:** un ad por zona + presupuesto → en analytics ves cuál convierte mejor.

---

### 8.4 · Clínica médica / estética

**Problema:** agendar citas, enviar recordatorios, reducir ausencias.

**Setup específico:**

1. **Agente IA** conectado a tu sistema de agendas (via `HerramientaAgente` con endpoint a tu API):
   ```
   Cuando el paciente pida cita:
   1. Pregunta especialidad y fecha preferida.
   2. Llama a la herramienta "consultar_disponibilidad".
   3. Ofrece 3 horarios.
   4. Confirma y llama a "agendar_cita".
   ```
2. **Horarios** estrictos: lunes-viernes 08:00-17:00 + sábados 09:00-13:00.
3. **Campañas programadas:**
   - **Recordatorio 24h antes:** automatizable con cron + API REST. Consulta citas del día siguiente y envía `MensajeWhatsAppProgramado` con plantilla Meta aprobada de categoría UTILITY.
   - **Chequeo anual:** a pacientes con última visita hace 11 meses.
4. **Etiquetas:**
   - `Medicina general`, `Pediatría`, `Estética`
   - `Paciente crónico` (requiere seguimiento especial)
   - `Primera vez` vs `Recurrente`

**Importante — regulación:**
- Usa siempre plantillas Meta categoría `UTILITY` para recordatorios (no `MARKETING`).
- No guardes diagnósticos ni info sensible en `nota_interna` sin cifrado.

---

### 8.5 · Instituto educativo

**Problema:** responder preguntas de admisión, convertir interesados en matriculados.

**Setup específico:**

1. **Agente IA** con info de todos los programas (entrenamientos cargados en FAISS):
   - Duración
   - Costo
   - Modalidad (online/presencial)
   - Certificación
   - Fechas de inicio
2. **Etiquetas por programa:**
   - `Interesado Marketing`, `Interesado Contabilidad`, etc.
   - `Matriculado 2026-A`, `Graduado 2025`
3. **Pipeline "Matrícula":**
   - Interesado → Calificado → Cotización → Matrícula reservada → Pagado (ganado) → Iniciado
4. **Campañas:**
   - **Último cupo:** a `Interesado Marketing` sin matricular, 3 días antes del inicio.
   - **Apertura de curso avanzado:** a `Graduado 2025` con curso básico del área.
5. **Ads CTWA por programa** → analytics te dice cuál convierte mejor.

---

### 8.6 · Agencia de servicios (marketing, contable, legal)

**Problema:** lead generation + nurturing largo + venta consultiva.

**Setup específico:**

1. **Agente IA** con briefing:
   ```
   Eres SDR de una agencia de marketing digital. Tu objetivo:
   - Calificar (presupuesto, tamaño de empresa, urgencia).
   - Agendar reunión con el CEO.
   - Nunca des precio exacto; siempre "depende del alcance, agendemos una llamada".
   ```
2. **Pipeline "Sales":**
   - MQL → SQL → Reunión agendada → Reunión realizada → Propuesta enviada → Negociando → Cerrado ganado/perdido.
3. **Etiquetas:**
   - `Industria: retail`, `Industria: saas`, etc.
   - `Empresa 1-10`, `11-50`, `51+`
   - `Decisor`, `Intermediario`
4. **Horarios** y **round-robin:** 3 SDRs reciben los leads alternadamente.
5. **Webhook saliente:** cuando llega un MQL (etapa inicial), dispara a Slack:
   ```json
   {
     "url": "https://hooks.slack.com/services/...",
     "eventos": ["conversacion.nueva"]
   }
   ```
   Así el equipo se entera en tiempo real.

---

### 8.7 · Empresa B2B con equipo comercial

**Problema:** varios vendedores, territorios, jerarquía de seguimiento.

**Setup específico:**

1. **DisponibilidadAgente** por cada vendedor, con `sesiones` limitadas (ej. solo la sesión "Vendedor Quito-Norte").
2. **Round-robin** se encarga de repartir nuevos leads.
3. **Pipeline estándar B2B** con etapas largas (ciclo de 3-6 meses):
   - Lead → Discovery → Demo → Propuesta → Negociación → Legal → Firmado → Perdido
4. **Integraciones con CRM externo** via webhooks salientes → HubSpot/Salesforce.
5. **API REST** para sincronizar contactos desde el CRM → FastChat:
   ```bash
   POST /whatsapp/api/v1/contactos/
   { "sesion_id": 1, "numero": "5939...", "nombre": "Juan" }
   ```

---

## Parte 9 · Operación diaria: el día a día de un agente

### Rutina matutina (15 min)

1. **Abre `/panel/`** — dashboard principal.
2. **`/whatsapp/conversaciones/`** — filtra "asignadas a mí" + "abiertas" → atiende.
3. **Pipeline** → revisa tarjetas estancadas (>48h en una etapa) → las trabajas primero.
4. **Mensajes programados del día** → revisa `MensajeWhatsAppProgramado` para que no se dispare algo raro.

### Durante el día

**Cuando llega una conversación nueva (notificación en tiempo real via WebSocket):**
1. Ábrela, lee el historial.
2. Si tiene ícono CTWA 🔔 → trátala prioridad (es lead pagado).
3. Responde manualmente o deja que la IA responda y valida.
4. Etiquétala.
5. Si amerita, arrástrala al Kanban.

**Cuando el cliente confirma una compra/venta:**
1. Mueve la tarjeta a "Cerrado ganado" (con valor real).
2. Cambia la clasificación a `Cliente`.
3. Agrega etiquetas post-venta (`Compró 1 vez`, `Envío pendiente`, etc.).
4. Cierra la conversación (botón "Terminar conversación") — dispara resumen IA + análisis de sentimiento.

### Al finalizar el día

1. Todas las conversaciones que requieren seguimiento mañana → etiqueta `Seguimiento mañana`.
2. Programa recordatorios con `MensajeWhatsAppProgramado` si vas a escribir al día siguiente.
3. Revisa `Analytics` → KPI del día (cuántas conversaciones, cuántos cierres).

---

## Parte 10 · Reportes y KPIs

**Ruta:** `/whatsapp/analytics/?dias=30`

### KPIs clave a monitorear

| KPI | Dónde verlo | Meta saludable |
|---|---|---|
| Conversaciones por día | Gráfico línea | Crecimiento MoM |
| % Mensajes IA / total | Card superior | 60-80% (IA resuelve primer nivel) |
| Tasa conversión (Clientes/Leads) | Tabla clasificación | 10-25% según rubro |
| Tiempo primera respuesta | `EstadisticasConversacion` | <5 min |
| ROI por campaña CTWA | Tabla CTWA | Conv. % > costo adquisición / ticket promedio |
| Forecast pipeline ponderado | Tabla forecast | Depende de cuota |
| Eventos CAPI exitosos | Card superior | 100% success (si hay fallos, revisar pixel token) |

### Exportar data a Excel/BI

- **JSON directo:** `/whatsapp/analytics/?action=data&dias=90` → pégalo en Power BI o Google Sheets.
- **API REST:** itera conversaciones/campañas con paginación.

---

## Solución de problemas

### "La IA no responde"

1. `/whatsapp/trazas/?criterio=<número-del-contacto>` — verás el pipeline entero.
2. Causas típicas:
   - API key sin créditos (`llm_error` con "quota exceeded").
   - Sesión no conectada (`ia_desactivada`).
   - Modo bot en `ninguno` (cambiar a `ia` o `hibrido`).

### "La campaña no envía"

1. Revisa que el cron `ejecutar_campanas.py` esté corriendo (busca en logs).
2. Estado de la campaña debe ser `programada` o `enviando`.
3. `/admin/whatsapp/enviocampana/` → filtra por la campaña → revisa el campo `error`.

### "CAPI no registra conversiones"

1. Admin → **Eventos CAPI** → filtra `exitoso=False` → lee `response_body` (Meta te dice por qué).
2. Causas típicas:
   - Access token expirado (genera uno nuevo, los token de usuarios cortos caducan rápido — usa **System User tokens** que no expiran).
   - Pixel no activo o ID equivocado.
   - `test_event_code` puesto en producción (los eventos no suman a conversiones reales).

### "El webhook Meta no recibe eventos"

1. Meta Developer Portal → Webhooks → **Test** con datos mock → revisa si llega.
2. En Django, `/admin/whatsapp/eventometarecibido/` → verás si llega algo con `firma_valida=False` (problema de app_secret).
3. Asegúrate que la URL pública sea HTTPS (Meta exige TLS) y responda 200 en <5 segundos.

### "Los agentes no reciben asignación round-robin"

1. Admin → **Disponibilidad de agentes** → todos deben tener `disponible=True`.
2. Sesión debe tener `auto_asignar_round_robin=True`.
3. Si agente limita sus sesiones, la de la conversación debe estar en la lista.
4. Revisa `/admin/whatsapp/asignacionautomatica/` — verás intentos y motivos.

---

**¿Dudas?** Abre `/whatsapp/trazas/` primero — el 90% de problemas se diagnostica ahí. Si no, revisa los admins (`/admin/`) de los modelos relevantes: `EventoMetaRecibido`, `EventoCAPI`, `TrazaMensajeIA`, `EnvioCampana`.
