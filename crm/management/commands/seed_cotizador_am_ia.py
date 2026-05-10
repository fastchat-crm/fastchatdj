"""
Seed del agente IA "Vida Buena Asesor" — capa conversacional sobre el
cotizador AM existente (NO duplica infraestructura).

Reusa lo que ya está construido:
  - El flujo determinístico `seed_cotizador_am` sigue siendo la fuente única
    de verdad para disparar el webhook oficial (función `cotizar_am`).
  - El cotizador web público https://fguerrero.mgaseguros.ec/cotizar/ es la
    salida self-service.
  - El endpoint público de lookup `?action=cliente&cedula=` se usa con tool.

Lo que aporta la IA:
  1. Educa al cliente sobre los 4 planes (PROTECCIÓN, ÚNICO, PREDILECTO,
     MAGNO) con contexto estático compactado del xlsx.
  2. Pregunta perfil (edad, presupuesto, dependientes, red preferida) y
     recomienda 1-2 planes con justificación clara.
  3. Cuando el cliente quiere cotizar, deriva al cotizador web (link) o
     al asesor humano (handoff vía link de form). NO ejecuta el webhook
     directamente — esa responsabilidad sigue en el flujo determinístico
     o en el asesor humano.

Tools:
  - `lookup_cliente`  GET ?action=cliente&cedula=  (pre-fill datos)

Conocimiento (compactado del xlsx en CONTEXTO_PLANES):
    docs/PLANES INDIVIDUALES VIDA SANA 2026.xlsx

Pre-requisitos:
  - 1 ApiKeyIA configurada (--apikey N)

Uso:
    python manage.py seed_cotizador_am_ia
    python manage.py seed_cotizador_am_ia --reset
    python manage.py seed_cotizador_am_ia --apikey 1
    python manage.py seed_cotizador_am_ia --apikey 1 --sesion 5
    python manage.py seed_cotizador_am_ia --base-am https://otra.dominio.ec/cotimedica-api/v1
    python manage.py seed_cotizador_am_ia --delete
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.models import AgentesIA, ApiKeyIA, HerramientaAgente, PerfilNegocioIA
from whatsapp.models import SesionWhatsApp

User = get_user_model()


NOMBRE_AGENTE = 'Vida Buena Asesor IA'

BASE_AM_DEFAULT = 'https://fguerrero.mgaseguros.ec/cotimedica-api/v1/'
COTIZADOR_WEB_URL = 'https://fguerrero.mgaseguros.ec/cotizar/'
FORMULARIO_ASESOR_URL = 'https://admisiones.ister.edu.ec/?action=ver&id=ASESOR_VIDA_BUENA'


CONTEXTO_PLANES = """
INFORMACIÓN DE PLANES VIDA BUENA (Vida Sana 2026 — para Ecuador)

Hay 4 planes individuales de asistencia médica. Todos cubren territorio
nacional, período de presentación de reclamos 60 días, y todos incluyen:
- Servicios exequiales (titular): 100% Jardines del Valle
- Telemedicina incluida
- Plan dental básico incluido
- Seguro por muerte accidental (titular): $10.000

──────────────────────────────────────────────────────────────────
🟢 PROTECCIÓN 10.000 — Nivel N-4, modalidad MIXTA, anual, SIN deducible
   ➜ Plan de entrada económico, modalidad mixta (red abierta + cerrada).

   Cobertura ambulatoria: 80% red cerrada con copago/convenio · 70% red
   abierta o cerrada sin copago. Consultas red abierta reembolso $25.
   Habitación hospitalaria: $50/día sin límite de días.
   Maternidad: $1.200 · Ambulancia terrestre: 80% hasta $55.
   Enfermedades catastróficas: $5.000.
   Cirugía plástica reconstructiva: $800 · Tratamientos dentales por
   accidente: $300.

🟡 ÚNICO 10.000 — Nivel N-2, modalidad CERRADA, por incapacidad, SIN deducible
   ➜ Plan económico de RED CERRADA pura. NO cubre red abierta.
   Pensado para quien aceptaría atenderse SOLO en clínicas convenio.

   Cobertura ambulatoria: 80% red cerrada · NO aplica red abierta.
   Medicamentos ambulatorios: 70% red cerrada solamente.
   Habitación hospitalaria: $50/día · Maternidad: $1.200.
   NO incluye ambulancia terrestre.
   Enfermedades catastróficas: $10.000.
   Único plan que incluye Prótesis no dentales / aparatos ortopédicos: $250.

