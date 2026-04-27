"""
Seed del flujo "Asistente Virtual RU - Lucía".

Modelo "1 solo agente, todo en uno":
  - Un único `DepartamentoChatBot` con UN menú raíz que lista las 14 opciones
    del bot RU (mismo orden que el JSON original).
  - Opciones públicas (sin cédula) → respuesta estática → vuelve al menú.
  - Opciones privadas (requieren cédula) → mini-rama:
        cond_skip (¿ya tengo cédula?)
            true  → http_X         (saltea pedir cédula)
            false → pregunta_cedula → http_buscar → http_X
    Tras http_X → vuelve al menú raíz.
  - `ver_horarios` (handler con sub-preguntas) → tras /horarios/ presenta
    sub-menú "Solo hoy / Actividades semana / Volver" — cada sub-opción
    también es una mini-rama privada que reaprovecha la cédula.
  - Tras una respuesta o handler exitoso, el flujo regresa SIEMPRE al menú
    raíz para "nueva consulta".

API base: https://ruedge.ister.edu.ec/service/v1/bot/lucia

Uso:
    python manage.py seed_ru
    python manage.py seed_ru --reset
    python manage.py seed_ru --sesion 5
    python manage.py seed_ru --bearer "<token>"
    python manage.py seed_ru --base-url https://...
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'Asistente RU - Lucía'
# El bot tiene codigo "ru" en la API (no "lucia"). La URL incluye codigo_bot.
BASE_URL_DEFAULT = 'https://ruedge.ister.edu.ec/service/v1/bot/ru'


# Descriptor de los 14 procedimientos del JSON original.
# Cada item declara qué nodos genera el seed y cómo se conectan al menú.
# Tipos:
#   'estatico': respuesta estática (sin cédula).
#   'http': llamada API (requiere o no cédula según `requiere_cedula`).
#   'http_con_submenu': como 'http' pero tras la API presenta sub-menú.
PROCEDIMIENTOS = [
    {
        'codigo': 'ingreso', 'orden': 1,
        'etiqueta': '🚪 Entrar a clases',
        'tipo': 'estatico',
        'mensaje': (
            '🚪 *¿Cómo entro a mis clases?*\n\n'
            '1️⃣ Portal Ruedge: https://ruedge.ister.edu.ec/alu/horarios/\n'
            '2️⃣ Ingresa con tu usuario y contraseña institucional.\n'
            '3️⃣ Tutorial: https://www.youtube.com/watch?v=gL_4UYdYwq0\n\n'
            '💡 Si aún no apareces en *Teams* o *Aula Virtual*, tu cuenta '
            'se está procesando — puede tardar algunas horas.\n\n'
            '🆘 Sigue sin aparecer? Abre un ticket: https://procesos.ister.edu.ec'
        ),
    },
    {
        'codigo': 'actividades', 'orden': 2,
        'etiqueta': '📝 Actividades semana',
        'tipo': 'http', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/actividades-semana/',
        'extraer': [
            {'variable': 'a_titulo',  'jsonpath': 'data.titulo'},
            {'variable': 'a_rango',   'jsonpath': 'data.rango_label'},
            {'variable': 'a_totales', 'jsonpath': 'data.totales'},
            {'variable': 'a_dias',    'jsonpath': 'data.dias'},
        ],
        'plantilla': (
            '📝 *{{variables.a_titulo}}*\n'
            '🗓️ {{variables.a_rango}}\n\n'
            'Resumen: *{{variables.a_totales.total}}* ítems · '
            'Tareas {{variables.a_totales.tareas}} · '
            'Foros {{variables.a_totales.foros}} · '
            'Tests {{variables.a_totales.tests}}\n\n'
            '*Pendientes por día:*\n'
            '{% for d in variables.a_dias %}'
            '_{{d.dia_label}}_ — {{d.total}} ítems\n'
            '{% for it in d.items %}'
            '  • {{it.tipo_label}}: *{{it.titulo}}* ({{it.asignatura}}) · {{it.hora}}\n'
            '{% endfor %}'
            '{% endfor %}'
        ),
    },
    {
        'codigo': 'materias', 'orden': 3,
        'etiqueta': '📚 Mis materias',
        'tipo': 'http', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/materias/',
        'extraer': [
            {'variable': 'm_titulo',   'jsonpath': 'data.titulo'},
            {'variable': 'm_total',    'jsonpath': 'data.total'},
            {'variable': 'm_url',      'jsonpath': 'data.url_materias'},
            {'variable': 'm_lista',    'jsonpath': 'data.materias'},
        ],
        'plantilla': (
            '📚 *{{variables.m_titulo}}*\n'
            'Tienes *{{variables.m_total}}* materias activas:\n\n'
            '{% for m in variables.m_lista %}'
            '• *{{m.asignatura}}* — _{{m.docente}}_\n'
            '  ✉️ {{m.docente_email}}\n'
            '{% endfor %}'
            '\n🔗 Ver con Meet/Moodle/Teams: {{variables.m_url}}'
        ),
    },
    {
        'codigo': 'horarios', 'orden': 4,
        'etiqueta': '📅 Mis horarios',
        'tipo': 'http_con_submenu', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/horarios/',
        'extraer': [
            {'variable': 'h_url',     'jsonpath': 'data.url_horarios'},
            {'variable': 'h_url_mat', 'jsonpath': 'data.url_materias'},
            {'variable': 'h_lista',   'jsonpath': 'data.materias'},
        ],
        'plantilla': (
            '📅 *Estas son las materias que estás cursando:*\n\n'
            '{% for m in variables.h_lista %}'
            '*{{m.asignatura}}*\n'
            '{% for h in m.horarios %}'
            '  {{h.dia}} · {{h.hora}} · _{{h.profesor}}_\n'
            '{% endfor %}'
            '\n'
            '{% endfor %}'
            '🔗 Ver horario: {{variables.h_url}}\n'
            '🔗 Ver materias: {{variables.h_url_mat}}'
        ),
        'submenu': {
            'mensaje': '¿Quieres ver algo más específico?',
            'opciones': [
                {
                    'codigo': 'horarios_hoy',
                    'etiqueta': 'Clases de hoy',
                    'metodo': 'GET', 'path': '/horarios-hoy/',
                    'extraer': [
                        {'variable': 'h_titulo',  'jsonpath': 'data.titulo'},
                        {'variable': 'h_clases',  'jsonpath': 'data.clases'},
                    ],
                    'plantilla': (
                        '📅 *{{variables.h_titulo}}*\n\n'
                        '{% for c in variables.h_clases %}'
                        '*{{c.asignatura}}*\n'
                        '🕐 {{c.hora}} · _{{c.profesor}}_\n\n'
                        '{% endfor %}'
                    ),
                },
                {
                    'codigo': 'horarios_actividades',
                    'etiqueta': 'Actividades semana',
                    'metodo': 'GET', 'path': '/actividades-semana/',
                    'extraer': [
                        {'variable': 'a_titulo',  'jsonpath': 'data.titulo'},
                        {'variable': 'a_rango',   'jsonpath': 'data.rango_label'},
                        {'variable': 'a_tot',     'jsonpath': 'data.totales.total'},
                        {'variable': 'a_tot_tar', 'jsonpath': 'data.totales.tareas'},
                        {'variable': 'a_tot_for', 'jsonpath': 'data.totales.foros'},
                    ],
                    'plantilla': (
                        '📝 *{{variables.a_titulo}}*\n'
                        '🗓️ {{variables.a_rango}}\n\n'
                        'Total: *{{variables.a_tot}}* ítems · '
                        'Tareas: {{variables.a_tot_tar}} · Foros: {{variables.a_tot_for}}'
                    ),
                },
            ],
        },
    },
    {
        'codigo': 'deudas', 'orden': 5,
        'etiqueta': '💲 Mis deudas',
        'tipo': 'http', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/deudas/',
        'sin_matricula': True,
        'extraer': [
            {'variable': 'd_saldo',   'jsonpath': 'data.total_saldo'},
            {'variable': 'd_vencido', 'jsonpath': 'data.total_vencido'},
            {'variable': 'd_rubros',  'jsonpath': 'data.total_rubros'},
            {'variable': 'd_lista',   'jsonpath': 'data.detalle'},
        ],
        'plantilla': (
            '💲 *Resumen de tus rubros:*\n\n'
            'Total emitido: *${{variables.d_rubros}}*\n'
            'Saldo pendiente: *${{variables.d_saldo}}*\n'
            'Vencido: *${{variables.d_vencido}}*\n\n'
            '*Detalle:*\n'
            '{% for r in variables.d_lista %}'
            '• {{r.nombre}}\n'
            '  Vence {{r.vence}} · saldo ${{r.saldo}} · _{{r.estado}}_\n'
            '{% endfor %}'
        ),
    },
    {
        'codigo': 'mentor', 'orden': 6,
        'etiqueta': '👤 Mi mentor',
        'tipo': 'http', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/mentor/',
        'extraer': [
            {'variable': 'm_tiene', 'jsonpath': 'data.tiene_mentor'},
            {'variable': 'm_nom',   'jsonpath': 'data.nombre'},
            {'variable': 'm_email', 'jsonpath': 'data.email'},
            {'variable': 'm_cel',   'jsonpath': 'data.celular'},
            {'variable': 'm_wa',    'jsonpath': 'data.whatsapp_url'},
            {'variable': 'm_mail',  'jsonpath': 'data.mailto_url'},
        ],
        'plantilla': (
            '👤 *Tu mentor asignado*\n\n'
            '• *{{variables.m_nom}}*\n'
            '✉️ {{variables.m_email}}\n'
            '📱 {{variables.m_cel}}\n\n'
            '💬 Escribirle por WhatsApp 👉 {{variables.m_wa}}\n'
            '📧 Mandarle email 👉 {{variables.m_mail}}'
        ),
    },
    {
        'codigo': 'pass', 'orden': 7,
        'etiqueta': '🔐 Cambiar clave',
        'tipo': 'estatico',
        'mensaje': (
            '🔐 *Cambiar tu contraseña*\n\n'
            'Ingresa al portal oficial de Ruedge:\n'
            '👉 https://ruedge.ister.edu.ec/autenticacion/restorepass/'
        ),
    },
    {
        'codigo': 'contactos', 'orden': 8,
        'etiqueta': '💬 Otra pregunta',
        'tipo': 'http', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/contactos/',
        'extraer': [
            {'variable': 'c_lista', 'jsonpath': 'data.contactos'},
            {'variable': 'c_proc',  'jsonpath': 'data.url_procesos'},
        ],
        'plantilla': (
            '💬 *Tus contactos académicos*\n\n'
            '{% for c in variables.c_lista %}'
            '👤 *{{c.rol}}:* {{c.nombre}}\n'
            '✉️ {{c.email}}\n'
            '📱 {{c.celular}}\n\n'
            '{% endfor %}'
            '🌐 Portal de procesos: {{variables.c_proc}}'
        ),
    },
    {
        'codigo': 'asesor_contacto', 'orden': 9,
        'etiqueta': '📩 Asesor me contacta',
        'tipo': 'estatico',
        'mensaje': (
            '📩 *Quiero que un asesor me contacte*\n\n'
            'Completa este formulario y un asesor del ISTER se pondrá '
            'en contacto contigo a la brevedad.\n\n'
            '👉 https://admisiones.ister.edu.ec/?action=ver&id=OPPQQRRSSTTUUVVWWXXX'
        ),
    },
    {
        'codigo': 'pregrado', 'orden': 10,
        'etiqueta': '🎓 Oferta pregrado',
        'tipo': 'estatico',
        'mensaje': (
            '🎓 *Oferta de pregrado*\n\n'
            'Conoce nuestras tecnologías superiores y carreras: modalidades, '
            'horarios, requisitos y costos.\n\n'
            '👉 https://admisiones.ister.edu.ec/admision-pregrado/'
        ),
    },
    {
        'codigo': 'posgrado', 'orden': 11,
        'etiqueta': '🚀 Oferta posgrado',
        'tipo': 'estatico',
        'mensaje': (
            '🚀 *Oferta de posgrado*\n\n'
            '¿Buscas aumentar tu nivel académico y profesional? Especializaciones, '
            'maestrías y programas avanzados.\n\n'
            '👉 https://admisiones.ister.edu.ec/admision-posgrados/'
        ),
    },
    {
        'codigo': 'homologacion', 'orden': 12,
        'etiqueta': '🔄 Homologación',
        'tipo': 'estatico',
        'mensaje': (
            '🔄 *Homologar estudios*\n\n'
            'Si vienes de otra institución y quieres convalidar tus materias '
            'en el ISTER, gestiona tu homologación aquí:\n\n'
            '👉 https://homologacion.ister.edu.ec'
        ),
    },
    {
        'codigo': 'becas', 'orden': 13,
        'etiqueta': '🏆 Becas y ayudas',
        'tipo': 'estatico',
        'mensaje': (
            '🏆 *Becas y ayudas económicas*\n\n'
            'En el ISTER el talento merece oportunidades. 💚\n'
            'Tipos de beca, requisitos y cómo postular:\n\n'
            '👉 https://ister.edu.ec/sistema-de-becas-y-ayudas-economicas/'
        ),
    },
    {
        'codigo': 'soporte', 'orden': 14,
        'etiqueta': '🎧 Soporte general',
        'tipo': 'estatico',
        'mensaje': (
            '🎧 *Soporte general*\n\n'
            'Si necesitas soporte académico o administrativo, abre un '
            'trámite en el Balcón de Servicios:\n\n'
            '👉 https://procesos.ister.edu.ec\n'
            '🌐 https://ister.edu.ec'
        ),
    },
    {
        'codigo': 'vinculacion', 'orden': 15,
        'etiqueta': '🤝 Vinculación comunidad',
        'tipo': 'estatico',
        'mensaje': (
            '🤝 *Vinculación con la Comunidad* 🌱\n\n'
            'Aquí encontrarás todo lo relacionado con tus prácticas y '
            'oportunidades laborales. Elige el módulo que necesitas:\n\n'
            '👉 Prácticas Comunitarias:\n'
            '   https://ruedge.ister.edu.ec/alu/practicascomunitarias/\n\n'
            '👉 Prácticas Preprofesionales:\n'
            '   https://ruedge.ister.edu.ec/alu/practicaspreprofesionales/\n\n'
            '👉 Plazas Disponibles:\n'
            '   https://ruedge.ister.edu.ec/alu/plazaspracticaspreprofesionales/\n\n'
            '👉 Bolsa Laboral:\n'
            '   https://ruedge.ister.edu.ec/alu/bolsa_laboral/'
        ),
    },
]


class Command(BaseCommand):
    help = 'Crea el flujo del asistente RU (Lucía) — un solo depto, loop al menú.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el depto previo y lo recrea.')
        parser.add_argument('--delete', action='store_true',
                            help='Solo borra el depto y sale (no recrea).')
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

    def _query_para(self, proc):
        """Construye query del API.

        En esta versión del bot RU, `matricula_id` es OPCIONAL para todos los
        handlers — la API auto-selecciona la última matrícula vigente
        (prioriza pregrado vigente, fallback a cualquier vigente). Solo lo
        pasamos si el usuario explícitamente eligió otra matrícula
        (tracked en `variables.matricula_id_override`); de lo contrario,
        dejamos que el server elija para evitar pasar valores stale.
        """
        return {'cedula': '{{variables.cedula}}'}

    def _crear_rama_privada(self, depto, ep_ru, menu_raiz, salida_ok,
                            fin_error, proc, base_orden):
        """Crea solo el nodo http_X del procedimiento privado.

        En este modelo cédula+buscar son nodos GLOBALES al inicio del flujo
        (antes del menu_raiz), así que cuando llegamos acá ya tenemos
        `variables.cedula` y `variables.matricula_id` seteadas. La rama
        privada se reduce a una sola llamada API:

            menu_raiz --[salida=codigo]--> http_X
                http_X --[ok]--> salida_ok
                http_X --[error]--> fin_error
        """
        codigo = proc['codigo']
        http_x = self._nodo(
            depto, f'API {proc["metodo"]} {proc["path"]} ({codigo})', 'http',
            orden=base_orden, endpoint=ep_ru,
            config={
                'metodo': proc['metodo'],
                'path':   proc['path'],
                'query':  self._query_para(proc),
                'extraer': proc.get('extraer') or [],
                'plantilla_respuesta': proc.get('plantilla') or '',
            },
        )
        self._conectar(menu_raiz, http_x, codigo, 1)
        self._conectar(http_x, salida_ok, 'ok', 1)
        self._conectar(http_x, fin_error, 'error', 2)
        return http_x

    # ─────────────────────────────────────────────────────────────
    # Main
    # ─────────────────────────────────────────────────────────────

    def _eliminar_depto(self):
        """Borra hard-delete del depto + estados huérfanos. Devuelve resumen."""
        from crm.models import EstadoFlujoChatbot, ConexionNodoChatbot
        viejos = DepartamentoChatBot.objects.filter(nombre=NOMBRE_DEPTO)
        n_deptos = viejos.count()
        n_estados = EstadoFlujoChatbot.objects.filter(departamento__in=viejos).count()
        n_nodos = OpcionDepartamentoChatBot.objects.filter(departamento__in=viejos).count()
        n_conn = ConexionNodoChatbot.objects.filter(nodo_origen__departamento__in=viejos).count()

        EstadoFlujoChatbot.objects.filter(departamento__in=viejos).delete()
        viejos.delete()

        n_huerfanos = 0
        huerfanos = EstadoFlujoChatbot.objects.filter(departamento__isnull=True)
        if huerfanos.exists():
            n_huerfanos = huerfanos.count()
            huerfanos.delete()

        return {
            'deptos': n_deptos, 'nodos': n_nodos, 'conexiones': n_conn,
            'estados': n_estados, 'huerfanos': n_huerfanos,
        }

    @transaction.atomic
    def handle(self, *args, **opts):
        # --delete: solo borra y sale (sin recrear).
        if opts.get('delete'):
            res = self._eliminar_depto()
            if res['deptos'] == 0:
                self.stdout.write(self.style.WARNING(
                    f'No habia depto "{NOMBRE_DEPTO}" para borrar.'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'[DELETE OK] "{NOMBRE_DEPTO}" eliminado.\n'
                    f'   Deptos: {res["deptos"]} | Nodos: {res["nodos"]} | '
                    f'Conexiones: {res["conexiones"]}\n'
                    f'   Estados runtime: {res["estados"]} '
                    f'(+ {res["huerfanos"]} estados huerfanos sueltos).'
                ))
            return

        if opts['reset']:
            res = self._eliminar_depto()
            self.stdout.write(self.style.WARNING(
                f'Depto "{NOMBRE_DEPTO}" previo eliminado '
                f'({res["nodos"]} nodos, {res["conexiones"]} conexiones, '
                f'{res["estados"]} estados runtime tambien borrados).'
            ))
            if res['huerfanos']:
                self.stdout.write(self.style.WARNING(
                    f'  + {res["huerfanos"]} estados huerfanos sin depto tambien eliminados.'
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
                nombre='Bot RU - Bearer', tipo='bearer',
                secretos={'token': opts['bearer']},
                descripcion='Token Bearer del bot RU.',
            )
        else:
            credencial = CredencialApiChatbot.objects.create(
                nombre='Bot RU - AllowAny', tipo='none', secretos={},
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
        # FLUJO UPFRONT: cédula → buscar estudiante → menú
        # ─────────────────────────────────────────────────────────
        # 1) Pregunta cédula (es_inicio=True). Es el primer nodo del flujo
        #    después del saludo del depto. Replica el UX del bot RU real.
        preg_cedula = self._nodo(
            depto, 'Pedir cédula', 'pregunta', es_inicio=True, orden=0,
            config={'pregunta': (
                '🪪 Para atenderte necesito tu *número de cédula*. '
                'Por favor ingrésalo para continuar. 🙂'
            )},
            variable='cedula', validacion='cedula', reintentos=3,
            mensaje_error='Cédula inválida. Vuelve a intentarlo (10 dígitos).',
        )
        # 2) Buscar estudiante: extrae datos + matrícula activa.
        http_buscar = self._nodo(
            depto, 'Buscar estudiante', 'http', orden=1, endpoint=ep_ru,
            config={
                'metodo': 'POST', 'path': '/buscar-estudiante/',
                'body': {'cedula': '{{variables.cedula}}'},
                'extraer': [
                    {'variable': 'nombre',          'jsonpath': 'data.nombre'},
                    {'variable': 'matricula_id',    'jsonpath': 'data.matricula_actual.id'},
                    {'variable': 'matricula_label', 'jsonpath': 'data.matricula_actual.label'},
                    {'variable': 'carrera',         'jsonpath': 'data.matricula_actual.carrera'},
                    {'variable': 'nivel',           'jsonpath': 'data.matricula_actual.nivel'},
                    {'variable': 'periodo',         'jsonpath': 'data.matricula_actual.periodo'},
                ],
                'plantilla_respuesta': (
                    '¡Qué gusto, *{{variables.nombre}}*! 🎓\n'
                    'Estoy revisando tu matrícula activa:\n'
                    '*{{variables.matricula_label}}*'
                ),
            },
        )

        # 3) Menú raíz (después del buscar). Las opciones privadas asumen
        # que `variables.cedula` y `variables.matricula_id` ya están seteadas.
        menu_raiz = self._nodo(
            depto, 'Menú principal', 'menu', orden=2,
            config={
                'mensaje': '¿En qué te puedo ayudar hoy?',
                'opciones': [
                    {'etiqueta': p['etiqueta'], 'valor': p['codigo'], 'salida': p['codigo']}
                    for p in PROCEDIMIENTOS
                ],
            },
            variable='opcion_menu',
            mensaje_error='Elige el número de la opción.',
        )

        # ── Nodos terminales / fallback ──────────────────────────
        no_encontrado = self._nodo(
            depto, 'Estudiante no encontrado', 'respuesta', orden=900,
            config={'mensaje': (
                '🔎 No encontré información registrada con esa cédula.\n'
                'Si crees que es un error, comunícate con tu coordinación.\n\n'
                'Probemos de nuevo…'
            )},
        )
        fin_error = self._nodo(
            depto, 'Error API', 'respuesta', orden=901,
            config={'mensaje': (
                '⚠️ No pude consultar tus datos en este momento. '
                'Intenta más tarde o escribe *menu* para volver.'
            )},
        )
        handoff = self._nodo(
            depto, 'Transferir a asesor', 'handoff', orden=902,
            config={'mensaje': '👤 Te conecto con un asesor humano del RU. Un momento por favor…'},
        )
        # Reset de variables tras buscar(error) — evita que la cédula
        # inválida quede sticky y bloquee consultas siguientes.
        set_var_reset_buscar = self._nodo(
            depto, 'Reset cédula/matrícula tras buscar(error)', 'set_variable',
            orden=903,
            config={'asignaciones': [
                {'variable': 'cedula',          'expresion': ''},
                {'variable': 'matricula_id',    'expresion': ''},
                {'variable': 'matricula_label', 'expresion': ''},
                {'variable': 'nombre',          'expresion': ''},
            ]},
        )
        # Reset cuando el usuario pide "consultar otra matrícula" (vuelve a
        # pedir cédula desde cero).
        set_var_reset_otra = self._nodo(
            depto, 'Reset para otra matrícula', 'set_variable', orden=904,
            config={'asignaciones': [
                {'variable': 'cedula',          'expresion': ''},
                {'variable': 'matricula_id',    'expresion': ''},
                {'variable': 'matricula_label', 'expresion': ''},
                {'variable': 'nombre',          'expresion': ''},
                {'variable': 'carrera',         'expresion': ''},
            ]},
        )
        # Sub-menú reusable después de cada handler exitoso.
        menu_post = self._nodo(
            depto, 'Sub-menú post-handler', 'menu', orden=905,
            config={
                'mensaje': '¿Quieres consultar algo más?',
                'opciones': [
                    {'etiqueta': '↩️ Volver al menú',     'valor': 'volver', 'salida': 'volver'},
                    {'etiqueta': '🔄 Otra matrícula',     'valor': 'otra',   'salida': 'otra'},
                    {'etiqueta': '👋 Terminar',           'valor': 'fin',    'salida': 'fin'},
                ],
            },
            variable='post_accion',
            mensaje_error='Elige una opción.',
        )
        fin_despedida = self._nodo(
            depto, 'Despedida', 'fin', orden=906,
            config={'mensaje': (
                '¡Gracias por usar Lucía! 💙 Si necesitas algo más, escribe *menu* '
                'cuando quieras y volvemos a empezar. 👋'
            )},
        )

        # ── Conexiones de cabecera (cédula → buscar → menú) ──────
        self._conectar(preg_cedula, http_buscar, '', 1)
        self._conectar(preg_cedula, fin_error,   'timeout', 2, '3 cédulas inválidas')
        self._conectar(http_buscar, menu_raiz,   'ok', 1, 'Cédula válida → menú')
        self._conectar(http_buscar, set_var_reset_buscar, 'error', 2,
                       'Cédula sin matrícula → reset y reintentar')

        # Loops de cierre.
        self._conectar(set_var_reset_buscar, no_encontrado, '', 1)
        self._conectar(no_encontrado,        preg_cedula,   '', 1, 'Reintentar cédula')
        self._conectar(fin_error,            menu_raiz,     '', 1, 'Tras error → menú')
        self._conectar(set_var_reset_otra,   preg_cedula,   '', 1, 'Otra matrícula → pide cédula nueva')
        self._conectar(menu_post, menu_raiz,           'volver',  1)
        self._conectar(menu_post, set_var_reset_otra,  'otra',    2)
        self._conectar(menu_post, fin_despedida,       'fin',     3)
        self._conectar(menu_post, menu_raiz,           'timeout', 4)

        # ── Generar mini-ramas por procedimiento ─────────────────
        # Cada rama empieza en `base_orden` y usa hasta 4 nodos (cond, preg,
        # buscar, http_X). Reservamos 10 órdenes por rama para holgura.
        for i, proc in enumerate(PROCEDIMIENTOS, start=1):
            base = i * 10  # 10, 20, 30, ...

            if proc['tipo'] == 'estatico':
                # Pública: respuesta directa → sub-menú post-handler.
                resp = self._nodo(
                    depto, f'Resp ({proc["codigo"]})', 'respuesta', orden=base,
                    config={'mensaje': proc['mensaje']},
                )
                self._conectar(menu_raiz, resp, proc['codigo'], 1)
                self._conectar(resp, menu_post, '', 1, 'Tras respuesta → opciones de seguimiento')
                continue

            if proc['tipo'] == 'http':
                self._crear_rama_privada(
                    depto, ep_ru, menu_raiz,
                    salida_ok=menu_post,
                    fin_error=fin_error,
                    proc=proc, base_orden=base,
                )
                continue

            if proc['tipo'] == 'http_con_submenu':
                sub_cfg = proc['submenu']
                sub_menu = self._nodo(
                    depto, f'Sub-menú ({proc["codigo"]})', 'menu',
                    orden=base + 5,
                    config={
                        'mensaje': sub_cfg['mensaje'],
                        'opciones': (
                            [{'etiqueta': o['etiqueta'], 'valor': o['codigo'], 'salida': o['codigo']}
                             for o in sub_cfg['opciones']]
                            + [{'etiqueta': 'Volver al menú', 'valor': 'volver', 'salida': 'volver'}]
                        ),
                    },
                    variable=f'sub_{proc["codigo"]}',
                    mensaje_error='Elige una opción.',
                )
                self._conectar(sub_menu, menu_raiz, 'volver', 99, 'Volver al menú principal')

                # Handler padre → tras la API, presenta el sub-menú.
                self._crear_rama_privada(
                    depto, ep_ru, menu_raiz,
                    salida_ok=sub_menu,
                    fin_error=fin_error,
                    proc=proc, base_orden=base,
                )

                # Sub-opciones también son llamadas API (cédula ya seteada).
                for j, sub_opt in enumerate(sub_cfg['opciones'], start=1):
                    sub_proc = {
                        'codigo': sub_opt['codigo'],
                        'metodo': sub_opt['metodo'],
                        'path':   sub_opt['path'],
                        'extraer': sub_opt.get('extraer') or [],
                        'plantilla': sub_opt.get('plantilla') or '',
                        'sin_matricula': sub_opt.get('sin_matricula', False),
                    }
                    self._crear_rama_privada(
                        depto, ep_ru, sub_menu,
                        salida_ok=menu_post,
                        fin_error=fin_error,
                        proc=sub_proc,
                        base_orden=base + 50 + j * 10,
                    )
                continue

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
                    f'Sesion "{s.nombre or s.session_id}" asociada al depto. '
                    f'modo_bot={s.modo_bot}, departamento_default={s.departamento_default.nombre}'
                ))

        total_nodos = depto.opciondepartamentochatbot_set.count()
        total_conns = ConexionNodoChatbot.objects.filter(nodo_origen__departamento=depto).count()
        self.stdout.write(self.style.SUCCESS(
            f'\n[OK] Flujo creado: "{depto.nombre}"\n'
            f'   Nodos: {total_nodos}  |  Conexiones: {total_conns}\n'
            f'   Endpoint: {ep_ru.nombre} -> {ep_ru.base_url}\n'
            f'   Credencial: {credencial.nombre} ({credencial.get_tipo_display()})\n\n'
            f'Modelo: 1 menu raiz con {len(PROCEDIMIENTOS)} opciones, todas vuelven al menu\n'
            f'tras responder. La cedula se pide UNA SOLA VEZ y se reusa en\n'
            f'consultas siguientes (cond_skip por opcion privada).\n\n'
            f'Siguiente: si la API ya pide auth, vuelve a correr con --bearer "<token>".'
        ))
