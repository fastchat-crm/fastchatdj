"""
Seed del agente IA "Lucía RU" — espejo conversacional del flujo seed_ru.

Diferencia vs seed_ru:
  - seed_ru crea un DepartamentoChatBot con menú rígido de 15 opciones.
  - seed_ru_ia crea un AgentesIA + 7 HerramientaAgente que el LLM invoca
    vía function-calling. El estudiante conversa libre; el agente decide
    cuándo llamar la API.

Lo que cubre:
  - Las 6 APIs privadas de RU (actividades, materias, horarios general,
    horarios hoy, deudas, mentor, contactos académicos) → 7 tools HTTP.
  - Toda la info estática (pregrado, posgrado, becas, homologación,
    soporte, vinculación, cambio de clave, ingreso a clases) → inyectada
    en `contexto_estatico` del agente.
  - Handoff a humano: el agente comparte la URL del formulario de asesor
    cuando el estudiante lo pide o cuando no puede responder.

Pre-requisitos:
  - Tener al menos 1 ApiKeyIA configurada (provider Claude/Gemini/OpenAI).
    Pasale el ID con --apikey.
  - Si querés vincular el agente a una sesión, --sesion <id>.

Uso:
    python manage.py seed_ru_ia --apikey 1
    python manage.py seed_ru_ia --apikey 1 --reset
    python manage.py seed_ru_ia --apikey 1 --sesion 5
    python manage.py seed_ru_ia --apikey 1 --base-url https://otro.dominio/v1/bot/ru
    python manage.py seed_ru_ia --delete
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.models import AgentesIA, ApiKeyIA, HerramientaAgente
from whatsapp.models import SesionWhatsApp


NOMBRE_AGENTE = 'Lucía RU IA'
BASE_URL_DEFAULT = 'https://ruedge.ister.edu.ec/service/v1/bot/ru'

URL_FORMULARIO_ASESOR = (
    'https://admisiones.ister.edu.ec/?action=ver&id=OPPQQRRSSTTUUVVWWXXX'
)


CONTEXTO_ESTATICO = """
INFORMACIÓN DEL INSTITUTO ISTER (úsala cuando el estudiante pregunte por
estos temas — no llamés ninguna herramienta para esto, respondé directo):

──────────────────────────────────────────────────────────────────
🚪 ENTRAR A CLASES / AULA VIRTUAL
- Portal Ruedge: https://ruedge.ister.edu.ec/alu/horarios/
- Iniciar sesión con usuario y clave institucional.
- Tutorial: https://www.youtube.com/watch?v=gL_4UYdYwq0
- Si no aparece en Teams o Aula Virtual, la cuenta puede tardar
  unas horas en propagarse. Si persiste, abrir ticket en
  https://procesos.ister.edu.ec

🔐 CAMBIAR CONTRASEÑA
- Portal: https://ruedge.ister.edu.ec/autenticacion/restorepass/

🎓 OFERTA DE PREGRADO
- Tecnologías superiores y carreras, modalidades, horarios, requisitos
  y costos: https://admisiones.ister.edu.ec/admision-pregrado/

🚀 OFERTA DE POSGRADO
- Especializaciones, maestrías y programas avanzados:
  https://admisiones.ister.edu.ec/admision-posgrados/

🔄 HOMOLOGACIÓN DE ESTUDIOS
- Si viene de otra institución y quiere convalidar materias:
  https://homologacion.ister.edu.ec

🏆 BECAS Y AYUDAS ECONÓMICAS
- Tipos de beca, requisitos, postulación:
  https://ister.edu.ec/sistema-de-becas-y-ayudas-economicas/

🎧 SOPORTE GENERAL ACADÉMICO/ADMINISTRATIVO
- Balcón de servicios: https://procesos.ister.edu.ec
- Web institucional: https://ister.edu.ec

🤝 VINCULACIÓN CON LA COMUNIDAD
- Prácticas Comunitarias:
  https://ruedge.ister.edu.ec/alu/practicascomunitarias/
