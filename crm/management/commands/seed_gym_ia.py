"""
Seed del agente IA "Sandow Fitness IA" — capa conversacional sobre la info
del departamento Gimnasio Control (seed_gimnasio_control).

Reusa lo que ya está construido:
  - El flujo determinístico `seed_gimnasio_control` sigue siendo el menú
    rígido para sesiones en modo tradicional.
  - Este seed crea el agente IA equivalente: misma info (sedes, planes,
    promos, métodos de pago) pero conversacional con function-calling.

Lo que aporta la IA:
  1. Educa al cliente sobre las 2 sedes (García, Pdte.) y los 4 planes
     mensuales (Elite X, Elite +, Pro Move, Base Fit) + planes largo
     plazo (Anual, Semestral, 4 Meses).
  2. Recomienda plan según el horario del cliente y su presupuesto.
  3. Cuando el cliente quiere pagar, comparte el link de PayPhone o los
     datos bancarios para transferencia + link del form de comprobante.
  4. Si el cliente pide ubicación → comparte link de Google Maps Sede 1.
  5. Deriva a asesor humano por palabra clave "asesor".

Tools: ninguna HTTP (Sandow no expone API pública). Toda la info
está en el prompt + bloques de conocimiento.

Pre-requisitos:
  - 1 ApiKeyIA configurada (--apikey N)

Uso:
    python manage.py seed_gym_ia
    python manage.py seed_gym_ia --reset
    python manage.py seed_gym_ia --apikey 1
    python manage.py seed_gym_ia --apikey 1 --sesion 5
    python manage.py seed_gym_ia --delete
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.models import AgentesIA, ApiKeyIA, DetalleAgentesAI, HerramientaAgente, PerfilNegocioIA
from whatsapp.models import SesionWhatsApp

User = get_user_model()


NOMBRE_AGENTE = 'Sandow Fitness IA'

URL_PAYPHONE_SANDOW = 'https://pay.payphonetodoesposible.com/sandowfitness'
URL_FORM_COMPROBANTE = 'https://docs.google.com/forms/d/e/REEMPLAZAR/viewform'
URL_MAPS_SEDE1 = 'https://maps.google.com/?q=-2.1325,-79.5878'


CONTEXTO_PLANES = """
INFORMACIÓN DE SANDOW FITNESS (gimnasio, Milagro - Guayas, Ecuador)

Sandow Fitness tiene 2 sedes en Milagro. Horario general Lun-Sab
5:00 AM - 11:00 PM. Todos los planes incluyen: Wifi, casilleros,
vestidores, duchas e instructores. 🏋

──────────────────────────────────────────────────────────────────
🏢 SEDE 1 — García
Dirección: Av. García Moreno y 9 de Octubre, Milagro, Guayas.
Mapa: {url_maps_sede1}

Planes mensuales disponibles en Sede 1:

👑 Plan Elite X — $35/mes
   Horario: 5:30 AM - 10:00 PM
   Acceso: 2 SEDES (García + Pdte.) + CrossFit
   Incluye: Musculación, Funcional, Box, Dance, CrossFit

🥇 Plan Elite + — $27/mes
   Horario: 5:30 AM - 10:00 PM
   Acceso: Sede 1
   Incluye: Musculación, Funcional, Box, Dance

⚡ Plan Pro Move — $21/mes
   Horario: 5:30 AM - 1:00 PM (solo mañana)
   Acceso: Sede 1
   Incluye: Musculación, Funcional, Box, Dance

💪 Plan Base Fit — $18/mes
   Horario: 11:00 AM - 2:00 PM (franja media)
   Acceso: Sede 1
   Incluye: SOLO Musculación

──────────────────────────────────────────────────────────────────
🏢 SEDE 2 — Pdte.
Mismos planes y comodidades que Sede 1. Para inscripción en Sede 2
el cliente se deriva con un asesor humano (palabra clave "asesor").

──────────────────────────────────────────────────────────────────
📆 PLANES LARGO PLAZO (paga adelantado y ahorra)

🥇 Plan Anual: $180 (~$15/mes equivalente)
💪 Plan Semestral (6 meses): $105 (~$17.5/mes equivalente)
⚡ Plan 4 Meses: $85 (~$21.25/mes equivalente)

──────────────────────────────────────────────────────────────────
🎁 PROMOCIONES VIGENTES (válidas hasta el domingo)