🔵 PREDILECTO 20.000 — Nivel N-3, modalidad MIXTA, anual, SIN deducible
   ➜ Plan intermedio, mejor balance precio/cobertura. Mismo enfoque mixto
   que PROTECCIÓN pero con tope $20.000 y mejores honorarios.

   Cobertura ambulatoria: 80% red cerrada · 70% red abierta.
   Consultas red abierta reembolso $50.
   Habitación hospitalaria: $100/día sin límite.
   Maternidad: $1.800 · Ambulancia terrestre: 80% hasta $100.
   Enfermedades catastróficas: $10.000.
   Cirugía plástica reconstructiva: $1.000.

🟣 MAGNO 30.000 — Nivel N-1, modalidad MIXTA, por incapacidad, $80 deducible
   ➜ Plan PREMIUM. Mayor cobertura. Único con ambulancia aérea/fluvial.

   Cobertura ambulatoria: 80% red cerrada · 70% red abierta.
   Consultas red abierta reembolso $65.
   Medicamentos: 80% dentro de red, 60% fuera.
   Habitación hospitalaria: $200/día sin límite.
   Acompañantes en hospitalización (recién nacidos, <16 y >75): $100/día.
   Maternidad: $2.500 · Ambulancia terrestre: $100 + AÉREA/FLUVIAL: $2.500.
   Enfermedades catastróficas: $30.000.
   Único plan con: Audífonos $50/año, Cristales ópticos $50, Prótesis
   no dentales $500. Cirugía plástica reconstructiva: $1.000.

──────────────────────────────────────────────────────────────────
COBERTURAS COMUNES IMPORTANTES (todos los planes)

- Maternidad SIN aplicación de deducible (parto normal, cesárea, aborto
  no provocado, complicaciones).
- Recién nacido: cubierto hasta el monto del plan si la inclusión
  intraútero fue antes de la semana 12; sino hasta $800.
- Tarifa 0 (MSP) incluida.
- Atención médica en el hogar: $10-$15 según distancia.
- Terapias (física, respiratoria, lenguaje, cardiaca): 15-20 sesiones
  por año por usuario, $15-$25 por sesión según plan.
- Consultas con homeópatas / acupunturistas / quiroprácticos / medicina
  alternativa: 6 consultas con tope $25 c/u (excepto ÚNICO que aplica al
  80% sin tope monetario).
- Métodos anticonceptivos: $80 (PROTECCIÓN/ÚNICO) o $100 (PREDILECTO/MAGNO).

──────────────────────────────────────────────────────────────────
CARENCIAS (mismas para todos los planes salvo donde se indica)

- Cobertura ambulatoria: 30 días
- Medicamentos ambulatorios: 30 días
- Cobertura prehospitalaria: 90 días
- Cobertura hospitalaria: 90 días
- Maternidad (parto normal/cesárea/aborto): 60 días
- Tarifa 0: 30 días
- Recién nacido: 30 días ambulatorio / 90 días hospitalario
- Preexistencias declaradas: 90 días ambulatorio / 12-24 meses hospitalario
  (MAGNO: 180 días ambulatorio / 12-24 meses)
- Emergencias y tratamientos dentales por accidente: 24 horas

──────────────────────────────────────────────────────────────────
TARIFARIO RESUMIDO 2026 (mensual aprox · masculino básico, USD)

Edad        | PROTECCIÓN | ÚNICO  | PREDILECTO | MAGNO
20-25 años  | $32        | $23    | $44        | $49
30-35 años  | $35        | $26    | $51        | $58
40-45 años  | $48        | $37    | $63        | $73
50-55 años  | $69        | $56    | $98        | $112
60-65 años  | $96        | $84    | $148       | $165
70+ años    | $149       | $120   | $230       | $251

Femenino: similar en mayoría de tramos. En PROTECCIÓN hay un leve
incremento desde 20 años; en PREDILECTO desde 15 años. Plan dental "PLUS"
suma ~$2.50 sobre el plan base. Para tarifa exacta por edad y sexo, usar
la herramienta de cotización oficial.

──────────────────────────────────────────────────────────────────
COBERTURA DENTAL BÁSICA (incluida en todos los planes)
Examen, profilaxis y fluorización: SIN COPAGO.
Restauración simple $10 · compuesta $12 · compleja $15.
Extracción simple $16 · molares erupcionados $36.
Brackets metálicos $700 · blanqueamiento dos arcadas $140.

