"""
Seed de un flujo realista tipo "Centro de Atención Estudiantil".

Crea un DepartamentoChatBot con su grafo de nodos listo para que el motor
`crm.motor_flujo_chatbot` lo ejecute. Incluye:
  - Menú principal de 5 opciones.
  - Consulta de matrícula: pregunta cédula (validación EC) → HTTP GET → respuesta.
  - Consulta de notas: pregunta cédula → HTTP GET → plantilla.
  - Información de becas: respuesta estática + pregunta sí/no → condicional.
  - Horarios: sub-menú por carrera → HTTP GET.
  - Hablar con asesor: handoff humano.

APIs usadas para que funcione end-to-end en demo:
  - https://jsonplaceholder.typicode.com  (GET /users/{id})
  - https://httpbin.org                    (GET /anything echoes params)
Sustitúyelas por las URLs reales de tu sistema académico.

Uso:
    python manage.py seed_centro_estudiantil
    python manage.py seed_centro_estudiantil --reset     # borra y recrea
    python manage.py seed_centro_estudiantil --sesion 3  # asocia a esa sesión
                                                          y setea modo_bot='tradicional'
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'Centro de Atención Estudiantil'


class Command(BaseCommand):
    help = 'Crea un flujo de chatbot tradicional tipo centro estudiantil (demo).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Borra el depto previo y lo recrea.')
        parser.add_argument('--sesion', type=int, default=None, help='ID de SesionWhatsApp para asociar el flujo.')

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
            # Limpia estados huérfanos asociados al depto que vamos a borrar.
            viejos = DepartamentoChatBot.objects.filter(nombre=NOMBRE_DEPTO)
            n_estados = EstadoFlujoChatbot.objects.filter(departamento__in=viejos).count()
            EstadoFlujoChatbot.objects.filter(departamento__in=viejos).delete()
            viejos.delete()
            self.stdout.write(self.style.WARNING(
                f'Depto "{NOMBRE_DEPTO}" previo eliminado '
                f'({n_estados} estados runtime también borrados).'
            ))
            # Limpia estados ya huérfanos (sin depto) que podrían tener
            # en_handoff=True y bloquear a contactos.
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
                'color': '#2563EB',
                'mensaje_saludo': (
                    '🎓 Hola {{contacto.nombre}}, bienvenido al *Centro de Atención Estudiantil*.\n'
                    'Estoy aquí para ayudarte con trámites, notas, becas y más.'
                ),
                'palabras_clave': 'universidad\nestudiante\nmatricula\nnotas\nbeca',
                'es_default': True,
                'activo_tradicional': True,
            },
        )
        if not creado:
            self.stdout.write(self.style.WARNING(
                'El depto ya existía. Usa --reset para recrearlo desde cero.'
            ))
            return

        # ── Credencial + endpoints ───────────────────────────────
        credencial = CredencialApiChatbot.objects.create(
            nombre='API Académica (demo)',
            tipo='none',
            secretos={},
            descripcion='Placeholder. Reemplaza por Bearer/APIKey real de tu SIS.',
        )
        ep_users = EndpointApiChatbot.objects.create(
            nombre='JSONPlaceholder /users',
            base_url='https://jsonplaceholder.typicode.com',
            credencial=credencial,
            headers_default={'Accept': 'application/json'},
            timeout_seg=10,
            descripcion='Demo: retorna info tipo {"name":..., "email":...}',
        )
        ep_echo = EndpointApiChatbot.objects.create(
            nombre='HTTPBin /anything',
            base_url='https://httpbin.org',
            credencial=credencial,
            headers_default={'Accept': 'application/json'},
            timeout_seg=10,
            descripcion='Demo: refleja args/headers/body; útil para probar envíos.',
        )

        # ── Menú principal ───────────────────────────────────────
        menu = self._nodo(
            depto, 'Menú principal', 'menu',
            es_inicio=True, orden=0,
            config={
                'mensaje': '¿En qué te puedo ayudar hoy?',
                'opciones': [
                    {'etiqueta': 'Consultar matrícula', 'valor': 'matricula', 'salida': 'matricula'},
                    {'etiqueta': 'Consultar notas',     'valor': 'notas',     'salida': 'notas'},
                    {'etiqueta': 'Horarios por carrera','valor': 'horarios',  'salida': 'horarios'},
                    {'etiqueta': 'Información de becas','valor': 'becas',     'salida': 'becas'},
                    {'etiqueta': 'Hablar con asesor',   'valor': 'asesor',    'salida': 'asesor'},
                ],
            },
            variable='opcion_menu',
            mensaje_error='Opción inválida. Responde con el *número* de la opción (1-5).',
        )

        # ── Rama: MATRÍCULA ──────────────────────────────────────
        p_ced_mat = self._nodo(
            depto, 'Pedir cédula (matrícula)', 'pregunta', orden=10,
            config={'pregunta': 'Por favor indícame tu número de *cédula* (10 dígitos):'},
            variable='cedula', validacion='cedula', reintentos=3,
            mensaje_error='La cédula no parece válida. Intenta nuevamente (10 dígitos, sólo números).',
        )
        http_mat = self._nodo(
            depto, 'Consultar estado de matrícula', 'http', orden=11,
            endpoint=ep_echo,
            config={
                'metodo': 'GET',
                'path': '/anything/matricula',
                'query': {'cedula': '{{variables.cedula}}', 'periodo': '2026-1'},
                'extraer': [
                    {'variable': 'cedula_eco', 'jsonpath': 'args.cedula'},
                    {'variable': 'periodo',    'jsonpath': 'args.periodo'},
                ],
                'plantilla_respuesta': (
                    '✅ Matrícula consultada.\n'
                    'Cédula: {{variables.cedula_eco}}\n'
                    'Período: {{variables.periodo}}\n'
                    'Estado: *ACTIVA* — pago al día.'
                ),
            },
        )
        fin_mat = self._nodo(
            depto, 'Fin (matrícula)', 'fin', orden=12,
            config={'mensaje': '¿Necesitas algo más? Escribe *hola* para volver al menú.'},
        )

        # ── Rama: NOTAS ──────────────────────────────────────────
        p_ced_notas = self._nodo(
            depto, 'Pedir cédula (notas)', 'pregunta', orden=20,
            config={'pregunta': 'Para consultar tus notas, indícame tu *cédula*:'},
            variable='cedula', validacion='cedula', reintentos=3,
            mensaje_error='Cédula inválida. Debe tener 10 dígitos.',
        )
        http_notas = self._nodo(
            depto, 'Consultar notas (API SIS)', 'http', orden=21,
            endpoint=ep_users,
            config={
                'metodo': 'GET',
                'path': '/users/1',
                'extraer': [
                    {'variable': 'alumno',  'jsonpath': 'name'},
                    {'variable': 'correo',  'jsonpath': 'email'},
                    {'variable': 'ciudad',  'jsonpath': 'address.city'},
                ],
                'plantilla_respuesta': (
                    '📊 *Reporte académico*\n'
                    'Alumno: {{variables.alumno}}\n'
                    'Correo: {{variables.correo}}\n'
                    'Ciudad: {{variables.ciudad}}\n\n'
                    'Promedio semestre: *8.7 / 10*\n'
                    'Materias aprobadas: 6 / 6'
                ),
            },
        )
        err_notas = self._nodo(
            depto, 'Error consulta notas', 'respuesta', orden=22,
            config={'mensaje': (
                '⚠️ No pude consultar tu record en este momento. '
                'Inténtalo más tarde o escribe *asesor* para hablar con alguien.'
            )},
        )
        fin_notas = self._nodo(
            depto, 'Fin (notas)', 'fin', orden=23,
            config={'mensaje': 'Escribe *hola* para volver al menú principal.'},
        )

        # ── Rama: HORARIOS (sub-menú por carrera) ────────────────
        menu_carrera = self._nodo(
            depto, 'Menú de carrera', 'menu', orden=30,
            config={
                'mensaje': '¿De qué carrera quieres el horario?',
                'opciones': [
                    {'etiqueta': 'Sistemas',      'valor': 'SIS', 'salida': 'sis'},
                    {'etiqueta': 'Administración','valor': 'ADM', 'salida': 'adm'},
                    {'etiqueta': 'Contabilidad',  'valor': 'CON', 'salida': 'con'},
                ],
            },
            variable='carrera',
            mensaje_error='Elige 1, 2 o 3.',
        )
        http_horario = self._nodo(
            depto, 'Consultar horario', 'http', orden=31,
            endpoint=ep_echo,
            config={
                'metodo': 'GET',
                'path': '/anything/horarios',
                'query': {'carrera': '{{variables.carrera}}'},
                'extraer': [{'variable': 'carrera_eco', 'jsonpath': 'args.carrera'}],
                'plantilla_respuesta': (
                    '📅 *Horario carrera {{variables.carrera_eco}}*\n'
                    'Lun–Vie: 07:00 – 12:00\n'
                    'Sáb: 08:00 – 14:00\n'
                    'Aula: pabellón B, piso 2.'
                ),
            },
        )
        fin_horario = self._nodo(
            depto, 'Fin (horario)', 'fin', orden=32,
            config={'mensaje': '¡Listo! Escribe *hola* para volver al menú.'},
        )

        # ── Rama: BECAS ──────────────────────────────────────────
        resp_becas = self._nodo(
            depto, 'Info becas', 'respuesta', orden=40,
            config={'mensaje': (
                '💰 *Programa de becas 2026*\n'
                '• Excelencia académica: 50% de descuento (promedio ≥ 9.0)\n'
                '• Deportiva: hasta 70%\n'
                '• Socio-económica: evaluada caso por caso\n\n'
                'Requisitos y fechas: https://universidad.edu.ec/becas'
            )},
        )
        p_aplica = self._nodo(
            depto, '¿Aplicar a beca?', 'pregunta', orden=41,
            config={'pregunta': '¿Quieres iniciar tu solicitud ahora? (responde *si* o *no*)'},
            variable='aplica_beca',
        )
        cond_aplica = self._nodo(
            depto, 'Condicional aplica', 'condicional', orden=42,
            config={
                'operador': 'or',
                'condiciones': [
                    {'izq': '{{variables.aplica_beca}}', 'op': 'contiene', 'der': 'si'},
                    {'izq': '{{variables.aplica_beca}}', 'op': 'contiene', 'der': 'sí'},
                ],
            },
        )
        set_prom = self._nodo(
            depto, 'Setear promedio simulado', 'set_variable', orden=43,
            config={'asignaciones': [{'variable': 'promedio_sim', 'expresion': '8.6'}]},
        )
        post_solicitud = self._nodo(
            depto, 'Registrar solicitud beca', 'http', orden=44,
            endpoint=ep_echo,
            config={
                'metodo': 'POST',
                'path': '/anything/becas',
                'body': {
                    'numero': '{{contacto.numero}}',
                    'nombre': '{{contacto.nombre}}',
                    'promedio': '{{variables.promedio_sim}}',
                    'conversacion_id': '{{conversacion.id}}',
                },
                'plantilla_respuesta': (
                    '📝 Solicitud registrada. Un asesor de becas te contactará '
                    'en 24–48h al número {{contacto.numero}}.'
                ),
            },
        )
        resp_no_beca = self._nodo(
            depto, 'No aplica beca', 'respuesta', orden=45,
            config={'mensaje': 'Perfecto, si cambias de opinión escribe *becas* de nuevo.'},
        )
        fin_becas = self._nodo(
            depto, 'Fin (becas)', 'fin', orden=46,
            config={'mensaje': 'Escribe *hola* para volver al menú principal.'},
        )

        # ── Rama: HANDOFF (asesor humano) ────────────────────────
        handoff = self._nodo(
            depto, 'Transferir a asesor', 'handoff', orden=50,
            config={'mensaje': (
                '👤 Te conecto con un asesor humano del centro estudiantil. '
                'Un momento por favor…'
            )},
        )

        # ─────────────────────────────────────────────────────────
        # Conexiones
        # ─────────────────────────────────────────────────────────
        # Menú principal → cada rama
        self._conectar(menu, p_ced_mat,    'matricula', 1)
        self._conectar(menu, p_ced_notas,  'notas',     2)
        self._conectar(menu, menu_carrera, 'horarios',  3)
        self._conectar(menu, resp_becas,   'becas',     4)
        self._conectar(menu, handoff,      'asesor',    5)
        self._conectar(menu, handoff,      'timeout',   6, 'Reintentos agotados → asesor')

        # Rama matrícula
        self._conectar(p_ced_mat,  http_mat,  '',        1)
        self._conectar(p_ced_mat,  handoff,   'timeout', 2, 'Cédula inválida 3 veces → asesor')
        self._conectar(http_mat,   fin_mat,   'ok',      1)
        self._conectar(http_mat,   handoff,   'error',   2, 'API caída → asesor')

        # Rama notas
        self._conectar(p_ced_notas, http_notas, '',        1)
        self._conectar(p_ced_notas, handoff,    'timeout', 2)
        self._conectar(http_notas,  fin_notas,  'ok',      1)
        self._conectar(http_notas,  err_notas,  'error',   2)
        self._conectar(err_notas,   fin_notas,  '',        1)

        # Rama horarios
        self._conectar(menu_carrera, http_horario, '',        1)
        self._conectar(menu_carrera, handoff,      'timeout', 2)
        self._conectar(http_horario, fin_horario,  'ok',      1)
        self._conectar(http_horario, handoff,      'error',   2)

        # Rama becas
        self._conectar(resp_becas,    p_aplica,      '',       1)
        self._conectar(p_aplica,      cond_aplica,   '',       1)
        self._conectar(cond_aplica,   set_prom,      'true',   1)
        self._conectar(cond_aplica,   resp_no_beca,  'false',  2)
        self._conectar(set_prom,      post_solicitud,'',       1)
        self._conectar(post_solicitud, fin_becas,    'ok',     1)
        self._conectar(post_solicitud, handoff,      'error',  2)
        self._conectar(resp_no_beca,   fin_becas,    '',       1)

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
                s.departamento_default = depto
                if s.modo_bot == 'ia':
                    s.modo_bot = 'tradicional'
                s.save()
                self.stdout.write(self.style.SUCCESS(
                    f'Sesión "{s.nombre or s.session_id}" asociada al depto. '
                    f'modo_bot={s.modo_bot}, departamento_default={depto.nombre}'
                ))

        total_nodos = depto.opciondepartamentochatbot_set.count()
        total_conns = ConexionNodoChatbot.objects.filter(nodo_origen__departamento=depto).count()
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Flujo creado: "{depto.nombre}"\n'
            f'   Nodos: {total_nodos}  |  Conexiones: {total_conns}\n'
            f'   Endpoints demo: {ep_users.nombre}, {ep_echo.nombre}\n'
            f'   Credencial: {credencial.nombre}\n\n'
            f'Siguiente: asocia este depto a tu SesionWhatsApp y setea '
            f'modo_bot="tradicional" (o usa --sesion <id>).'
        ))