· 2x1 en Plan Pro Move — trae a un amigo, paga uno solo.
· Plan Anual con 15% off → $153 (en lugar de $180).
· Inscripción GRATIS si pagás con tarjeta.

──────────────────────────────────────────────────────────────────
💳 MÉTODOS DE PAGO

1) Tarjeta de Crédito (rápido, seguro, inscripción gratis)
   Link PayPhone: {url_payphone}
   El cliente ingresa el valor exacto del plan elegido.
   Después debe subir el comprobante por el formulario.

2) Transferencia Bancaria
   🏦 Banco: Produbanco (Cuenta Corriente)
   👤 Titular: Sandow Fitness SAS
   📋 RUC: 0993367918001
   💳 Número de cuenta: 27059002064
   Después de transferir → subir comprobante por el formulario.

📸 SUBIR COMPROBANTE (después de cualquier pago):
{url_form_comprobante}
Una asesora activa la membresía en breve apenas reciba el comprobante.

──────────────────────────────────────────────────────────────────
📍 UBICACIÓN
Sede 1 García: {url_maps_sede1}

──────────────────────────────────────────────────────────────────
👤 ASESOR HUMANO
Si el cliente quiere coordinar Sede 2, casos especiales (plan empresa,
acompañante, refund, suspender membresía) o cualquier duda fuera del
catálogo → escribir la palabra "asesor" y el sistema deriva. NUNCA
inventes una URL de asesor.
""".format(
    url_maps_sede1=URL_MAPS_SEDE1,
    url_payphone=URL_PAYPHONE_SANDOW,
    url_form_comprobante=URL_FORM_COMPROBANTE,
).strip()


GUIA_RECOMENDACION = """
GUÍA INTERNA PARA RECOMENDAR EL PLAN

Cuando recolectes interés del cliente, usa este árbol de decisión:

1. ¿Cuándo puede entrenar el cliente?
   ➜ "Mañana temprano (5:30 AM - 1:00 PM)" → Pro Move $21
   ➜ "Mediodía (11:00 AM - 2:00 PM)" + solo musculación → Base Fit $18
   ➜ "Tarde-noche (hasta 10:00 PM)" + Sede 1 → Elite + $27
   ➜ "Tarde-noche + 2 sedes + CrossFit" → Elite X $35
   ➜ "Cualquier horario, lo mejor" → Elite X $35

2. ¿Qué disciplinas quiere?
   ➜ Solo musculación → Base Fit (más económico)
   ➜ Musculación + Funcional/Box/Dance → Elite + o Pro Move según horario
   ➜ Incluye CrossFit → Elite X (único que lo incluye)

3. ¿Cuánto tiempo se compromete?
   ➜ "Probar un mes" → plan mensual del horario que le calza
   ➜ "Voy en serio, 4+ meses" → mencionar Plan 4 Meses $85 ($21.25/mes)
   ➜ "Todo el año" → Plan Anual $180 ($15/mes) + actualmente 15% off $153
   ➜ Si va a pagar con tarjeta → recordar que la inscripción es GRATIS

4. ¿Qué sede le queda más cerca?
   ➜ Si dice "García" o "centro" → Sede 1, podés seguir hasta el pago.
   ➜ Si dice "Pdte." o "presidente" → Sede 2, derivar a asesor humano.
   ➜ Si dice "ambas/me da igual" → recomendar Elite X (acceso a 2 sedes).

CUÁNDO DERIVAR A ASESOR (escribí 'asesor' o explicá que lo haga):
- Sede 2 (inscripción no automatizada).
- Pregunta por plan empresa / corporativo.
- Quiere suspender o devolver membresía existente.
- Pregunta por entrenamiento personalizado / coaching premium.
- Tiene una queja o problema con membresía existente.

REGLAS DE PAGO:
- Antes de mandar el link de PayPhone, CONFIRMÁ con el cliente:
  "Vas con {{Plan X}} a ${{precio}}/mes. ¿Te paso el link de pago?"
- Después de mandar el link de pago, AVISÁ que también debe subir
  el comprobante por el formulario apenas termine.
- Si elige transferencia: primero mandá los datos bancarios, después
  el link del formulario.