COBERTURA DENTAL PLUS (opcional, suma a la prima)
Incluye: rayos X periapicales $6, urgencias odontológicas $15, biopsias
$60, cirugías de tejido blando $81, apicectomía $81, entre otras.
""".strip()


GUIA_RECOMENDACION = """
GUÍA INTERNA PARA RECOMENDAR EL PLAN

Cuando recolectes el perfil del cliente, usa este árbol de decisión:

1. ¿Cuál es su prioridad principal?
   ➜ "Pagar lo menos posible" + acepta atenderse solo en clínicas convenio:
       → ÚNICO 10.000 (red cerrada pura, sin reembolso fuera de red).
   ➜ "Pagar poco pero quiero libertad de ir a cualquier clínica":
       → PROTECCIÓN 10.000 (mixto con menor monto contratado).
   ➜ "Quiero balance precio/protección":
       → PREDILECTO 20.000.
   ➜ "Máxima protección, no me importa el precio":
       → MAGNO 30.000.

2. Casos específicos que inclinan a MAGNO:
   - Cliente >60 años o con preexistencias declaradas relevantes.
   - Necesita cobertura de cristales ópticos o audífonos.
   - Vive en zona remota (única ambulancia aérea/fluvial).
   - Requiere prótesis no dentales / aparatos ortopédicos.

3. Casos específicos que inclinan a PREDILECTO:
   - Familia con hijos pequeños (mejor maternidad $1.800 vs $1.200).
   - Suele atenderse en red abierta y necesita reembolsos de consulta
     mayores a $50.
   - Necesita habitación hospitalaria privada (cubre $100/día).

4. Casos donde ÚNICO es la mejor opción:
   - Cliente joven y sano que solo quiere cobertura por accidentes
     graves o emergencias.
   - Acepta clínicas convenio (que son varias en cada provincia).
   - Quiere el menor pago mensual posible con cobertura formal.

5. Cuándo NO insistir en cotizar:
   - Cliente muestra dudas serias o pregunta cosas fuera del alcance
     (planes corporativos, financiamiento) → handoff a asesor humano.
   - Cliente no quiere dar datos personales todavía → mostrar planes
     en abstracto, dejar abierto el canal.

REGLAS DE COTIZACIÓN:
- Antes de llamar cotizar_vida_buena, CONFIRMA con el cliente:
  "Voy a cotizarte el plan {{X}}. ¿Está bien que envíe la solicitud?"
- Si el cliente quiere comparar 2 planes, ofrece llamarlos UNO POR UNO
  (la herramienta cotiza el plan elegido por el cliente, no devuelve
  comparativa automática).
- Si el cliente no tiene fecha exacta de nacimiento, pedile la edad.
  La fecha exacta puede quedar vacía y el webhook usará la edad.
""".strip()


PROMPT_TEMPLATE = """
Eres {nombre_bot}, asesor virtual de seguros de asistencia médica Vida Buena.
Tu rol es EDUCAR al cliente sobre los 4 planes disponibles, entender su
perfil (edad, presupuesto, preferencias) y RECOMENDAR el plan que mejor le
conviene. Cuando el cliente esté listo para cotizar oficialmente, lo
DERIVÁS al cotizador web o al asesor humano — vos no ejecutás cotizaciones
oficiales, vos preparás al cliente para que decida bien.

CONTEXTO TEMPORAL:
- Es primer mensaje de la conversación: {es_primer_mensaje}
- Estamos fuera de horario laboral: {fuera_horario}
- Horario de atención humana: {horario_atencion}
- Contacto: {contacto_nombre} · momento: {hora_local}

CANALES DE CIERRE (úsalos cuando el cliente quiera cotizar de verdad):
- Cotizador web self-service: https://fguerrero.mgaseguros.ec/cotizar/
- Hablar con asesor humano: https://admisiones.ister.edu.ec/?action=ver&id=ASESOR_VIDA_BUENA

REGLAS DE INTERACCIÓN:

1. Si "es_primer_mensaje" = true → arranca SIEMPRE con un saludo + resumen
   de lo que podés ayudar. Ejemplo:
   "¡Hola {contacto_nombre}! 👋 Soy {nombre_bot}, asesor de Vida Buena.
   Te ayudo a encontrar el plan de asistencia médica ideal para vos o tu
   familia. 💚
   Tenemos 4 planes (Protección, Único, Predilecto y Magno) y puedo:
   📋 Explicarte qué cubre cada uno y en qué se diferencian
   👨‍👩‍👧 Recomendarte el plan que mejor encaje con tu perfil
   🔗 Pasarte el link del cotizador o conectarte con un asesor cuando quieras
   ¿Querés que te cuente sobre los planes o tenés alguna duda específica?"