- Prácticas Preprofesionales:
  https://ruedge.ister.edu.ec/alu/practicaspreprofesionales/
- Plazas Disponibles:
  https://ruedge.ister.edu.ec/alu/plazaspracticaspreprofesionales/
- Bolsa Laboral:
  https://ruedge.ister.edu.ec/alu/bolsa_laboral/

📩 HABLAR CON UN ASESOR HUMANO
- Si el estudiante quiere que un asesor del ISTER lo contacte
  personalmente, o si tiene una duda que no podés responder con
  las herramientas ni con esta información, comparte SIEMPRE este
  enlace y pedile que llene el formulario:
  {url_asesor}
- Frase sugerida: "Para esto te conviene que te contacte un asesor
  del ISTER. Llená este formulario y se comunican vos a la brevedad: <link>"
""".format(url_asesor=URL_FORMULARIO_ASESOR).strip()


PROMPT_TEMPLATE = """
Eres {nombre_bot}, la asistente virtual del Instituto Superior Tecnológico
ISTER. Tu rol es ayudar a estudiantes activos a consultar información de
su matrícula, materias, horarios, deudas y mentor; y orientarlos sobre
trámites generales (pregrado, posgrado, becas, homologación, etc.).

REGLAS DE INTERACCIÓN:
1. Saluda con calidez al primer mensaje. Presenta brevemente lo que podés
   ayudar.
2. Para consultas privadas (actividades, materias, horarios, deudas,
   mentor, contactos académicos) NECESITAS la cédula del estudiante.
   Si todavía no la tenés en la conversación, pedila ANTES de llamar la
   herramienta. Cédula = 10 dígitos numéricos.
3. Una vez que tengas la cédula, REUSALA en consultas siguientes — no la
   pidas de nuevo en la misma conversación.
4. Al recibir la respuesta JSON de una herramienta, redactala en lenguaje
   natural (no muestres JSON crudo). Usa emojis con mesura, párrafos
   cortos, listas si hay múltiples ítems.
5. Si una herramienta devuelve ERROR o vacío, disculpate y ofrecé el
   contacto del asesor humano (link arriba).
6. Si el estudiante pide algo que NO tenés en herramientas ni en la
   información estática, NO inventes — comparte el link del formulario
   de asesor.
7. Tu personalidad: {tono}. {personalidad}

INFORMACIÓN INSTITUCIONAL:
{contexto_estatico}

PREGUNTAS FRECUENTES (top {faqs_count}):
{faqs}

HISTORIAL RECIENTE:
{historial}

PREGUNTA DEL ESTUDIANTE:
{pregunta}