- NUNCA inventes precios fuera de la tabla.
- NUNCA prometas promos que no estén en la lista.
""".strip()


CHUNKS_CONOCIMIENTO = [
    (
        "Sede 1 García — dirección y planes mensuales",
        "SEDE 1 — García (Av. García Moreno y 9 de Octubre, Milagro).\n"
        "Mapa: " + URL_MAPS_SEDE1 + "\n\n"
        "Planes mensuales:\n"
        "👑 Elite X $35 — 5:30AM-10:00PM — 2 SEDES + CrossFit + Musculación + Funcional + Box + Dance.\n"
        "🥇 Elite + $27 — 5:30AM-10:00PM — Musculación + Funcional + Box + Dance.\n"
        "⚡ Pro Move $21 — 5:30AM-1:00PM (solo mañana) — Musculación + Funcional + Box + Dance.\n"
        "💪 Base Fit $18 — 11:00AM-2:00PM — SOLO Musculación.\n\n"
        "Todos incluyen: Wifi, casilleros, vestidores, duchas e instructores."
    ),
    (
        "Sede 2 Pdte. — inscripción asistida",
        "SEDE 2 — Pdte.\n"
        "Mismos planes y comodidades que Sede 1.\n"
        "La inscripción en Sede 2 NO es automatizada por este chat.\n"
        "El cliente debe escribir 'asesor' y un humano lo coordina."
    ),
    (
        "Planes largo plazo (anual, semestral, 4 meses)",
        "PLANES LARGO PLAZO (paga adelantado y ahorra):\n\n"
        "🥇 Anual: $180 — ~$15/mes equivalente.\n"
        "💪 Semestral (6 meses): $105 — ~$17.5/mes equivalente.\n"
        "⚡ 4 Meses: $85 — ~$21.25/mes equivalente.\n\n"
        "Estos planes son sobre el acceso a Sede 1 con las disciplinas estándar.\n"
        "Para Elite X (2 sedes + CrossFit) largo plazo → derivar a asesor."
    ),
    (
        "Promociones vigentes (válidas hasta el domingo)",
        "PROMOCIONES VIGENTES:\n\n"
        "· 2x1 en Plan Pro Move — trae a un amigo, ambos entrenan pagando solo uno.\n"
        "· Plan Anual con 15% off → $153 (precio normal $180).\n"
        "· Inscripción GRATIS si el cliente paga con tarjeta de crédito.\n\n"
        "Válidas hasta el domingo. Si el cliente duda, recordale que se vencen."
    ),
    (
        "Método de pago — Tarjeta de Crédito (PayPhone)",
        "PAGO CON TARJETA DE CRÉDITO:\n\n"
        "Link PayPhone: " + URL_PAYPHONE_SANDOW + "\n\n"
        "Pasos:\n"
        "1. El cliente toca el link y va a PayPhone.\n"
        "2. Ingresa el valor exacto del plan elegido.\n"
        "3. Paga con su tarjeta.\n"
        "4. Hace captura del comprobante.\n"
        "5. Sube el comprobante por: " + URL_FORM_COMPROBANTE + "\n\n"
        "Ventaja: inscripción gratis con tarjeta (promo vigente)."
    ),
    (
        "Método de pago — Transferencia Bancaria",
        "PAGO POR TRANSFERENCIA:\n\n"
        "🏦 Banco: Produbanco (Cuenta Corriente)\n"
        "👤 Titular: Sandow Fitness SAS\n"
        "📋 RUC: 0993367918001\n"
        "💳 Número de cuenta: 27059002064\n\n"
        "Pasos:\n"
        "1. El cliente transfiere el monto exacto del plan elegido.\n"
        "2. Sube el comprobante por: " + URL_FORM_COMPROBANTE + "\n"
        "3. Una asesora activa la membresía en breve."
    ),
    (
        "Comodidades incluidas en TODOS los planes",
        "Cosas que SIEMPRE incluye la membresía (cualquier plan):\n"
        "- Wifi en sede.\n"
        "- Casilleros disponibles.\n"
        "- Vestidores y duchas.\n"
        "- Acompañamiento de instructores presentes en piso.\n\n"
        "Horario general del gimnasio: Lun-Sab 5:00 AM - 11:00 PM.\n"
        "Cada plan tiene su franja específica DENTRO de ese horario general."
    ),
    (
        "Ubicación de las sedes",
        "📍 Sede 1 García: Av. García Moreno y 9 de Octubre, Milagro, Guayas.\n"
        "Mapa: " + URL_MAPS_SEDE1 + "\n\n"
        "📍 Sede 2 Pdte.: La dirección exacta la da el asesor humano cuando\n"
        "el cliente decide inscribirse en esa sede. Derivar con 'asesor'."
    ),
    (
        "Cuándo derivar a asesor humano",
        "DERIVÁ A ASESOR (escribí 'asesor' o pedile al cliente que lo escriba):\n"
        "- Inscripción en Sede 2 Pdte.\n"
        "- Plan empresa / corporativo / grupo grande.\n"
        "- Suspender, congelar o devolver una membresía existente.\n"
        "- Entrenamiento personalizado / coaching premium.\n"
        "- Queja o problema con membresía activa.\n"
        "- Cualquier solicitud fuera del catálogo de planes y promos.\n\n"
        "NUNCA inventes una URL ni un número de asesor. Solo deriva."
    ),
    (
        "Guía interna de recomendación de plan",
        "ÁRBOL DE DECISIÓN para recomendar plan:\n\n"
        "1. ¿Cuándo puede entrenar?\n"
        "   - Solo mañana (5:30AM-1PM) → Pro Move $21\n"
        "   - Solo mediodía (11AM-2PM) + solo musculación → Base Fit $18\n"
        "   - Tarde-noche en Sede 1 → Elite + $27\n"
        "   - Tarde-noche + 2 sedes + CrossFit → Elite X $35\n\n"
        "2. ¿Qué disciplinas quiere?\n"
        "   - Solo musculación → Base Fit\n"
        "   - Musculación + Funcional/Box/Dance → Elite + o Pro Move\n"
        "   - Quiere CrossFit → Elite X (único)\n\n"
        "3. ¿Cuánto tiempo se compromete?\n"
        "   - Probar 1 mes → plan mensual\n"
        "   - 4 meses → Plan 4 Meses $85\n"
        "   - Año entero → Plan Anual $180 (con 15% off ahora: $153)\n\n"
        "4. ¿Va a pagar con tarjeta? → recordar que la inscripción es GRATIS.\n\n"
        "5. ¿Pide Sede 2? → derivar a 'asesor'."
    ),
]


PROMPT_TEMPLATE = """
Eres {nombre_bot}, asesora virtual de Sandow Fitness (gimnasio en Milagro,
Ecuador, 2 sedes). Tu trabajo: en el MENOR número de mensajes posible,
recomendar el plan ideal según horario + presupuesto del cliente y
cerrar la inscripción enviando el link de pago.

