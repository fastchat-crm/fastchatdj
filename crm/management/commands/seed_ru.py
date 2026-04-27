"""
Seed del flujo "Asistente Virtual RU - Lucía".

Crea un DepartamentoChatBot con su grafo de nodos listo para que el motor
`crm.motor_flujo_chatbot` lo ejecute. Replica el bot RU del ISTER pero
adaptado al motor de flujo tradicional de WhatsApp (no al bot web).

Estructura:
  - Menú raíz: estudiante / aspirante / asesor.
  - Rama estudiante: pide cédula → POST /buscar-estudiante/ → menú con
    opciones privadas (horarios, deudas, mentor, materias, contactos, etc.).
  - Rama aspirante: menú con opciones públicas (oferta pre/posgrado, becas,
    homologación, soporte).
  - Sub-menú horarios: toda la semana / hoy / próxima clase / actividades.

API base: https://ruedge.ister.edu.ec/service/v1/bot/lucia
Doc: ver `bot_apis.json` del proyecto RU.

Uso:
    python manage.py seed_ru
    python manage.py seed_ru --reset                # borra y recrea
    python manage.py seed_ru --sesion 5             # asocia a esa sesión y
                                                      pone modo_bot='tradicional'
    python manage.py seed_ru --base-url https://...  # override host
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'Asistente RU - Lucía'
BASE_URL_DEFAULT = 'https://ruedge.ister.edu.ec/service/v1/bot/lucia'


class Command(BaseCommand):
    help = 'Crea el flujo del asistente RU (Lucía) calcado a la API del bot RU.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el depto previo y lo recrea.')
        parser.add_argument('--sesion', type=int, default=None,
                            help='ID de SesionWhatsApp para asociar el flujo.')
        parser.add_argument('--base-url', type=str, default=BASE_URL_DEFAULT,
                            help=f'Base URL del bot RU (default: {BASE_URL_DEFAULT}).')
        parser.add_argument('--bearer', type=str, default='',
                            help='Token Bearer si la API ya no es AllowAny.')

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────

    def _nodo(self, depto, nombre, tipo, *, config=None, es_inicio=False,
              endpoint=None, variable=None, validacion='none', reintentos=3,
              mensaje_error='', orden=0):
        return OpcionDepartamentoChatBot.objects.create(
            departamento=depto,
            nombre=nombre,
            tipo_nodo=tipo,
            config=config or {},
            es_inicio=es_inicio,
            endpoint=endpoint,
            variable_destino=variable or '',
            validacion_tipo=validacion,
            mensaje_error=mensaje_error,
            reintentos_max=reintentos,
            orden=orden,
        )

    def _conectar(self, origen, destino, etiqueta='', orden=0, descripcion=''):
        return ConexionNodoChatbot.objects.create(
            nodo_origen=origen,
            nodo_destino=destino,
            etiqueta=etiqueta,
            orden=orden,
            descripcion=descripcion,
        )

    # ─────────────────────────────────────────────────────────────
    # Main
    # ─────────────────────────────────────────────────────────────

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['reset']:
            from crm.models import EstadoFlujoChatbot
            viejos = DepartamentoChatBot.objects.filter(nombre=NOMBRE_DEPTO)
            n_estados = EstadoFlujoChatbot.objects.filter(departamento__in=viejos).count()
            EstadoFlujoChatbot.objects.filter(departamento__in=viejos).delete()
            viejos.delete()
            self.stdout.write(self.style.WARNING(
                f'Depto "{NOMBRE_DEPTO}" previo eliminado '
                f'({n_estados} estados runtime también borrados).'
            ))
            huerfanos = EstadoFlujoChatbot.objects.filter(departamento__isnull=True)
            if huerfanos.exists():
                n = huerfanos.count()
                huerfanos.delete()
                self.stdout.write(self.style.WARNING(
                    f'  + {n} estados huérfanos sin depto también eliminados.'
                ))

        depto, creado = DepartamentoChatBot.objects.get_or_create(
            nombre=NOMBRE_DEPTO,
            defaults={
                'color': '#0a3d62',
                'mensaje_saludo': (
                    '🎓 ¡Hola! Soy *Lucía* 🤖, asistente virtual del RU. '
                    'Estoy aquí para ayudarte con tus consultas académicas. ✨'
                ),
                'palabras_clave': (
                    'lucia\nlucía\nru\nister\nestudiante\nmatricula\n'
                    'horarios\ndeudas\nmentor\nbecas'
                ),
                'es_default': False,
                'activo_tradicional': True,
            },
        )
        if not creado:
            self.stdout.write(self.style.WARNING(
                'El depto ya existía. Usa --reset para recrearlo desde cero.'
            ))
            return

        # ── Credencial + endpoint único ─────────────────────────
        if opts.get('bearer'):
            credencial = CredencialApiChatbot.objects.create(
                nombre='Bot RU - Bearer',
                tipo='bearer',
                secretos={'token': opts['bearer']},
                descripcion='Token Bearer del bot RU.',
            )
        else:
            credencial = CredencialApiChatbot.objects.create(
                nombre='Bot RU - AllowAny',
                tipo='none',
                secretos={},
                descripcion='APIs del bot RU actualmente públicas (AllowAny).',
            )
        ep_ru = EndpointApiChatbot.objects.create(
            nombre='Bot RU Lucía',
            base_url=opts['base_url'].rstrip('/'),
            credencial=credencial,
            headers_default={'Accept': 'application/json'},
            timeout_seg=15,
            descripcion='Endpoint base del bot RU del ISTER.',
        )

        # ─────────────────────────────────────────────────────────
        # NODOS: MENÚ RAÍZ
        # ─────────────────────────────────────────────────────────
        menu = self._nodo(
            depto, 'Menú principal', 'menu', es_inicio=True, orden=0,
            config={
                'mensaje': '¿Cómo te puedo ayudar hoy?',
                'opciones': [
                    {'etiqueta': 'Soy estudiante (matriculado)', 'valor': 'estudiante', 'salida': 'estudiante'},
                    {'etiqueta': 'Soy aspirante / invitado',     'valor': 'aspirante',  'salida': 'aspirante'},
                    {'etiqueta': 'Hablar con un asesor',         'valor': 'asesor',     'salida': 'asesor'},
                ],
            },
            variable='tipo_usuario',
            mensaje_error='Elige 1, 2 o 3 para continuar.',
        )

        # ─────────────────────────────────────────────────────────
        # RAMA ESTUDIANTE: pedir cédula → buscar → menú estudiante
        # ─────────────────────────────────────────────────────────
        p_cedula = self._nodo(
            depto, 'Pedir cédula', 'pregunta', orden=10,
            config={'pregunta': '🪪 Por favor ingresa tu *número de cédula* (10 dígitos):'},
            variable='cedula', validacion='cedula', reintentos=3,
            mensaje_error='La cédula no parece válida. Vuelve a intentarlo (10 dígitos, sólo números).',
        )
        http_buscar = self._nodo(
            depto, 'Buscar estudiante', 'http', orden=11,
            endpoint=ep_ru,
            config={
                'metodo': 'POST',
                'path': '/buscar-estudiante/',
                'body': {'cedula': '{{variables.cedula}}'},
                'extraer': [
                    {'variable': 'nombre',       'jsonpath': 'data.nombre'},
                    {'variable': 'matricula_id', 'jsonpath': 'data.matriculas[0].id'},
                    {'variable': 'carrera',      'jsonpath': 'data.matriculas[0].carrera'},
                    {'variable': 'nivel',        'jsonpath': 'data.matriculas[0].nivel'},
                    {'variable': 'periodo',      'jsonpath': 'data.matriculas[0].periodo'},
                ],
                'plantilla_respuesta': (
                    '✅ Hola *{{variables.nombre}}* 👋\n'
                    '🎓 {{variables.carrera}} · {{variables.nivel}}\n'
                    '📅 Período: {{variables.periodo}}'
                ),
            },
        )
        no_encontrado = self._nodo(
            depto, 'Estudiante no encontrado', 'respuesta', orden=12,
            config={'mensaje': (
                '🔎 No encontré información registrada con esa cédula.\n'
                'Te llevo al menú de aspirantes — si crees que es un error, '
                'comunícate con tu coordinación de carrera.'
            )},
        )

        menu_est = self._nodo(
            depto, 'Menú estudiante', 'menu', orden=20,
            config={
                'mensaje': '¿Qué te gustaría consultar?',
                'opciones': [
                    {'etiqueta': '📅 Mis horarios',         'valor': 'horarios',    'salida': 'horarios'},
                    {'etiqueta': '📚 Mis materias',         'valor': 'materias',    'salida': 'materias'},
                    {'etiqueta': '📝 Actividades semana',   'valor': 'actividades', 'salida': 'actividades'},
                    {'etiqueta': '💲 Mis deudas',           'valor': 'deudas',      'salida': 'deudas'},
                    {'etiqueta': '👤 Mi mentor',            'valor': 'mentor',      'salida': 'mentor'},
                    {'etiqueta': '📞 Contactos académicos', 'valor': 'contactos',   'salida': 'contactos'},
                    {'etiqueta': '🚪 ¿Cómo entro a clases?','valor': 'ingreso',     'salida': 'ingreso'},
                    {'etiqueta': '🔐 Cambiar contraseña',   'valor': 'pass',        'salida': 'pass'},
                    {'etiqueta': '🎧 Soporte general',      'valor': 'soporte',     'salida': 'soporte'},
                ],
            },
            variable='opcion_estudiante',
            mensaje_error='Elige el número de la opción.',
        )

        # ── Sub-menú HORARIOS ────────────────────────────────────
        menu_horarios = self._nodo(
            depto, 'Sub-menú horarios', 'menu', orden=30,
            config={
                'mensaje': '📅 ¿Qué horario quieres ver?',
                'opciones': [
                    {'etiqueta': 'Toda la semana',     'valor': 'semana',  'salida': 'semana'},
                    {'etiqueta': 'Solo mis clases hoy','valor': 'hoy',     'salida': 'hoy'},
                    {'etiqueta': 'Mi próxima clase',   'valor': 'proxima', 'salida': 'proxima'},
                    {'etiqueta': 'Actividades semana', 'valor': 'activ',   'salida': 'activ'},
                ],
            },
            variable='opcion_horario',
            mensaje_error='Elige una opción del 1 al 4.',
        )
        http_horarios = self._nodo(
            depto, 'GET /horarios/', 'http', orden=31, endpoint=ep_ru,
            config={
                'metodo': 'GET',
                'path': '/horarios/',
                'query': {
                    'cedula': '{{variables.cedula}}',
                    'matricula_id': '{{variables.matricula_id}}',
                },
                'extraer': [
                    {'variable': 'h_url',     'jsonpath': 'data.url_horarios'},
                    {'variable': 'h_primera', 'jsonpath': 'data.materias[0].asignatura'},
                ],
                'plantilla_respuesta': (
                    '📅 *Tus horarios de la semana*\n'
                    'Primera materia: {{variables.h_primera}}\n\n'
                    'Ver horario completo aquí 👉 {{variables.h_url}}'
                ),
            },
        )
        http_horarios_hoy = self._nodo(
            depto, 'GET /horarios-hoy/', 'http', orden=32, endpoint=ep_ru,
            config={
                'metodo': 'GET',
                'path': '/horarios-hoy/',
                'query': {
                    'cedula': '{{variables.cedula}}',
                    'matricula_id': '{{variables.matricula_id}}',
                },
                'extraer': [
                    {'variable': 'titulo',    'jsonpath': 'data.titulo'},
                    {'variable': 'primera',   'jsonpath': 'data.clases[0].asignatura'},
                    {'variable': 'hora',      'jsonpath': 'data.clases[0].hora'},
                    {'variable': 'profesor',  'jsonpath': 'data.clases[0].profesor'},
                ],
                'plantilla_respuesta': (
                    '📅 *{{variables.titulo}}*\n'
                    '• {{variables.primera}}\n'
                    '🕐 {{variables.hora}}\n'
                    '👤 {{variables.profesor}}'
                ),
            },
        )
        http_proxima = self._nodo(
            depto, 'GET /proxima-clase/', 'http', orden=33, endpoint=ep_ru,
            config={
                'metodo': 'GET',
                'path': '/proxima-clase/',
                'query': {
                    'cedula': '{{variables.cedula}}',
                    'matricula_id': '{{variables.matricula_id}}',
                },
                'extraer': [
                    {'variable': 'asig',  'jsonpath': 'data.proxima_clase.asignatura'},
                    {'variable': 'dia',   'jsonpath': 'data.proxima_clase.dia'},
                    {'variable': 'hora',  'jsonpath': 'data.proxima_clase.hora'},
                    {'variable': 'prof',  'jsonpath': 'data.proxima_clase.profesor'},
                ],
                'plantilla_respuesta': (
                    '⏭️ *Tu próxima clase*\n'
                    '📚 {{variables.asig}}\n'
                    '📆 {{variables.dia}}, {{variables.hora}}\n'
                    '👤 {{variables.prof}}'
                ),
            },
        )
        http_actividades = self._nodo(
            depto, 'GET /actividades-semana/', 'http', orden=34, endpoint=ep_ru,
            config={
                'metodo': 'GET',
                'path': '/actividades-semana/',
                'query': {
                    'cedula': '{{variables.cedula}}',
                    'matricula_id': '{{variables.matricula_id}}',
                },
                'extraer': [
                    {'variable': 'titulo',   'jsonpath': 'data.titulo'},
                    {'variable': 'rango',    'jsonpath': 'data.rango_label'},
                    {'variable': 'tot',      'jsonpath': 'data.totales.total'},
                    {'variable': 'tot_tar',  'jsonpath': 'data.totales.tareas'},
                    {'variable': 'tot_for',  'jsonpath': 'data.totales.foros'},
                    {'variable': 'tot_test', 'jsonpath': 'data.totales.tests'},
                ],
                'plantilla_respuesta': (
                    '📝 *{{variables.titulo}}*\n'
                    '🗓️ Semana: {{variables.rango}}\n\n'
                    'Total: *{{variables.tot}}* ítems\n'
                    '• Tareas: {{variables.tot_tar}}\n'
                    '• Foros: {{variables.tot_for}}\n'
                    '• Tests: {{variables.tot_test}}'
                ),
            },
        )

        # ── Otros nodos http privados ────────────────────────────
        http_materias = self._nodo(
            depto, 'GET /materias/', 'http', orden=40, endpoint=ep_ru,
            config={
                'metodo': 'GET',
                'path': '/materias/',
                'query': {
                    'cedula': '{{variables.cedula}}',
                    'matricula_id': '{{variables.matricula_id}}',
                },
                'extraer': [
                    {'variable': 'titulo', 'jsonpath': 'data.titulo'},
                    {'variable': 'total',  'jsonpath': 'data.total'},
                    {'variable': 'm_url',  'jsonpath': 'data.url_materias'},
                ],
                'plantilla_respuesta': (
                    '📚 *{{variables.titulo}}*\n'
                    'Tienes *{{variables.total}}* materias activas.\n\n'
                    'Ver detalle (Meet, Moodle, docentes) 👉 {{variables.m_url}}'
                ),
            },
        )
        http_deudas = self._nodo(
            depto, 'GET /deudas/', 'http', orden=41, endpoint=ep_ru,
            config={
                'metodo': 'GET',
                'path': '/deudas/',
                'query': {'cedula': '{{variables.cedula}}'},
                'extraer': [
                    {'variable': 'saldo',    'jsonpath': 'data.total_saldo'},
                    {'variable': 'vencido',  'jsonpath': 'data.total_vencido'},
                    {'variable': 'rubros',   'jsonpath': 'data.total_rubros'},
                    {'variable': 'detalle1', 'jsonpath': 'data.detalle[0].nombre'},
                    {'variable': 'estado1',  'jsonpath': 'data.detalle[0].estado'},
                ],
                'plantilla_respuesta': (
                    '💲 *Tu estado financiero*\n'
                    '• Saldo total: ${{variables.saldo}}\n'
                    '• Vencido: ${{variables.vencido}}\n'
                    '• Rubros del período: ${{variables.rubros}}\n\n'
                    'Último rubro: {{variables.detalle1}} → {{variables.estado1}}'
                ),
            },
        )
        http_mentor = self._nodo(
            depto, 'GET /mentor/', 'http', orden=42, endpoint=ep_ru,
            config={
                'metodo': 'GET',
                'path': '/mentor/',
                'query': {
                    'cedula': '{{variables.cedula}}',
                    'matricula_id': '{{variables.matricula_id}}',
                },
                'extraer': [
                    {'variable': 'm_nom',   'jsonpath': 'data.nombre'},
                    {'variable': 'm_email', 'jsonpath': 'data.email'},
                    {'variable': 'm_cel',   'jsonpath': 'data.celular'},
                    {'variable': 'm_wa',    'jsonpath': 'data.whatsapp_url'},
                ],
                'plantilla_respuesta': (
                    '👤 *Tu mentor asignado*\n'
                    '• {{variables.m_nom}}\n'
                    '✉️ {{variables.m_email}}\n'
                    '📱 {{variables.m_cel}}\n\n'
                    'Escribirle por WhatsApp 👉 {{variables.m_wa}}'
                ),
            },
        )
        http_contactos = self._nodo(
            depto, 'GET /contactos/', 'http', orden=43, endpoint=ep_ru,
            config={
                'metodo': 'GET',
                'path': '/contactos/',
                'query': {
                    'cedula': '{{variables.cedula}}',
                    'matricula_id': '{{variables.matricula_id}}',
                },
                'extraer': [
                    {'variable': 'c_men_nom', 'jsonpath': 'data.contactos[0].nombre'},
                    {'variable': 'c_men_em',  'jsonpath': 'data.contactos[0].email'},
                    {'variable': 'c_ase_nom', 'jsonpath': 'data.contactos[1].nombre'},
                    {'variable': 'c_ase_em',  'jsonpath': 'data.contactos[1].email'},
                    {'variable': 'c_proc',    'jsonpath': 'data.url_procesos'},
                ],
                'plantilla_respuesta': (
                    '📞 *Tus contactos académicos*\n\n'
                    '👤 *Mentor:* {{variables.c_men_nom}}\n'
                    '✉️ {{variables.c_men_em}}\n\n'
                    '👤 *Asesor:* {{variables.c_ase_nom}}\n'
                    '✉️ {{variables.c_ase_em}}\n\n'
                    'Portal de procesos 👉 {{variables.c_proc}}'
                ),
            },
        )

        # ── Respuestas estáticas privadas ────────────────────────
        resp_ingreso = self._nodo(
            depto, 'Cómo entrar a clases', 'respuesta', orden=50,
            config={'mensaje': (
                '🚪 *¿Cómo entro a mis clases?*\n\n'
                '1️⃣ Portal Ruedge: https://ruedge.ister.edu.ec/alu/horarios/\n'
                '2️⃣ Ingresa con tu usuario y contraseña institucional.\n'
                '3️⃣ Tutorial en video: https://www.youtube.com/watch?v=gL_4UYdYwq0\n\n'
                '💡 Si aún no apareces en *Teams* o *Aula Virtual*, tu cuenta '
                'se está procesando — puede tardar algunas horas en sincronizarse.\n\n'
                '🆘 ¿Sigue sin aparecer? Abre un ticket en https://procesos.ister.edu.ec'
            )},
        )
        resp_pass = self._nodo(
            depto, 'Cambiar contraseña', 'respuesta', orden=51,
            config={'mensaje': (
                '🔐 *Cambiar tu contraseña*\n\n'
                'Ingresa al portal oficial de Ruedge:\n'
                '👉 https://ruedge.ister.edu.ec/autenticacion/restorepass/'
            )},
        )

        # ─────────────────────────────────────────────────────────
        # RAMA INVITADO / ASPIRANTE
        # ─────────────────────────────────────────────────────────
        menu_inv = self._nodo(
            depto, 'Menú aspirante / invitado', 'menu', orden=60,
            config={
                'mensaje': '¿Qué te interesa conocer?',
                'opciones': [
                    {'etiqueta': '🎓 Oferta de pregrado',  'valor': 'pre',     'salida': 'pre'},
                    {'etiqueta': '🚀 Oferta de posgrado',  'valor': 'pos',     'salida': 'pos'},
                    {'etiqueta': '🔄 Homologar estudios',  'valor': 'homol',   'salida': 'homol'},
                    {'etiqueta': '🏆 Becas y ayudas',      'valor': 'becas',   'salida': 'becas'},
                    {'etiqueta': '📩 Que un asesor me contacte', 'valor': 'ases', 'salida': 'ases'},
                    {'etiqueta': '🎧 Soporte general',     'valor': 'soporte', 'salida': 'soporte'},
                ],
            },
            variable='opcion_invitado',
            mensaje_error='Elige el número de la opción.',
        )
        resp_pre = self._nodo(
            depto, 'Oferta pregrado', 'respuesta', orden=61,
            config={'mensaje': (
                '🎓 *Oferta de pregrado*\n\n'
                'Conoce nuestras tecnologías superiores y carreras: modalidades, '
                'horarios, requisitos y costos en un solo lugar.\n\n'
                '👉 https://admisiones.ister.edu.ec/admision-pregrado/'
            )},
        )
        resp_pos = self._nodo(
            depto, 'Oferta posgrado', 'respuesta', orden=62,
            config={'mensaje': (
                '🚀 *Oferta de posgrado*\n\n'
                '¿Buscas aumentar tu nivel académico y profesional? Conoce '
                'especializaciones, maestrías y programas avanzados.\n\n'
                '👉 https://admisiones.ister.edu.ec/admision-posgrados/'
            )},
        )
        resp_homol = self._nodo(
            depto, 'Homologación', 'respuesta', orden=63,
            config={'mensaje': (
                '🔄 *Homologar estudios*\n\n'
                'Si vienes de otra institución y quieres convalidar tus materias '
                'aprobadas en el ISTER, gestiona tu homologación aquí:\n\n'
                '👉 https://homologacion.ister.edu.ec'
            )},
        )
        resp_becas = self._nodo(
            depto, 'Sistema de becas', 'respuesta', orden=64,
            config={'mensaje': (
                '🏆 *Becas y ayudas económicas*\n\n'
                'En el ISTER creemos que el talento merece oportunidades. 💚\n'
                'Tipos de beca, requisitos, plazos y cómo postular:\n\n'
                '👉 https://ister.edu.ec/sistema-de-becas-y-ayudas-economicas/'
            )},
        )
        resp_asesor = self._nodo(
            depto, 'Asesor de contacto', 'respuesta', orden=65,
            config={'mensaje': (
                '📩 *Quiero que un asesor me contacte*\n\n'
                'Completa este formulario y un asesor del ISTER se pondrá en '
                'contacto contigo a la brevedad por el medio que prefieras.\n\n'
                '👉 https://admisiones.ister.edu.ec/?action=ver&id=OPPQQRRSSTTUUVVWWXXX'
            )},
        )
        resp_soporte = self._nodo(
            depto, 'Soporte general', 'respuesta', orden=66,
            config={'mensaje': (
                '🎧 *Soporte general*\n\n'
                'Si necesitas soporte académico o administrativo, abre un '
                'trámite formal en nuestro Balcón de Servicios. El equipo '
                'del RU te dará seguimiento personalizado.\n\n'
                '👉 https://procesos.ister.edu.ec\n'
                '🌐 https://ister.edu.ec'
            )},
        )

        # ── Cierre / handoff humano ─────────────────────────────
        handoff = self._nodo(
            depto, 'Transferir a asesor', 'handoff', orden=90,
            config={'mensaje': (
                '👤 Te conecto con un asesor humano del RU. Un momento por favor…'
            )},
        )
        fin_estudiante = self._nodo(
            depto, 'Fin (estudiante)', 'fin', orden=91,
            config={'mensaje': (
                '¿Necesitas algo más? Escribe *menu* para volver al inicio.'
            )},
        )
        fin_invitado = self._nodo(
            depto, 'Fin (invitado)', 'fin', orden=92,
            config={'mensaje': (
                '¿Algo más? Escribe *menu* para volver al inicio o *asesor* '
                'si quieres hablar con un humano.'
            )},
        )
        fin_error = self._nodo(
            depto, 'Error API', 'respuesta', orden=93,
            config={'mensaje': (
                '⚠️ No pude consultar tus datos en este momento. Intenta más '
                'tarde o escribe *asesor* para hablar con alguien.'
            )},
        )

        # ─────────────────────────────────────────────────────────
        # CONEXIONES
        # ─────────────────────────────────────────────────────────
        # Menú raíz → ramas
        self._conectar(menu, p_cedula,  'estudiante', 1)
        self._conectar(menu, menu_inv,  'aspirante',  2)
        self._conectar(menu, handoff,   'asesor',     3)
        self._conectar(menu, handoff,   'timeout',    4, 'Reintentos agotados → asesor')

        # Rama estudiante: cédula → buscar → menú estudiante
        self._conectar(p_cedula,    http_buscar,    '',        1)
        self._conectar(p_cedula,    handoff,        'timeout', 2, 'Cédula inválida 3 veces')
        self._conectar(http_buscar, menu_est,       'ok',      1)
        self._conectar(http_buscar, no_encontrado,  'error',   2)
        self._conectar(no_encontrado, menu_inv,     '',        1)

        # Menú estudiante → ramas
        self._conectar(menu_est, menu_horarios, 'horarios',    1)
        self._conectar(menu_est, http_materias, 'materias',    2)
        self._conectar(menu_est, http_actividades, 'actividades', 3)
        self._conectar(menu_est, http_deudas,   'deudas',      4)
        self._conectar(menu_est, http_mentor,   'mentor',      5)
        self._conectar(menu_est, http_contactos,'contactos',   6)
        self._conectar(menu_est, resp_ingreso,  'ingreso',     7)
        self._conectar(menu_est, resp_pass,     'pass',        8)
        self._conectar(menu_est, resp_soporte,  'soporte',     9)
        self._conectar(menu_est, handoff,       'timeout',    10)

        # Sub-menú horarios
        self._conectar(menu_horarios, http_horarios,     'semana',  1)
        self._conectar(menu_horarios, http_horarios_hoy, 'hoy',     2)
        self._conectar(menu_horarios, http_proxima,      'proxima', 3)
        self._conectar(menu_horarios, http_actividades,  'activ',   4)
        self._conectar(menu_horarios, handoff,           'timeout', 5)

        # HTTP estudiantes → fin / error
        for n in (http_horarios, http_horarios_hoy, http_proxima,
                  http_actividades, http_materias, http_deudas,
                  http_mentor, http_contactos):
            self._conectar(n, fin_estudiante, 'ok',    1)
            self._conectar(n, fin_error,      'error', 2)

        # Estáticos privados → fin estudiante
        self._conectar(resp_ingreso, fin_estudiante, '', 1)
        self._conectar(resp_pass,    fin_estudiante, '', 1)
        self._conectar(resp_soporte, fin_estudiante, '', 1)
        self._conectar(fin_error,    fin_estudiante, '', 1)

        # Menú invitado → ramas
        self._conectar(menu_inv, resp_pre,     'pre',     1)
        self._conectar(menu_inv, resp_pos,     'pos',     2)
        self._conectar(menu_inv, resp_homol,   'homol',   3)
        self._conectar(menu_inv, resp_becas,   'becas',   4)
        self._conectar(menu_inv, resp_asesor,  'ases',    5)
        self._conectar(menu_inv, resp_soporte, 'soporte', 6)
        self._conectar(menu_inv, handoff,      'timeout', 7)

        # Estáticos invitado → fin invitado
        for n in (resp_pre, resp_pos, resp_homol, resp_becas, resp_asesor):
            self._conectar(n, fin_invitado, '', 1)

        # ── Asociar a una sesión si se pidió ─────────────────────
        if opts.get('sesion'):
            from whatsapp.models import SesionWhatsApp
            try:
                s = SesionWhatsApp.objects.get(pk=opts['sesion'])
            except SesionWhatsApp.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f'Sesión #{opts["sesion"]} no existe. Asocia el depto manualmente.'
                ))
            else:
                s.departamentos.add(depto)
                if not s.departamento_default:
                    s.departamento_default = depto
                if s.modo_bot == 'ia':
                    s.modo_bot = 'tradicional'
                s.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Sesión "{s.nombre or s.session_id}" asociada al depto. '
                    f'modo_bot={s.modo_bot}, departamento_default={s.departamento_default.nombre}'
                ))

        total_nodos = depto.opciondepartamentochatbot_set.count()
        total_conns = ConexionNodoChatbot.objects.filter(nodo_origen__departamento=depto).count()
        self.stdout.write(self.style.SUCCESS(
            f'\n[OK] Flujo creado: "{depto.nombre}"\n'
            f'   Nodos: {total_nodos}  |  Conexiones: {total_conns}\n'
            f'   Endpoint: {ep_ru.nombre} -> {ep_ru.base_url}\n'
            f'   Credencial: {credencial.nombre} ({credencial.get_tipo_display()})\n\n'
            f'Puede coexistir este depto con "Centro de Atencion Estudiantil"\n'
            f'asociando cada uno a sesiones distintas (o al mismo, con palabras\n'
            f'clave separadas: "lucia"/"ru" -> este, otras keywords -> el otro).\n\n'
            f'Siguiente: si la API ya pide auth, vuelve a correr con --bearer "<token>".'
        ))
