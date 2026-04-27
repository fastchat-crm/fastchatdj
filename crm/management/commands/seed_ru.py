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
                    {'etiqueta': 'Soy estudiante',     'valor': 'estudiante', 'salida': 'estudiante'},
                    {'etiqueta': 'Soy aspirante',      'valor': 'aspirante',  'salida': 'aspirante'},
                    {'etiqueta': 'Hablar con asesor',  'valor': 'asesor',     'salida': 'asesor'},
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

        # Menú estudiante: mismo orden que el JSON original del bot RU.
        # Etiquetas ≤24 chars (límite Meta para list rows).
        menu_est = self._nodo(
            depto, 'Menú estudiante', 'menu', orden=20,
            config={
                'mensaje': '¿Qué te gustaría consultar?',
                'opciones': [
                    {'etiqueta': '🚪 Entrar a clases',    'valor': 'ingreso',     'salida': 'ingreso'},
                    {'etiqueta': '📝 Actividades semana', 'valor': 'actividades', 'salida': 'actividades'},
                    {'etiqueta': '📚 Mis materias',       'valor': 'materias',    'salida': 'materias'},
                    {'etiqueta': '📅 Mis horarios',       'valor': 'horarios',    'salida': 'horarios'},
                    {'etiqueta': '💲 Mis deudas',         'valor': 'deudas',      'salida': 'deudas'},
                    {'etiqueta': '👤 Mi mentor',          'valor': 'mentor',      'salida': 'mentor'},
                    {'etiqueta': '🔐 Cambiar clave',      'valor': 'pass',        'salida': 'pass'},
                    {'etiqueta': '💬 Otra pregunta',      'valor': 'contactos',   'salida': 'contactos'},
                    {'etiqueta': '🎧 Soporte',            'valor': 'soporte',     'salida': 'soporte'},
                ],
            },
            variable='opcion_estudiante',
            mensaje_error='Elige el número de la opción.',
        )

        # ── Sub-menú HORARIOS (subpreguntas de "Mis horarios") ────
        # Replica la estructura del JSON: ver_horarios tiene 2 subpreguntas:
        #   - ver_horarios_hoy
        #   - ver_actividades_semana
        # Se presenta DESPUÉS de ejecutar /horarios/ (handler padre).
        menu_horarios = self._nodo(
            depto, 'Sub-preguntas horarios', 'menu', orden=30,
            config={
                'mensaje': '¿Quieres ver algo más específico?',
                'opciones': [
                    {'etiqueta': 'Clases de hoy',      'valor': 'hoy',    'salida': 'hoy'},
                    {'etiqueta': 'Actividades semana', 'valor': 'activ',  'salida': 'activ'},
                    {'etiqueta': 'Volver al menú',     'valor': 'volver', 'salida': 'volver'},
                ],
            },
            variable='opcion_horario',
            mensaje_error='Elige una opción.',
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
                    {'etiqueta': '🎓 Pregrado',         'valor': 'pre',     'salida': 'pre'},
                    {'etiqueta': '🚀 Posgrado',         'valor': 'pos',     'salida': 'pos'},
                    {'etiqueta': '🔄 Homologación',     'valor': 'homol',   'salida': 'homol'},
                    {'etiqueta': '🏆 Becas y ayudas',   'valor': 'becas',   'salida': 'becas'},
                    {'etiqueta': '📩 Asesor me contacta','valor': 'ases',   'salida': 'ases'},
                    {'etiqueta': '🎧 Soporte',          'valor': 'soporte', 'salida': 'soporte'},
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

        # Menú estudiante → ramas (orden = JSON original del bot RU).
        self._conectar(menu_est, resp_ingreso,     'ingreso',     1)
        self._conectar(menu_est, http_actividades, 'actividades', 2)
        self._conectar(menu_est, http_materias,    'materias',    3)
        self._conectar(menu_est, http_horarios,    'horarios',    4)
        self._conectar(menu_est, http_deudas,      'deudas',      5)
        self._conectar(menu_est, http_mentor,      'mentor',      6)
        self._conectar(menu_est, resp_pass,        'pass',        7)
        self._conectar(menu_est, http_contactos,   'contactos',   8)
        self._conectar(menu_est, resp_soporte,     'soporte',     9)
        self._conectar(menu_est, handoff,          'timeout',    10)

        # ver_horarios (handler padre) → muestra resumen → sub-preguntas
        self._conectar(http_horarios, menu_horarios, 'ok',    1)
        self._conectar(http_horarios, fin_error,     'error', 2)

        # Sub-preguntas de horarios
        self._conectar(menu_horarios, http_horarios_hoy, 'hoy',     1)
        self._conectar(menu_horarios, http_actividades,  'activ',   2)
        self._conectar(menu_horarios, menu_est,          'volver',  3)
        self._conectar(menu_horarios, fin_estudiante,    'timeout', 4)

        # Resto de HTTPs estudiantes → fin / error (sin http_horarios y
        # http_actividades/http_horarios_hoy: estos terminan en fin_estudiante
        # tras la sub-pregunta).
        for n in (http_horarios_hoy, http_actividades, http_materias,
                  http_deudas, http_mentor, http_contactos):
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