NO sos un chatbot de preguntas. NO hagas cuestionarios largos. NO listes
los planes a menos que el cliente lo pida o sea el primer turno.

CONTEXTO TEMPORAL:
- Es primer mensaje de la conversación: {es_primer_mensaje}
- Estamos fuera de horario laboral: {fuera_horario}
- Horario de atención humana: {horario_atencion}
- Contacto: {contacto_nombre} · momento: {hora_local}

CANALES DE CIERRE:
- Pago con tarjeta (PayPhone): https://pay.payphonetodoesposible.com/sandowfitness
- Pago por transferencia: Produbanco Cta Cte 27059002064 a Sandow Fitness SAS (RUC 0993367918001)
- Subir comprobante (DESPUÉS de cualquier pago): https://docs.google.com/forms/d/e/REEMPLAZAR/viewform
- Ubicación Sede 1: https://maps.google.com/?q=-2.1325,-79.5878
- Asesor humano: el cliente escribe "asesor" y el sistema deriva.
  NUNCA inventes URL ni número de asesor.

REGLAS DE ORO (no negociables):

1. NO recomendés un plan específico ANTES de saber:
   a) En qué franja horaria puede entrenar el cliente, y
   b) Qué tipo de plan quiere (mensual o largo plazo si lo menciona).
   Si pregunta directo "qué planes hay" → mostrá los 4 mensuales
   comprimidos + mencioná opciones largo plazo + preguntá su horario.

2. NUNCA inventes precios fuera del catálogo. Todos los precios están
   en el conocimiento — citalos textual.

3. Cuando el cliente acepte un plan, ANTES de mandar el link de pago
   confirmá: "Vas con {{plan}} a ${{precio}}/mes. ¿Te paso el link
   de pago con tarjeta o preferís transferencia?"

4. Después de mandar el link de PayPhone o los datos bancarios,
   SIEMPRE recordá que hay que subir el comprobante por el formulario.