Tu respuesta:
""".strip()


HERRAMIENTAS = [
    {
        'nombre': 'consultar_actividades_semana',
        'nombre_amigable': 'Consultar actividades de la semana',
        'descripcion': (
            'Devuelve las tareas, foros, tests y actividades que el estudiante '
            'tiene pendientes esta semana, agrupadas por día. Úsala cuando el '
            'estudiante pregunte qué actividades tiene, qué tareas debe entregar, '
            'qué hay que hacer esta semana, etc.'
        ),
        'metodo': 'GET',
        'path': 'actividades-semana/',
        'plantilla_respuesta': (
            '📝 *{{data.titulo}}*\n'
            '🗓️ {{data.rango_label}}\n\n'
            'Total: *{{data.totales.total}}* ítems · '
            'Tareas {{data.totales.tareas}} · '
            'Foros {{data.totales.foros}} · '
            'Tests {{data.totales.tests}}\n\n'
            '*Pendientes por día:*\n'
            '{% for d in data.dias %}'
            '_{{d.dia_label}}_ — {{d.total}} ítems\n'
            '{% for it in d.items %}'
            '  • {{it.tipo_label}}: *{{it.titulo}}* ({{it.asignatura}}) · {{it.hora}}\n'
            '{% endfor %}'
            '{% endfor %}'
        ),
    },
    {
        'nombre': 'consultar_materias',
        'nombre_amigable': 'Consultar materias activas',
        'descripcion': (
            'Lista las materias activas en las que el estudiante está '
            'matriculado este periodo, con docente y email de cada una. '
            'Úsala cuando pregunte qué materias está cursando, quién es '
            'su profesor, cómo contactar al docente, etc.'
        ),
        'metodo': 'GET',
        'path': 'materias/',
        'plantilla_respuesta': (
            '📚 *{{data.titulo}}*\n'
            'Tienes *{{data.total}}* materias activas:\n\n'
            '{% for m in data.materias %}'
            '• *{{m.asignatura}}* — _{{m.docente}}_\n'
            '  ✉️ {{m.docente_email}}\n'
            '{% endfor %}'
            '\n🔗 Ver con Meet/Moodle/Teams: {{data.url_materias}}'
        ),
    },
    {
        'nombre': 'consultar_horarios',
        'nombre_amigable': 'Consultar horarios completos',
        'descripcion': (
            'Devuelve el horario completo del estudiante con todas las '
            'materias y sus días/horas/profesores. Úsala cuando pregunte por '
            'su horario en general, cuándo tiene clases, qué clases tiene en '
            'la semana.'
        ),
        'metodo': 'GET',
        'path': 'horarios/',
        'plantilla_respuesta': (
            '📅 *Estas son las materias que estás cursando:*\n\n'
            '{% for m in data.materias %}'
            '*{{m.asignatura}}*\n'
            '{% for h in m.horarios %}'
            '  {{h.dia}} · {{h.hora}} · _{{h.profesor}}_\n'
            '{% endfor %}'
            '\n'
            '{% endfor %}'
            '🔗 Ver horario: {{data.url_horarios}}\n'
            '🔗 Ver materias: {{data.url_materias}}'
        ),
    },
    {
        'nombre': 'consultar_horarios_hoy',
        'nombre_amigable': 'Consultar clases de hoy',
        'descripcion': (
            'Devuelve las clases que tiene el estudiante específicamente el '
            'día de hoy, con horario y profesor. Úsala cuando pregunte qué '
            'clases tiene hoy, cuál es la próxima clase, a qué hora empieza '
            'la siguiente.'
        ),
        'metodo': 'GET',
        'path': 'horarios-hoy/',
        'plantilla_respuesta': (
            '📅 *{{data.titulo}}*\n\n'
            '{% for c in data.clases %}'
            '*{{c.asignatura}}*\n'
            '🕐 {{c.hora}} · _{{c.profesor}}_\n\n'
            '{% endfor %}'
        ),
    },
    {
        'nombre': 'consultar_deudas',
        'nombre_amigable': 'Consultar deudas y rubros',
        'descripcion': (
            'Devuelve los rubros pendientes del estudiante: matrícula, '
            'pensiones, otros — con monto total, vencido, saldo y detalle. '
            'Úsala cuando pregunte por sus deudas, cuánto debe, qué le falta '
            'pagar, fechas de vencimiento, estado de un rubro.'
        ),
        'metodo': 'GET',
        'path': 'deudas/',
        'plantilla_respuesta': (
            '💲 *Resumen de tus rubros:*\n\n'
            'Total emitido: *${{data.total_rubros}}*\n'
            'Saldo pendiente: *${{data.total_saldo}}*\n'
            'Vencido: *${{data.total_vencido}}*\n\n'
            '*Detalle:*\n'
            '{% for r in data.detalle %}'
            '• {{r.nombre}}\n'
            '  Vence {{r.vence}} · saldo ${{r.saldo}} · _{{r.estado}}_\n'
            '{% endfor %}'
        ),
    },
    {
        'nombre': 'consultar_mentor',
        'nombre_amigable': 'Consultar mentor asignado',
        'descripcion': (
            'Devuelve los datos del mentor académico asignado al estudiante: '
            'nombre, email, celular, link directo de WhatsApp. Úsala cuando '
            'pregunte quién es su mentor, cómo lo contacta, si tiene mentor.'
        ),
        'metodo': 'GET',
        'path': 'mentor/',
        'plantilla_respuesta': (
            '👤 *Tu mentor asignado*\n\n'
            '• *{{data.nombre}}*\n'
            '✉️ {{data.email}}\n'
            '📱 {{data.celular}}\n\n'
            '💬 Escribirle por WhatsApp 👉 {{data.whatsapp_url}}\n'
            '📧 Mandarle email 👉 {{data.mailto_url}}'
        ),
    },
    {
        'nombre': 'consultar_contactos_academicos',
        'nombre_amigable': 'Consultar contactos académicos',
        'descripcion': (
            'Devuelve la lista de contactos académicos del estudiante '
            '(coordinador, secretaría, soporte, etc) con rol, nombre, '
            'email y celular. Úsala cuando pregunte a quién le escribe '
            'para temas académicos o administrativos específicos.'
        ),
        'metodo': 'GET',
        'path': 'contactos/',
        'plantilla_respuesta': (
            '💬 *Tus contactos académicos*\n\n'
            '{% for c in data.contactos %}'
            '👤 *{{c.rol}}:* {{c.nombre}}\n'
            '✉️ {{c.email}}\n'
            '📱 {{c.celular}}\n\n'
            '{% endfor %}'
            '🌐 Portal de procesos: {{data.url_procesos}}'
        ),
    },
]


PARAMETRO_CEDULA = {
    'nombre': 'cedula',
    'tipo': 'string',
    'descripcion': (
        'Cédula del estudiante (10 dígitos numéricos). '
        'Pedila al estudiante si todavía no la tenés en la conversación.'
    ),
    'requerido': True,
    'pregunta_sugerida': '¿Me das tu número de cédula? (10 dígitos)',
}


class Command(BaseCommand):
    help = 'Crea/actualiza el agente IA "Lucía RU IA" con las 7 herramientas HTTP del bot académico.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el agente previo y sus herramientas y recrea todo.')
        parser.add_argument('--delete', action='store_true',
                            help='Solo borra el agente y sale (no recrea).')
        parser.add_argument('--apikey', type=int, default=None,
                            help='ID de ApiKeyIA a vincular (requerido al crear).')
        parser.add_argument('--sesion', type=int, default=None,
                            help='ID de SesionWhatsApp para asignar el agente como modo_bot=ia.')
        parser.add_argument('--base-url', type=str, default=BASE_URL_DEFAULT,
                            help=f'Base URL del bot RU (default: {BASE_URL_DEFAULT}).')

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
            if not opts['apikey']:
                raise CommandError(
                    'Tenés que pasar --apikey <id> al crear el agente. '
                    'Listá las disponibles con: python manage.py shell -c '
                    '"from crm.models import ApiKeyIA; '
                    '[print(k.id, k.nombre, k.proveedor) for k in ApiKeyIA.objects.filter(status=True)]"'
                )
            try:
                apikey = ApiKeyIA.objects.get(id=opts['apikey'], status=True)
            except ApiKeyIA.DoesNotExist:
                raise CommandError(f'No existe ApiKeyIA activa con id={opts["apikey"]}')

            agente = self._crear_agente(apikey)
            self.stdout.write(self.style.SUCCESS(f'Agente creado: {agente.nombre} (id={agente.id})'))
        else:
            self.stdout.write(self.style.WARNING(f'Agente ya existe: {agente.nombre} (id={agente.id}) — actualizando.'))
            self._actualizar_agente(agente)

        base_url = opts['base_url'].rstrip('/') + '/'
        creadas, actualizadas = self._sembrar_herramientas(agente, base_url)
        self.stdout.write(self.style.SUCCESS(
            f'Herramientas: {creadas} creadas, {actualizadas} actualizadas.'
        ))

        if opts['sesion']:
            self._vincular_sesion(agente, opts['sesion'])

        self._resumen(agente)

    def _eliminar(self):
        agente = AgentesIA.objects.filter(nombre=NOMBRE_AGENTE).first()
        if not agente:
            self.stdout.write(self.style.WARNING(f'No existe agente "{NOMBRE_AGENTE}", nada para borrar.'))
            return
        SesionWhatsApp.objects.filter(agente_ia=agente).update(agente_ia=None, modo_bot='ninguno')
        agente.herramientas.all().delete()
        agente.delete()
        self.stdout.write(self.style.SUCCESS(f'Agente "{NOMBRE_AGENTE}" + herramientas eliminados.'))

    def _crear_agente(self, apikey):
        agente = AgentesIA.objects.create(
            nombre=NOMBRE_AGENTE,
            descripcion=(
                'Asistente virtual conversacional del Instituto Superior Tecnológico '
                'ISTER para estudiantes activos. Versión IA (function-calling) del '
                'bot tradicional Lucía.'
            ),
            contexto_estatico=CONTEXTO_ESTATICO,
            prompt_template=PROMPT_TEMPLATE,
            faqs_en_prompt=5,
            personalidad_preset='amable',
            nombre_bot='Lucía',
            personalidad=(
                'Soy Lucía, asistente del ISTER. Soy paciente, clara y resolutiva. '
                'Trato al estudiante de "vos" con calidez, sin formalismos exagerados. '
                'Cuando algo no lo puedo resolver, ofrezco el contacto del asesor humano.'
            ),
            tono='cercano',
            estilo_escritura=(
                'Mensajes cortos, 2-4 líneas. Emojis con mesura (1-2 por respuesta). '
                'Listas con viñetas cuando hay múltiples ítems. Nunca muestro JSON. '
                'No abro signos de interrogación dobles ni signos de exclamación dobles.'
            ),
            humanizar_timing=True,
            cfg_history_turns=8,
            cfg_max_output_tokens=2000,
        )
        agente.apikey.add(apikey)
        return agente

    def _actualizar_agente(self, agente):
        agente.contexto_estatico = CONTEXTO_ESTATICO
        agente.prompt_template = PROMPT_TEMPLATE
        agente.descripcion = (
            'Asistente virtual conversacional del Instituto Superior Tecnológico '
            'ISTER para estudiantes activos. Versión IA (function-calling) del '
            'bot tradicional Lucía.'
        )
        agente.save()

    def _sembrar_herramientas(self, agente, base_url):
        creadas = 0
        actualizadas = 0
        for spec in HERRAMIENTAS:
            url_completa = base_url + spec['path']
            defaults = {
                'nombre_amigable': spec['nombre_amigable'],
                'descripcion': spec['descripcion'],
                'metodo': spec['metodo'],
                'url': url_completa,
                'headers': {},
                'parametros': [PARAMETRO_CEDULA],
                'ubicacion_params': 'query',
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
            f'Sesión #{sesion.id} ({sesion.nombre or sesion.numero}) vinculada al agente con modo_bot=ia.'
        ))

    def _resumen(self, agente):
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('=== RESUMEN ==='))
        self.stdout.write(f'Agente: {agente.nombre} (id={agente.id})')
        self.stdout.write(f'API Keys vinculadas: {agente.apikey.count()}')
        self.stdout.write(f'Herramientas activas: {agente.herramientas.filter(activo=True, status=True).count()}')
        self.stdout.write('')
        self.stdout.write('Probá el agente desde:')
        self.stdout.write(f'  /crm/agentes_ai/?accion=editar&id={agente.id}')
        self.stdout.write('')
        self.stdout.write('Verificá tools y logs en:')
        self.stdout.write(f'  /crm/herramientas_agente/?agente={agente.id}')
        self.stdout.write('')
        self.stdout.write('Si quedó vinculado a una sesión, mandale mensajes de prueba:')
        self.stdout.write('  - "hola"')
        self.stdout.write('  - "qué tareas tengo esta semana?"   → debería pedir cédula y llamar consultar_actividades_semana')
        self.stdout.write('  - "y mis deudas?"                   → reusar cédula, llamar consultar_deudas')
        self.stdout.write('  - "necesito hablar con un asesor"   → debería compartir el link del formulario')
        self.stdout.write('  - "cómo cambio mi clave?"           → respuesta de contexto estático, sin tool')