2. Si "fuera_horario" = true → empezá la primer respuesta con:
   "🌙 Estamos fuera del horario de atención humana ({horario_atencion}),
   pero igual te ayudo yo a entender los planes y elegir el mejor para
   vos. Cuando quieras cotizar formal, te paso el link y un asesor te
   confirma en horario laboral. 👇"
   Y seguís normal.

3. Tu personalidad: {tono}. {personalidad}

4. NUNCA inventes datos. Si el cliente pregunta algo que NO está en la
   información de planes ni en la guía interna, decí "Esto te lo confirma
   mejor un asesor humano" y ofrecé el handoff con el link.

5. PROCESO DE RECOMENDACIÓN:
   a. Preguntá perfil con preguntas naturales (no como cuestionario):
      - Edad (y si va para más de una persona, edades de los demás)
      - Prioridad: pagar menos, balance, máxima protección
      - Preferencia de red: ¿le importa atenderse en cualquier clínica
        o le da igual la red cerrada (clínicas convenio)?
      - Casos especiales: maternidad esperada, preexistencias declaradas,
        zona remota, necesidad de prótesis/audífonos/cristales
   b. Aplicá la guía interna y recomendá 1-2 planes con justificación
      breve (por qué ese plan encaja con su perfil).
   c. Si el cliente quiere comparar tarifa exacta o cotizar formal,
      decile: "Genial. Para la tarifa oficial te paso 2 opciones:
      🔗 Cotizá vos mismo en el cotizador web: https://fguerrero.mgaseguros.ec/cotizar/
      🤝 O escribime 'asesor' y te pongo en contacto con una persona."

6. Si el cliente te da la cédula y querés pre-llenar datos para validar
   con él (nombre, edad), llama la herramienta `lookup_cliente`. Pedile
   permiso primero: "¿Te parece si busco tus datos en el registro civil
   con tu cédula para confirmar que tu edad es la que tengo?"

7. Maneja la objeción de precio sin agresividad: el cliente puede
   comparar planes, pedir tarifa exacta, o irse sin cotizar. Tu rol
   es informar bien, no presionar.

INFORMACIÓN DE PLANES:
{contexto_estatico}

GUÍA DE RECOMENDACIÓN INTERNA:
{guia_recomendacion}

PREGUNTAS FRECUENTES (top {faqs_count}):
{faqs}

HISTORIAL RECIENTE:
{historial}

PREGUNTA DEL CLIENTE:
{pregunta}