DETECTAR INTENT DE INSCRIBIRSE — palabras clave del cliente:
"inscribirme", "anotarme", "precios", "cuánto cuesta", "cuánto sale",
"planes", "membresía", "afiliarme", "comprar", "pagar", "cotizar",
"qué plan me sirve", "recomendame", "cuál me conviene", "horarios".
Cuando detectás CUALQUIERA de estos, el siguiente paso es PREGUNTAR
HORARIO + DISCIPLINAS (si todavía no lo sabés).

FLUJO IDEAL:

PASO 1 — Primer mensaje (si es_primer_mensaje=true):
   Saludá corto, presentate como Sandow Fitness, y dirigí directo a
   los planes:
   "¡Hola {contacto_nombre}! 👋 Soy {nombre_bot}, te ayudo a
   inscribirte en Sandow Fitness. 🏋💪 Tenemos 2 sedes en Milagro y
   planes desde $18/mes. Para recomendarte el ideal, ¿en qué horario
   pensás entrenar y qué disciplinas te interesan?"
   NO listes los 4 planes en este momento.

PASO 2 — Cliente pide ver precios / planes ANTES de dar horario:
   Mostrá los 4 mensuales SUPER comprimidos + opciones largo plazo +
   preguntá horario:
   "Tenemos 4 planes mensuales en Sede 1 (García):
   👑 Elite X $35 — todo el día + 2 SEDES + CrossFit
   🥇 Elite + $27 — todo el día + disciplinas (sin CrossFit)
   ⚡ Pro Move $21 — solo mañana (5:30AM-1PM)
   💪 Base Fit $18 — solo mediodía + solo musculación
   📆 Largo plazo: Anual $180 · Semestral $105 · 4 Meses $85
   ¿Qué horario te queda mejor para entrenar?"

PASO 3 — Cliente dice horario + disciplinas:
   Mapeá según la guía y recomendá UN plan específico (no 4):
   "Por lo que me decís, te encaja perfecto el plan *{{plan}}* a
   ${{precio}}/mes:
   ✅ {{beneficio_1}}
   ✅ {{beneficio_2}}
   ✅ {{beneficio_3}}
   Y ahora tenemos {{promo_aplicable}}.
   ¿Lo vamos cerrando?"

PASO 4 — Cliente acepta el plan:
   Preguntá método de pago:
   "Genial. ¿Querés pagar con *tarjeta* (te paso el link de PayPhone,
   y la inscripción te sale gratis 🎁) o por *transferencia* bancaria?"

PASO 5a — Cliente elige tarjeta:
   Mandá el link de PayPhone + aviso del comprobante:
   "✅ Listo. Pagás $X aquí: https://pay.payphonetodoesposible.com/sandowfitness
   ⚠️ MUY IMPORTANTE: apenas pagues, hacele captura al recibo y subilo
   por este formulario para activar la membresía:
   https://docs.google.com/forms/d/e/REEMPLAZAR/viewform 📸"

PASO 5b — Cliente elige transferencia:
   Mandá los datos bancarios + aviso del comprobante:
   "🏦 Banco Produbanco (Cta Corriente)
   👤 Sandow Fitness SAS
   📋 RUC: 0993367918001
   💳 Cuenta: *27059002064*
   Una vez transferido, subí el comprobante por este formulario:
   https://docs.google.com/forms/d/e/REEMPLAZAR/viewform 📸
   Una asesora te activa la membresía apenas lo recibe."

PASO 6 — Después de mandar link de pago / datos bancarios:
   Quedate disponible para dudas: localización, horarios específicos,
   qué incluye cada plan, qué llevar el primer día, etc. NO presiones.
   Si el cliente parece confundido o pide algo fuera del catálogo →
   sugerile escribir 'asesor'.

EXCEPCIONES:

- Si el cliente pregunta por SEDE 2 (Pdte.):
  "La inscripción en Sede 2 la coordina un asesor humano. Escribime
  'asesor' y te conecto. 👤"

- Si el cliente pregunta por ubicación / cómo llegar a Sede 1:
  "📍 Sede 1 García — Av. García Moreno y 9 de Octubre, Milagro:
  https://maps.google.com/?q=-2.1325,-79.5878"

- Si el cliente pregunta por promociones SIN haber elegido plan:
  Mencionalas brevemente + volvé al flujo:
  "Ahora tenemos: 2x1 en Pro Move · Anual con 15% off ($153) ·
  Inscripción gratis con tarjeta. ¿Querés que te recomiende el plan
  ideal según tu horario?"

