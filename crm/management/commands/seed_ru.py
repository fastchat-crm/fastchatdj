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
BASE_URL_DEFAULT = 'https://ruedge.ister.edu.ec/service/v1/bot/lucia'


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
            {'variable': 'titulo',   'jsonpath': 'data.titulo'},
            {'variable': 'rango',    'jsonpath': 'data.rango_label'},
            {'variable': 'tot',      'jsonpath': 'data.totales.total'},
            {'variable': 'tot_tar',  'jsonpath': 'data.totales.tareas'},
            {'variable': 'tot_for',  'jsonpath': 'data.totales.foros'},
            {'variable': 'tot_test', 'jsonpath': 'data.totales.tests'},
        ],
        'plantilla': (
            '📝 *{{variables.titulo}}*\n'
            '🗓️ Semana: {{variables.rango}}\n\n'
            'Total: *{{variables.tot}}* ítems\n'
            '• Tareas: {{variables.tot_tar}}\n'
            '• Foros: {{variables.tot_for}}\n'
            '• Tests: {{variables.tot_test}}'
        ),
    },
    {
        'codigo': 'materias', 'orden': 3,
        'etiqueta': '📚 Mis materias',
        'tipo': 'http', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/materias/',
        'extraer': [
            {'variable': 'm_titulo', 'jsonpath': 'data.titulo'},
            {'variable': 'm_total',  'jsonpath': 'data.total'},
            {'variable': 'm_url',    'jsonpath': 'data.url_materias'},
        ],
        'plantilla': (
            '📚 *{{variables.m_titulo}}*\n'
            'Tienes *{{variables.m_total}}* materias activas.\n\n'
            'Ver detalle (Meet, Moodle, docentes) 👉 {{variables.m_url}}'
        ),
    },
    {
        'codigo': 'horarios', 'orden': 4,
        'etiqueta': '📅 Mis horarios',
        'tipo': 'http_con_submenu', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/horarios/',
        'extraer': [
            {'variable': 'h_url',     'jsonpath': 'data.url_horarios'},
            {'variable': 'h_primera', 'jsonpath': 'data.materias[0].asignatura'},
        ],
        'plantilla': (
            '📅 *Tus horarios de la semana*\n'
            'Primera materia: {{variables.h_primera}}\n\n'
            'Ver horario completo aquí 👉 {{variables.h_url}}'
        ),
        'submenu': {
            'mensaje': '¿Quieres ver algo más específico?',
            'opciones': [
                {
                    'codigo': 'horarios_hoy',
                    'etiqueta': 'Clases de hoy',
                    'metodo': 'GET', 'path': '/horarios-hoy/',
                    'extraer': [
                        {'variable': 'titulo',   'jsonpath': 'data.titulo'},
                        {'variable': 'primera',  'jsonpath': 'data.clases[0].asignatura'},
                        {'variable': 'hora',     'jsonpath': 'data.clases[0].hora'},
                        {'variable': 'profesor', 'jsonpath': 'data.clases[0].profesor'},
                    ],
                    'plantilla': (
                        '📅 *{{variables.titulo}}*\n'
                        '• {{variables.primera}}\n'
                        '🕐 {{variables.hora}}\n'
                        '👤 {{variables.profesor}}'
                    ),
                },
                {
                    'codigo': 'horarios_actividades',
                    'etiqueta': 'Actividades semana',
                    'metodo': 'GET', 'path': '/actividades-semana/',
                    'extraer': [
                        {'variable': 'a_titulo', 'jsonpath': 'data.titulo'},
                        {'variable': 'a_rango',  'jsonpath': 'data.rango_label'},
                        {'variable': 'a_tot',    'jsonpath': 'data.totales.total'},
                    ],
                    'plantilla': (
                        '📝 *{{variables.a_titulo}}*\n'
                        '🗓️ {{variables.a_rango}}\n'
                        'Total: *{{variables.a_tot}}* ítems'
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
        'sin_matricula': True,  # /deudas/ no requiere matricula_id
        'extraer': [
            {'variable': 'saldo',    'jsonpath': 'data.total_saldo'},
            {'variable': 'vencido',  'jsonpath': 'data.total_vencido'},
            {'variable': 'rubros',   'jsonpath': 'data.total_rubros'},
            {'variable': 'detalle1', 'jsonpath': 'data.detalle[0].nombre'},
            {'variable': 'estado1',  'jsonpath': 'data.detalle[0].estado'},
        ],
        'plantilla': (
            '💲 *Tu estado financiero*\n'
            '• Saldo total: ${{variables.saldo}}\n'
            '• Vencido: ${{variables.vencido}}\n'
            '• Rubros del período: ${{variables.rubros}}\n\n'
            'Último rubro: {{variables.detalle1}} → {{variables.estado1}}'
        ),
    },
    {
        'codigo': 'mentor', 'orden': 6,
        'etiqueta': '👤 Mi mentor',
        'tipo': 'http', 'requiere_cedula': True,
        'metodo': 'GET', 'path': '/mentor/',
        'extraer': [
            {'variable': 'm_nom',   'jsonpath': 'data.nombre'},
            {'variable': 'm_email', 'jsonpath': 'data.email'},
            {'variable': 'm_cel',   'jsonpath': 'data.celular'},
            {'variable': 'm_wa',    'jsonpath': 'data.whatsapp_url'},
        ],
        'plantilla': (
            '👤 *Tu mentor asignado*\n'
            '• {{variables.m_nom}}\n'
            '✉️ {{variables.m_email}}\n'
            '📱 {{variables.m_cel}}\n\n'
            'Escribirle por WhatsApp 👉 {{variables.m_wa}}'
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
            {'variable': 'c_men_nom', 'jsonpath': 'data.contactos[0].nombre'},
            {'variable': 'c_men_em',  'jsonpath': 'data.contactos[0].email'},
            {'variable': 'c_ase_nom', 'jsonpath': 'data.contactos[1].nombre'},
            {'variable': 'c_ase_em',  'jsonpath': 'data.contactos[1].email'},
            {'variable': 'c_proc',    'jsonpath': 'data.url_procesos'},
        ],
        'plantilla': (
            '💬 *Tus contactos académicos*\n\n'
            '👤 *Mentor:* {{variables.c_men_nom}}\n'
            '✉️ {{variables.c_men_em}}\n\n'
            '👤 *Asesor:* {{variables.c_ase_nom}}\n'
            '✉️ {{variables.c_ase_em}}\n\n'
            'Portal de procesos 👉 {{variables.c_proc}}'
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
]


class Command(BaseCommand):
    help = 'Crea el flujo del asistente RU (Lucía) — un solo depto, loop al menú.'

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

    def _query_para(self, proc):
        """Construye query del API en base al descriptor del procedimiento."""
        q = {'cedula': '{{variables.cedula}}'}
        if not proc.get('sin_matricula'):
            q['matricula_id'] = '{{variables.matricula_id}}'
        return q

    def _crear_rama_privada(self, depto, ep_ru, menu_raiz, salida_ok, no_encontrado,
                            fin_error, set_var_reset_buscar, proc, base_orden):
        """
        Crea la mini-rama privada de un procedimiento que requiere cédula:

            menu_raiz --[salida=codigo]--> cond_skip
                cond_skip --[true]--> http_X
                cond_skip --[false]--> preg_cedula --> http_buscar
                                                       --[ok]--> http_X
                                                       --[error]--> set_var_reset --> no_encontrado
            http_X --[ok]--> salida_ok
            http_X --[error]--> fin_error

        Tras buscar(error) limpiamos `variables.cedula`/`matricula_id` con
        `set_var_reset_buscar` para que la próxima consulta vuelva a pedir
        cédula (sin esto el cond_skip vería la cédula sticky y entraría
        directo al API → fallo silencioso).

        Retorna http_X (útil cuando hay sub-menú post-handler).
        """
        codigo = proc['codigo']
        cond = self._nodo(
            depto, f'¿Tengo cédula? ({codigo})', 'condicional', orden=base_orden,
            config={
                'operador': 'and',
                'condiciones': [
                    {'izq': '{{variables.cedula}}', 'op': 'no_vacio', 'der': ''},
                ],
            },
        )
        preg = self._nodo(
            depto, f'Pedir cédula ({codigo})', 'pregunta', orden=base_orden + 1,
            config={'pregunta': '🪪 Por favor ingresa tu *número de cédula* (10 dígitos):'},
            variable='cedula', validacion='cedula', reintentos=3,
            mensaje_error='Cédula inválida. Vuelve a intentarlo (10 dígitos, sólo números).',
        )
        buscar = self._nodo(
            depto, f'Buscar estudiante ({codigo})', 'http', orden=base_orden + 2,
            endpoint=ep_ru,
            config={
                'metodo': 'POST', 'path': '/buscar-estudiante/',
                'body': {'cedula': '{{variables.cedula}}'},
                'extraer': [
                    {'variable': 'nombre',       'jsonpath': 'data.nombre'},
                    {'variable': 'matricula_id', 'jsonpath': 'data.matriculas[0].id'},
                    {'variable': 'carrera',      'jsonpath': 'data.matriculas[0].carrera'},
                ],
                'plantilla_respuesta': (
                    '✅ Hola *{{variables.nombre}}* 👋 — {{variables.carrera}}'
                ),
            },
        )
        http_x = self._nodo(
            depto, f'API {proc["metodo"]} {proc["path"]} ({codigo})', 'http',
            orden=base_orden + 3, endpoint=ep_ru,
            config={
                'metodo': proc['metodo'],
                'path':   proc['path'],
                'query':  self._query_para(proc),
                'extraer': proc.get('extraer') or [],
                'plantilla_respuesta': proc.get('plantilla') or '',
            },
        )

        # Conexiones
        self._conectar(menu_raiz, cond, codigo, 1)
        self._conectar(cond, http_x, 'true', 1, 'Cédula ya está set')
        self._conectar(cond, preg, 'false', 2, 'Cédula vacía → pedirla')
        self._conectar(preg, buscar, '', 1)
        self._conectar(preg, fin_error, 'timeout', 2)
        self._conectar(buscar, http_x, 'ok', 1)
        # Buscar fallido → reset variables → no_encontrado.
        self._conectar(buscar, set_var_reset_buscar, 'error', 2,
                       'Reset cédula/matricula tras fallo del buscar')
        self._conectar(http_x, salida_ok, 'ok', 1)
        self._conectar(http_x, fin_error, 'error', 2)
        return http_x

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
                f'({n_estados} estados runtime tambien borrados).'
            ))
            huerfanos = EstadoFlujoChatbot.objects.filter(departamento__isnull=True)
            if huerfanos.exists():
                n = huerfanos.count()
                huerfanos.delete()
                self.stdout.write(self.style.WARNING(
                    f'  + {n} estados huerfanos sin depto tambien eliminados.'
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

        # ── Menú raíz ────────────────────────────────────────────
        menu_raiz = self._nodo(
            depto, 'Menú principal', 'menu', es_inicio=True, orden=0,
            config={
                'mensaje': '¿Qué te gustaría consultar?',
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
                'Te llevo de vuelta al menú…'
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
                {'variable': 'cedula',       'expresion': ''},
                {'variable': 'matricula_id', 'expresion': ''},
                {'variable': 'nombre',       'expresion': ''},
            ]},
        )
        # Reset cuando el usuario pide "consultar otra matrícula".
        set_var_reset_otra = self._nodo(
            depto, 'Reset para otra matrícula', 'set_variable', orden=904,
            config={'asignaciones': [
                {'variable': 'cedula',       'expresion': ''},
                {'variable': 'matricula_id', 'expresion': ''},
                {'variable': 'nombre',       'expresion': ''},
                {'variable': 'carrera',      'expresion': ''},
            ]},
        )
        # Sub-menú reusable después de cada handler exitoso.
        # Replica el UX del bot real: "Volver al menú / Consultar otra matrícula".
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

        # Loop de cierre: respuesta-fallback / set_var → vuelven al menú.
        self._conectar(set_var_reset_buscar, no_encontrado, '', 1, 'Tras reset → mensaje')
        self._conectar(no_encontrado, menu_raiz, '', 1, 'Tras error → vuelve al menú')
        self._conectar(fin_error,     menu_raiz, '', 1, 'Tras error → vuelve al menú')
        self._conectar(set_var_reset_otra, menu_raiz, '', 1, 'Tras reset → menú (próxima opción privada pedirá cédula)')
        self._conectar(menu_post, menu_raiz,           'volver', 1, 'Volver al menú raíz')
        self._conectar(menu_post, set_var_reset_otra,  'otra',   2, 'Cambiar de matrícula')
        self._conectar(menu_post, fin_despedida,       'fin',    3, 'Terminar conversación')
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
                    salida_ok=menu_post,           # tras handler → sub-menú post-handler
                    no_encontrado=no_encontrado,
                    fin_error=fin_error,
                    set_var_reset_buscar=set_var_reset_buscar,
                    proc=proc, base_orden=base,
                )
                continue

            if proc['tipo'] == 'http_con_submenu':
                # Construir primero el sub-menú y sus mini-ramas (necesarios para
                # apuntar `salida_ok` del handler padre al sub-menú).
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
                # Conexión "volver" al menú raíz.
                self._conectar(sub_menu, menu_raiz, 'volver', 99, 'Volver al menú principal')

                # Mini-rama del handler padre → sub_menu (no menu_post).
                self._crear_rama_privada(
                    depto, ep_ru, menu_raiz,
                    salida_ok=sub_menu,
                    no_encontrado=no_encontrado,
                    fin_error=fin_error,
                    set_var_reset_buscar=set_var_reset_buscar,
                    proc=proc, base_orden=base,
                )

                # Mini-ramas de cada sub-opción (también privadas).
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
                        salida_ok=menu_post,           # tras sub-handler → sub-menú post
                        no_encontrado=no_encontrado,
                        fin_error=fin_error,
                        set_var_reset_buscar=set_var_reset_buscar,
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