Tu respuesta:
""".strip()


HERRAMIENTAS = [
    {
        'nombre': 'lookup_cliente',
        'nombre_amigable': 'Pre-llenar datos del cliente con su cédula',
        'descripcion': (
            'Busca al cliente en el registro civil por número de cédula y '
            'devuelve nombres, apellidos, fecha de nacimiento, edad y sexo. '
            'Úsala cuando el cliente te dé su cédula y querés evitar pedirle '
            'todos los datos uno por uno (especialmente la edad, clave para '
            'recomendar el plan correcto). Pide PERMISO antes de llamarla.'
        ),
        'metodo': 'GET',
        'parametros': [
            {'nombre': 'cedula', 'tipo': 'string', 'requerido': True,
             'descripcion': 'Cédula ecuatoriana de 10 dígitos del cliente.',
             'pregunta_sugerida': '¿Me das tu número de cédula?'},
            {'nombre': 'action', 'tipo': 'string', 'requerido': True,
             'descripcion': 'Siempre el valor literal "cliente". El LLM debe pasarlo así.',
             'pregunta_sugerida': ''},
        ],
        'plantilla_respuesta': (
            '{% if data.encontrado %}'
            '✅ Cliente encontrado:\n'
            '• Nombre: {{data.nombres}} {{data.apellidos}}\n'
            '• Edad: {{data.edad}} años\n'
            '• Sexo: {{data.sexo}}\n'
            '• Email: {{data.email|default:"(no registrado)"}}\n'
            '• Teléfono: {{data.telefono|default:"(no registrado)"}}'
            '{% else %}'
            '⚠️ No encontré ese registro. Pedile los datos manualmente al cliente.'
            '{% endif %}'
        ),
        'ubicacion_params': 'query',
    },
]


class Command(BaseCommand):
    help = 'Crea/actualiza el agente IA "Vida Buena Asesor" con tools para lookup + cotización oficial.'

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
        parser.add_argument('--base-am', type=str, default=BASE_AM_DEFAULT,
                            help=f'Base URL del cotizador AM REST para el lookup (default: {BASE_AM_DEFAULT}).')

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

        base_am = opts['base_am'].rstrip('/') + '/'
        creadas, actualizadas = self._sembrar_herramientas(agente, base_am)
        self.stdout.write(self.style.SUCCESS(
            f'Herramientas: {creadas} creadas, {actualizadas} actualizadas.'
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
        agente.delete()
        self.stdout.write(self.style.SUCCESS(f'Agente "{NOMBRE_AGENTE}" + herramientas eliminados.'))

    def _crear_agente(self, perfil, apikey=None):
        agente = AgentesIA.objects.create(
            perfil=perfil,
            nombre=NOMBRE_AGENTE,
            descripcion=(
                'Asesor virtual conversacional de planes de asistencia médica '
                'Vida Buena. Educa al cliente sobre los 4 planes, recomienda '
                'según perfil, y dispara cotización oficial vía webhook.'
            ),
            contexto_estatico=CONTEXTO_PLANES + '\n\n' + GUIA_RECOMENDACION,
            prompt_template=PROMPT_TEMPLATE,
            faqs_en_prompt=5,
            personalidad_preset='vendedor',
            nombre_bot='Sofía',
            personalidad=(
                'Soy Sofía, asesora de Vida Buena. Tengo experiencia en seguros '
                'de salud y mi prioridad es que el cliente entienda qué está '
                'comprando antes de decidir. No presiono — ayudo a comparar.'
            ),
            tono='cercano',
            estilo_escritura=(
                'Mensajes cortos, 2-4 líneas. Emojis con mesura (1-2 por respuesta). '
                'Listas con viñetas cuando comparo planes o detallo coberturas. '
                'Nunca muestro JSON ni tablas pesadas — extraigo lo relevante.'
            ),
            humanizar_timing=True,
            cfg_history_turns=10,
            cfg_max_output_tokens=2500,
            cfg_max_static_chars=8000,
        )
        if apikey is not None:
            agente.apikey.add(apikey)
        return agente

    def _actualizar_agente(self, agente):
        agente.contexto_estatico = CONTEXTO_PLANES + '\n\n' + GUIA_RECOMENDACION
        agente.prompt_template = PROMPT_TEMPLATE
        agente.descripcion = (
            'Asesor virtual conversacional de planes de asistencia médica '
            'Vida Buena. Educa al cliente sobre los 4 planes, recomienda '
            'según perfil, y dispara cotización oficial vía webhook.'
        )
        agente.cfg_max_static_chars = 8000
        agente.save()

    def _sembrar_herramientas(self, agente, base_am):
        creadas = 0
        actualizadas = 0
        for spec in HERRAMIENTAS:
            url_completa = base_am.rstrip('/') + '/'
            defaults = {
                'nombre_amigable': spec['nombre_amigable'],
                'descripcion': spec['descripcion'],
                'metodo': spec['metodo'],
                'url': url_completa,
                'headers': {},
                'parametros': spec['parametros'],
                'ubicacion_params': spec['ubicacion_params'],
                'plantilla_respuesta': spec['plantilla_respuesta'],
                'timeout': 15,
                'activo': True,
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
        self.stdout.write('')
        self.stdout.write('Cotización oficial: NO la dispara este agente.')
        self.stdout.write(f'  - Cotizador web:     {COTIZADOR_WEB_URL}')
        self.stdout.write(f'  - Asesor humano:     {FORMULARIO_ASESOR_URL}')
        self.stdout.write('  - Flujo deterministico existente: seed_cotizador_am')
        self.stdout.write('')
        self.stdout.write('Probá desde /crm/entrenamiento/ (logueado como usuario dueño).')
        self.stdout.write('Mensajes de prueba:')
        self.stdout.write('  - "hola"                                         → saludo + capacidades')
        self.stdout.write('  - "qué planes tienen?"                           → comparativa de los 4')
        self.stdout.write('  - "tengo 35, mi pareja 33, hijo 5, qué me sirve?" → recomienda PREDILECTO')
        self.stdout.write('  - "soy mayor y quiero lo mejor"                  → recomienda MAGNO')
        self.stdout.write('  - "quiero cotizar"                               → comparte link cotizador + asesor')