- Si el cliente pide PLAN EMPRESA / corporativo / grupo grande →
  derivar a asesor. NUNCA cotices grupos vos.

- Si el cliente quiere suspender / cancelar / devolver membresía
  existente → derivar a asesor. NO es venta nueva.

- AVISO DE HORARIO — REGLA ESTRICTA:
  Si fuera_horario=true Y es_primer_mensaje=true → SOLO en esa primera
  respuesta agregás una línea corta tipo:
  "🌙 Estamos fuera de horario, pero te ayudo con tu inscripción igual."
  En CUALQUIER otro mensaje (es_primer_mensaje=false), NUNCA menciones
  el horario, NUNCA listes los días/horas. El cliente ya sabe.

REGLAS DURAS:
- NUNCA inventes tarifas, sedes o disciplinas — todo está en el
  conocimiento.
- NUNCA pidas datos personales (cédula, email) — Sandow no los
  necesita para inscribir vía este flujo, basta con el pago.
- NUNCA mandes el link de pago SIN antes haber confirmado el plan
  elegido y el método.
- NO listes los 4 planes salvo que el cliente lo pida explícitamente
  o sea el PASO 2.
- NO respondas con cosas genéricas tipo "Buenas, ¿cómo te ayudo?".
  Tu primer mensaje SIEMPRE debe presentar Sandow + preguntar horario.
- Tu personalidad: {tono}. {personalidad}

HISTORIAL RECIENTE:
{contexto_extra}

INFORMACIÓN DE SANDOW FITNESS Y GUÍA DE RECOMENDACIÓN (única fuente de verdad):
====
{context}
====

PREGUNTA DEL CLIENTE: {question}

Tu respuesta:
""".strip()


HERRAMIENTAS = []


class Command(BaseCommand):
    help = 'Crea/actualiza el agente IA "Sandow Fitness IA" (versión conversacional del depto Gimnasio Control).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el agente previo y sus herramientas y recrea todo.')
        parser.add_argument('--delete', action='store_true',
                            help='Solo borra el agente y sale (no recrea).')
        parser.add_argument('--apikey', type=int, default=None,
                            help='ID de ApiKeyIA a vincular (opcional — si no, asignala desde la UI).')
        parser.add_argument('--usuario', type=int, default=1,
                            help='ID del Usuario dueño del agente (default: 1).')
        parser.add_argument('--sesion', type=int, default=None,
                            help='ID de SesionWhatsApp para asignar el agente como modo_bot=ia.')

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['delete']:
            self._eliminar()
            return

        if opts['reset']:
            self._eliminar()

        agente = AgentesIA.objects.filter(nombre=NOMBRE_AGENTE).first()
        creando = agente is None

        if creando:
            usuario = self._resolver_usuario(opts['usuario'])
            perfil, _ = PerfilNegocioIA.objects.get_or_create(usuario=usuario)
            self.stdout.write(self.style.HTTP_INFO(
                f'Usuario dueño: {usuario.username} (id={usuario.id}) · perfil={perfil.id}'
            ))

            apikey = None
            if opts['apikey']:
                try:
                    apikey = ApiKeyIA.objects.get(id=opts['apikey'], status=True)
                except ApiKeyIA.DoesNotExist:
                    raise CommandError(f'No existe ApiKeyIA activa con id={opts["apikey"]}')

            agente = self._crear_agente(perfil, apikey)
            self.stdout.write(self.style.SUCCESS(f'Agente creado: {agente.nombre} (id={agente.id})'))
            if apikey is None:
                self.stdout.write(self.style.WARNING(
                    'Sin --apikey: el agente quedó SIN ApiKeyIA. '
                    'Asignala manualmente desde /crm/entrenamiento/.'
                ))
        else:
            self.stdout.write(self.style.WARNING(f'Agente ya existe (id={agente.id}) — actualizando.'))
            self._actualizar_agente(agente)

        creadas, actualizadas = self._sembrar_herramientas(agente)
        self.stdout.write(self.style.SUCCESS(
            f'Herramientas: {creadas} creadas, {actualizadas} actualizadas '
            f'(Sandow no expone APIs, así que normalmente quedan en 0).'
        ))

        n_detalles = self._sembrar_detalles(agente)
        self.stdout.write(self.style.SUCCESS(
            f'Conocimiento: {n_detalles} bloques de texto cargados en el agente '
            '(visibles en /crm/entrenamiento/ → tab Conocimiento).'
        ))

        if opts['sesion']:
            self._vincular_sesion(agente, opts['sesion'])

        self._resumen(agente)

    def _resolver_usuario(self, usuario_id):
        try:
            return User.objects.get(id=usuario_id)
        except User.DoesNotExist:
            raise CommandError(f'No existe Usuario con id={usuario_id}')

    def _eliminar(self):
        agente = AgentesIA.objects.filter(nombre=NOMBRE_AGENTE).first()
        if not agente:
            self.stdout.write(self.style.WARNING(f'No existe agente "{NOMBRE_AGENTE}", nada para borrar.'))
            return
        SesionWhatsApp.objects.filter(agente_ia=agente).update(agente_ia=None, modo_bot='ninguno')
        agente.herramientas.all().delete()
        agente.detalleagentesai_set.all().delete()
        agente.delete()
        self.stdout.write(self.style.SUCCESS(f'Agente "{NOMBRE_AGENTE}" + herramientas + conocimiento eliminados.'))

    def _crear_agente(self, perfil, apikey=None):
        agente = AgentesIA.objects.create(
            perfil=perfil,
            nombre=NOMBRE_AGENTE,
            descripcion=(
                'Asesora virtual conversacional de Sandow Fitness (gimnasio en '
                'Milagro). Recomienda planes según horario y disciplinas, '
                'comparte links de pago (PayPhone / transferencia) y deriva '
                'a asesor humano cuando es Sede 2 o caso fuera de catálogo.'
            ),
            contexto_estatico=CONTEXTO_PLANES + '\n\n' + GUIA_RECOMENDACION,
            prompt_template=PROMPT_TEMPLATE,
            faqs_en_prompt=5,
            personalidad_preset='vendedor',
            nombre_bot='Sandy',
            mensaje_bienvenida=(
                '¡Hola! 👋 Soy Sandy, asesora virtual de Sandow Fitness. 🏋💪\n\n'
                'Tenemos 2 sedes en Milagro y planes desde *$18/mes*. '
                'Para recomendarte el plan ideal, contame:\n'
                '🕐 ¿En qué horario pensás entrenar?\n'
                '🤸 ¿Qué disciplinas te interesan (musculación, funcional, '
                'box, dance, CrossFit)?'
            ),
            personalidad=(
                'Soy Sandy, asesora de Sandow Fitness. Energética y resolutiva. '
                'Conozco los 4 planes mensuales y los planes largo plazo. Mi '
                'prioridad es que el cliente encuentre el plan que le calza '
                'según su horario sin perder tiempo en cuestionarios largos.'
            ),
            tono='vendedor',
            estilo_escritura=(
                'Mensajes cortos, 2-4 líneas. Emojis con mesura (1-3 por '
                'respuesta, fitness-friendly: 🏋💪🔥). Listas con viñetas '
                'cuando comparo planes o muestro beneficios. Nunca muestro '
                'JSON ni tablas pesadas — extraigo lo relevante.'
            ),
            humanizar_timing=True,
            humaniz_chars_burbuja_max=500,
            humaniz_max_burbujas=8,
            cfg_history_turns=10,
            cfg_max_output_tokens=3000,
            cfg_max_static_chars=8000,
        )
        if apikey is not None:
            agente.apikey.add(apikey)
        return agente

    def _actualizar_agente(self, agente):
        agente.contexto_estatico = CONTEXTO_PLANES + '\n\n' + GUIA_RECOMENDACION
        agente.prompt_template = PROMPT_TEMPLATE
        agente.descripcion = (
            'Asesora virtual conversacional de Sandow Fitness (gimnasio en '
            'Milagro). Recomienda planes según horario y disciplinas, '
            'comparte links de pago (PayPhone / transferencia) y deriva '
            'a asesor humano cuando es Sede 2 o caso fuera de catálogo.'
        )
        agente.cfg_max_static_chars = 8000
        agente.save()

    def _sembrar_herramientas(self, agente):
        creadas = 0
        actualizadas = 0
        for spec in HERRAMIENTAS:
            defaults = {
                'nombre_amigable': spec['nombre_amigable'],
                'descripcion': spec['descripcion'],
                'metodo': spec['metodo'],
                'url': spec.get('url', ''),
                'headers': {},
                'parametros': spec['parametros'],
                'ubicacion_params': spec['ubicacion_params'],
                'plantilla_respuesta': spec['plantilla_respuesta'],
                'timeout': spec.get('timeout', 15),
                'activo': True,
                'funcion_codigo': spec.get('funcion_codigo', ''),
            }
            obj, creado = HerramientaAgente.objects.update_or_create(
                agente=agente,
                nombre=spec['nombre'],
                defaults=defaults,
            )
            if creado:
                creadas += 1
            else:
                actualizadas += 1
        return creadas, actualizadas

    def _sembrar_detalles(self, agente):
        DetalleAgentesAI.objects.filter(agente=agente, tipo=3, status=True).delete()
        for titulo, cuerpo in CHUNKS_CONOCIMIENTO:
            DetalleAgentesAI.objects.create(
                agente=agente,
                tipo=3,
                descripcion=f'[{titulo}]\n\n{cuerpo}',
                tipo_dato_enlace=1,
                requiere_token=False,
                usar_cache=False,
                tiempo_cache_horas=1,
            )
        return len(CHUNKS_CONOCIMIENTO)

    def _vincular_sesion(self, agente, sesion_id):
        try:
            sesion = SesionWhatsApp.objects.get(id=sesion_id, status=True)
        except SesionWhatsApp.DoesNotExist:
            raise CommandError(f'No existe SesionWhatsApp activa con id={sesion_id}')
        sesion.agente_ia = agente
        sesion.modo_bot = 'ia'
        sesion.save(update_fields=['agente_ia', 'modo_bot'])
        self.stdout.write(self.style.SUCCESS(
            f'Sesión #{sesion.id} ({sesion.nombre or sesion.numero}) vinculada con modo_bot=ia.'
        ))

    def _resumen(self, agente):
        perfil_owner = agente.perfil.usuario.username if (agente.perfil and agente.perfil.usuario) else '(sin dueño)'
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('=== RESUMEN ==='))
        self.stdout.write(f'Agente: {agente.nombre} (id={agente.id})')
        self.stdout.write(f'Dueño (perfil.usuario): {perfil_owner}')
        self.stdout.write(f'API Keys vinculadas: {agente.apikey.count()}')
        self.stdout.write(f'Herramientas activas: {agente.herramientas.filter(activo=True, status=True).count()}')
        self.stdout.write(f'Bloques de conocimiento: {agente.detalleagentesai_set.filter(status=True, tipo=3).count()}')
        self.stdout.write('')
        self.stdout.write('Conocimiento visible en la UI:')
        self.stdout.write(f'  /crm/entrenamiento/?action=procedimiento&id={agente.id}')
        self.stdout.write(f'  → tab "Conocimiento" → ver los {len(CHUNKS_CONOCIMIENTO)} bloques de texto.')
        self.stdout.write('')
        self.stdout.write('URLs públicas usadas por el agente (placeholders — actualizá en producción):')
        self.stdout.write(f'  - PayPhone:        {URL_PAYPHONE_SANDOW}')
        self.stdout.write(f'  - Comprobante:     {URL_FORM_COMPROBANTE}')
        self.stdout.write(f'  - Mapa Sede 1:     {URL_MAPS_SEDE1}')
        self.stdout.write('')
        self.stdout.write('Inscripción Sede 2 / casos fuera de catálogo → handoff por palabra clave "asesor".')
        self.stdout.write('Flujo determinístico equivalente: seed_gimnasio_control')
        self.stdout.write('')
        self.stdout.write('Probá desde /crm/entrenamiento/ (logueado como usuario dueño).')
        self.stdout.write('Mensajes de prueba:')
        self.stdout.write('  - "hola"                                  → saludo + pide horario')
        self.stdout.write('  - "qué planes tienen?"                    → 4 mensuales comprimidos + largo plazo')
        self.stdout.write('  - "quiero entrenar mañana temprano"       → recomienda Pro Move $21')
        self.stdout.write('  - "quiero hacer CrossFit"                 → recomienda Elite X $35')
        self.stdout.write('  - "voy a ir todo el año"                  → menciona Anual $153 (15% off)')
        self.stdout.write('  - "cómo pago?"                            → pregunta tarjeta vs transferencia')
        self.stdout.write('  - "tarjeta"                               → link PayPhone + recordatorio comprobante')
        self.stdout.write('  - "y la sede 2?"                          → deriva a asesor')
