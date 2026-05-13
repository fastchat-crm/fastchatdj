"""
Seed del cotizador Vida Buena — modo MÚLTIPLE (Modo A del webhook).

Variante del flujo `seed_cotizador_am` para el caso en que el cliente quiere
elegir 1 a 3 planes concretos en la misma cotización. En vez de delegar la
recomendación al decision engine (`members[] + budget_intent`), el bot pide
explícitamente cada par `(plan_id, plan_dental_id)` y envía un solo POST con
`selecciones=[...]` al webhook externo.

Las opciones de plan y de plan dental se traen *en runtime* con
`GET ?action=planes&fecha_nacimiento=&sexo=` y se renderizan dinámicamente
en menús de botones — si el broker agrega/quita planes en el cotimedica
admin, el bot los toma sin redeploy.

El loop de selección NO usa nodos cíclicos en sentido estricto (el motor de
flujo no soporta recurrencia con scopes de variable). En su lugar repetimos
tres bloques de preguntas idénticos guardando en variables sufijadas
(`plan_id_1`/`plan_dental_id_1`, `_2`, `_3`). El usuario decide después de
cada par si añade otro plan o pasa a cotizar; los pares vacíos se descartan
en `cotizar_am_multiple`.

Flujo (resumido):
  saludo → cédula → GET ?action=cliente → completar datos faltantes
   → GET ?action=planes&fecha_nacimiento=&sexo= → planes_list + dental_options
   → ITER 1: menu plan → menu plan dental → ¿añadir otro?
   → ITER 2 (opcional): menu plan → menu plan dental → ¿añadir otro?
   → ITER 3 (opcional): menu plan → menu plan dental
   → "⏳ procesando…" → función `cotizar_am_multiple` → confirmación
   → handoff opcional al asesor.

Coexiste con `seed_cotizador_am` (deptos distintos, mismas credenciales y
endpoints reutilizados).

Uso:
    python manage.py seed_cotizador_asistenciamedica_multiple
    python manage.py seed_cotizador_asistenciamedica_multiple --reset
    python manage.py seed_cotizador_asistenciamedica_multiple --delete
    python manage.py seed_cotizador_asistenciamedica_multiple --sesion 5
    python manage.py seed_cotizador_asistenciamedica_multiple --base-url https://otro.dominio.ec/cotimedica-api/v1/
    python manage.py seed_cotizador_asistenciamedica_multiple --webhook-url https://otro.dominio.ec/cotimedica/webhook/
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'Vida Buena — Cotizador asistencia médica (múltiple)'

BASE_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/cotimedica-api/v1/'

CREDENCIAL_NOMBRE = 'Vida Buena REST - AllowAny'
ENDPOINT_NOMBRE = 'Cotizador Vida Buena REST v1'

WEBHOOK_EXTERNO_CREDENCIAL_NOMBRE = 'Vida Buena Webhook Externo (sin auth)'
WEBHOOK_EXTERNO_ENDPOINT_NOMBRE = 'Vida Buena — Webhook Cotizador (externo)'
WEBHOOK_EXTERNO_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/cotimedica/webhook/'
WEBHOOK_EXTERNO_TIMEOUT_DEFAULT = 45


BOT = {
    'codigo': 'vida_buena_multiple',
    'nombre': NOMBRE_DEPTO,
    'descripcion': (
        'Asistente que permite al cliente elegir explícitamente 1 a 3 planes '
        'de asistencia médica Vida Buena y dispara la cotización múltiple.'
    ),
    'mensaje_inicial': (
        'Hola 👋 Soy tu asesor de Vida Buena 🏥. Te ayudo a cotizar uno o '
        'varios planes en un solo paso. Empecemos con tus datos.'
    ),
    'color_primario': '#0d6efd',
    'palabras_clave': (
        'vida buena multiple\nplanes multiples\nvarios planes\ncotizar varios\n'
        'multiple plan medico\nelegir planes\ncotizacion multiple\n'
        'comparar planes vida buena'
    ),
    'reset_triggers': [
        'reiniciar', 'cancelar', 'volver al inicio', 'empezar de nuevo',
        'otra cotizacion', 'cotizar otra', 'otra persona', 'reset',
    ],
    'mensaje_reset': '🔄 Listo, empezamos de nuevo. Olvidé los datos anteriores.',
}


PASOS = [
    {
        'id': 10, 'orden': 10, 'tipo': 'respuesta_texto',
        'codigo': 'saludo_inicial', 'nombre': 'Saludo de bienvenida',
        'es_inicio': True,
        'mensaje': BOT['mensaje_inicial'],
        'siguiente': 20,
    },

    {
        'id': 20, 'orden': 20, 'tipo': 'input_texto',
        'codigo': 'pedir_cedula', 'nombre': 'Pedir cédula',
        'mensaje': '🪪 Para empezar, dame tu *cédula* (10 dígitos):',
        'guardar_en': 'cedula',
        'validacion': r'^[0-9]{10}([0-9]{3})?$',
        'siguiente': 30,
    },
    {
        'id': 30, 'orden': 30, 'tipo': 'llamada_http',
        'codigo': 'http_cliente',
        'nombre': 'GET ?action=cliente — lookup registro civil',
        'metodo': 'GET', 'path': '',
        'query': {'action': 'cliente', 'cedula': '{{variables.cedula}}'},
        'timeout_seg': 20,
        'extrae_variables': {
            '$encontrado_cli':   '$.data.encontrado',
            '$nombres':          '$.data.nombres',
            '$apellidos':        '$.data.apellidos',
            '$fecha_nacimiento': '$.data.fecha_nacimiento',
            '$edad_titular':     '$.data.edad',
            '$sexo_titular':     '$.data.sexo',
            '$email':            '$.data.email',
            '$telefono':         '$.data.telefono',
        },
        'siguiente_ok': 40, 'siguiente_error': 900,
    },
    {
        'id': 40, 'orden': 40, 'tipo': 'decision',
        'codigo': 'cliente_encontrado', 'nombre': '¿Cliente encontrado?',
        'condicion': '{{variables.encontrado_cli}} == true',
        'siguiente_si': 50, 'siguiente_no': 100,
    },

    {
        'id': 50, 'orden': 50, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_cliente', 'nombre': 'Mostrar datos del cliente',
        'mensaje': (
            '✅ Encontré tus datos:\n'
            '• Nombre: *{{variables.nombres}} {{variables.apellidos}}*\n'
            '• Edad: *{{variables.edad_titular}}*\n'
            '• Sexo: *{{variables.sexo_titular}}*\n'
            '• Email: *{{variables.email}}*'
        ),
        'siguiente': 60,
    },

    {
        'id': 60, 'orden': 60, 'tipo': 'decision',
        'codigo': 'email_vacio', 'nombre': '¿Email vacío?',
        'condiciones': [{'izq': '{{variables.email}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 62, 'siguiente_no': 64,
    },
    {
        'id': 62, 'orden': 62, 'tipo': 'input_texto',
        'codigo': 'pedir_email_faltante', 'nombre': 'Pedir email (faltante)',
        'mensaje': (
            '📧 No tenemos un correo registrado. ¿A qué *correo* te enviamos '
            'la cotización?'
        ),
        'guardar_en': 'email',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 80,
    },
    {
        'id': 64, 'orden': 64, 'tipo': 'menu_botones',
        'codigo': 'confirmar_correo', 'nombre': '¿Correo correcto?',
        'mensaje': '¿Te enviamos la cotización al correo *{{variables.email}}*?',
        'guardar_en': 'confirma_correo',
        'opciones': [
            {'etiqueta': '✅ Sí, está bien',   'valor': 'si',      'siguiente': 80},
            {'etiqueta': '✏️ Cambiar correo', 'valor': 'cambiar', 'siguiente': 66},
        ],
    },
    {
        'id': 66, 'orden': 66, 'tipo': 'input_texto',
        'codigo': 'pedir_email_nuevo_confirm', 'nombre': 'Pedir correo actualizado',
        'mensaje': '📧 Escríbeme el *correo nuevo* al que quieres recibir la cotización:',
        'guardar_en': 'email',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 80,
    },

    {
        'id': 80, 'orden': 80, 'tipo': 'decision',
        'codigo': 'sexo_vacio', 'nombre': '¿Sexo vacío?',
        'condiciones': [{'izq': '{{variables.sexo_titular}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 90, 'siguiente_no': 160,
    },
    {
        'id': 90, 'orden': 90, 'tipo': 'menu_botones',
        'codigo': 'pedir_sexo', 'nombre': 'Pedir sexo (titular)',
        'mensaje': '👤 ¿Cuál es tu *sexo*?',
        'guardar_en': 'sexo_titular',
        'opciones': [
            {'etiqueta': '👨 Masculino', 'valor': 'M', 'siguiente': 160},
            {'etiqueta': '👩 Femenino',  'valor': 'F', 'siguiente': 160},
        ],
    },

    {
        'id': 100, 'orden': 100, 'tipo': 'input_texto',
        'codigo': 'pedir_nombres', 'nombre': 'Pedir nombres',
        'mensaje': 'No te encontré en nuestra base. ¿Cuál es tu *nombre*?',
        'guardar_en': 'nombres',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'siguiente': 110,
    },
    {
        'id': 110, 'orden': 110, 'tipo': 'input_texto',
        'codigo': 'pedir_apellidos', 'nombre': 'Pedir apellidos',
        'mensaje': '¿Y tus *apellidos*?',
        'guardar_en': 'apellidos',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'siguiente': 120,
    },
    {
        'id': 120, 'orden': 120, 'tipo': 'input_texto',
        'codigo': 'pedir_email_nuevo', 'nombre': 'Pedir email',
        'mensaje': '📧 ¿A qué *correo* te enviamos la cotización?',
        'guardar_en': 'email',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 130,
    },
    {
        'id': 130, 'orden': 130, 'tipo': 'input_texto',
        'codigo': 'pedir_fecha_nacimiento', 'nombre': 'Pedir fecha de nacimiento',
        'mensaje': (
            '🎂 ¿Cuál es tu *fecha de nacimiento*? Formato DD/MM/AAAA '
            '(ej: 12/04/1985):'
        ),
        'guardar_en': 'fecha_nacimiento',
        'validacion': r'^\d{2}/\d{2}/\d{4}$',
        'siguiente': 150,
    },
    {
        'id': 150, 'orden': 150, 'tipo': 'menu_botones',
        'codigo': 'pedir_sexo_nuevo', 'nombre': 'Pedir sexo',
        'mensaje': '👤 ¿Cuál es tu *sexo*?',
        'guardar_en': 'sexo_titular',
        'opciones': [
            {'etiqueta': '👨 Masculino', 'valor': 'M', 'siguiente': 160},
            {'etiqueta': '👩 Femenino',  'valor': 'F', 'siguiente': 160},
        ],
    },

    {
        'id': 160, 'orden': 160, 'tipo': 'llamada_http',
        'codigo': 'http_planes',
        'nombre': 'GET ?action=planes — planes vigentes para edad/sexo',
        'metodo': 'GET', 'path': '',
        'query': {
            'action': 'planes',
            'fecha_nacimiento': '{{variables.fecha_nacimiento}}',
            'sexo': '{{variables.sexo_titular}}',
        },
        'timeout_seg': 25,
        'extrae_variables': {
            '$planes_list':    '$.data.planes',
            '$dental_options': '$.data.planes[0].opciones_dental',
            '$total_planes':   '$.data.total_planes',
        },
        'siguiente_ok': 165, 'siguiente_error': 900,
    },
    {
        'id': 165, 'orden': 165, 'tipo': 'respuesta_texto',
        'codigo': 'instrucciones_seleccion', 'nombre': 'Instrucciones del bucle',
        'mensaje': (
            '🩺 Te muestro los planes disponibles. Podés cotizar hasta *3 '
            'planes* en una misma solicitud. Te preguntaré por cada uno y '
            'al final eliges si quieres añadir otro o cerrar la cotización.'
        ),
        'siguiente': 170,
    },

    {
        'id': 170, 'orden': 170, 'tipo': 'menu_botones',
        'codigo': 'plan_iter_1', 'nombre': 'Plan #1',
        'mensaje': '🏥 Elige el *plan #1* que querés cotizar:',
        'guardar_en': 'plan_id_1',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.planes_list',
            'campo_id': 'plan_id',
            'campo_etiqueta': 'nombre',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 180,
    },
    {
        'id': 180, 'orden': 180, 'tipo': 'menu_botones',
        'codigo': 'dental_iter_1', 'nombre': 'Plan dental #1',
        'mensaje': '🦷 Elige el *plan dental* para tu plan #1:',
        'guardar_en': 'plan_dental_id_1',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.dental_options',
            'campo_id': 'plan_dental_id',
            'campo_etiqueta': 'plan_dental_codigo',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 190,
    },
    {
        'id': 190, 'orden': 190, 'tipo': 'menu_botones',
        'codigo': 'anadir_otro_1', 'nombre': '¿Añadir un segundo plan?',
        'mensaje': '➕ ¿Querés cotizar *otro plan* más?',
        'guardar_en': 'anadir_otro_1',
        'opciones': [
            {'etiqueta': '➕ Sí, añadir otro',   'valor': 'si', 'siguiente': 200},
            {'etiqueta': '✅ No, ya está bien', 'valor': 'no', 'siguiente': 300},
        ],
    },

    {
        'id': 200, 'orden': 200, 'tipo': 'menu_botones',
        'codigo': 'plan_iter_2', 'nombre': 'Plan #2',
        'mensaje': '🏥 Elige el *plan #2* que querés cotizar:',
        'guardar_en': 'plan_id_2',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.planes_list',
            'campo_id': 'plan_id',
            'campo_etiqueta': 'nombre',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 210,
    },
    {
        'id': 210, 'orden': 210, 'tipo': 'menu_botones',
        'codigo': 'dental_iter_2', 'nombre': 'Plan dental #2',
        'mensaje': '🦷 Elige el *plan dental* para tu plan #2:',
        'guardar_en': 'plan_dental_id_2',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.dental_options',
            'campo_id': 'plan_dental_id',
            'campo_etiqueta': 'plan_dental_codigo',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 220,
    },
    {
        'id': 220, 'orden': 220, 'tipo': 'menu_botones',
        'codigo': 'anadir_otro_2', 'nombre': '¿Añadir un tercer plan?',
        'mensaje': '➕ ¿Querés cotizar un *tercer plan*?',
        'guardar_en': 'anadir_otro_2',
        'opciones': [
            {'etiqueta': '➕ Sí, añadir otro',   'valor': 'si', 'siguiente': 230},
            {'etiqueta': '✅ No, ya está bien', 'valor': 'no', 'siguiente': 300},
        ],
    },

    {
        'id': 230, 'orden': 230, 'tipo': 'menu_botones',
        'codigo': 'plan_iter_3', 'nombre': 'Plan #3',
        'mensaje': '🏥 Elige el *plan #3* que querés cotizar:',
        'guardar_en': 'plan_id_3',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.planes_list',
            'campo_id': 'plan_id',
            'campo_etiqueta': 'nombre',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 240,
    },
    {
        'id': 240, 'orden': 240, 'tipo': 'menu_botones',
        'codigo': 'dental_iter_3', 'nombre': 'Plan dental #3',
        'mensaje': '🦷 Elige el *plan dental* para tu plan #3:',
        'guardar_en': 'plan_dental_id_3',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.dental_options',
            'campo_id': 'plan_dental_id',
            'campo_etiqueta': 'plan_dental_codigo',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 300,
    },

    {
        'id': 300, 'orden': 300, 'tipo': 'respuesta_texto',
        'codigo': 'esperando_cotizacion', 'nombre': 'Mensaje esperando',
        'mensaje': (
            '⏳ Estamos generando tus cotizaciones. En breve recibirás los '
            'PDFs por correo electrónico y aquí mismo el resumen.'
        ),
        'siguiente': 310,
    },

    {
        'id': 310, 'orden': 310, 'tipo': 'llamada_funcion',
        'codigo': 'fn_cotizar_am_multiple',
        'nombre': 'Función → Cotizar Vida Buena múltiple (selecciones)',
        'funcion_codigo': 'cotizar_am_multiple',
        'endpoint_key': 'webhook_externo',
        'envia_correo': True,
        'metodo': 'POST',
        'timeout_seg': 45,
        'body': {
            'cliente': {
                'cedula':           '{{variables.cedula}}',
                'nombres':          '{{variables.nombres}}',
                'apellidos':        '{{variables.apellidos}}',
                'fecha_nacimiento': '{{variables.fecha_nacimiento}}',
                'sexo':             '{{variables.sexo_titular}}',
                'email':            '{{variables.email}}',
            },
        },
        'extrae_variables': {
            '$cotizacion_status':  '$.status',
            '$cotizacion_mensaje': '$.message',
        },
        'siguiente_ok': 320, 'siguiente_error': 330,
    },

    {
        'id': 320, 'orden': 320, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_encolada', 'nombre': 'Cotización en proceso',
        'mensaje': (
            '✅ ¡Listo! Tus cotizaciones quedaron en proceso.\n\n'
            'Recibirás los *PDFs por correo electrónico* y el resumen aquí '
            'mismo en breve. 🏥💜'
        ),
        'siguiente': 350,
    },

    {
        'id': 330, 'orden': 330, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_error', 'nombre': 'Error al cotizar',
        'mensaje': (
            '⚠️ No pudimos procesar tu cotización en este momento. '
            'Por favor inténtalo más tarde. 🙏'
        ),
        'siguiente': 999,
    },

    {
        'id': 350, 'orden': 350, 'tipo': 'menu_botones',
        'codigo': 'handoff_asesor', 'nombre': '¿Contactar asesor?',
        'mensaje': (
            '¿Deseas que un *asesor* te contacte para validar datos y avanzar '
            'con la activación?'
        ),
        'guardar_en': 'quiere_asesor',
        'opciones': [
            {'etiqueta': '✅ Sí, contáctenme',  'valor': 'si', 'siguiente': 360},
            {'etiqueta': '👀 Solo informativo', 'valor': 'no', 'siguiente': 370},
        ],
    },
    {
        'id': 360, 'orden': 360, 'tipo': 'respuesta_texto',
        'codigo': 'handoff_aceptado', 'nombre': 'Handoff aceptado',
        'mensaje': (
            '🤝 Excelente. Un asesor te contactará en breve para confirmar '
            'la tarifa exacta y la activación.'
        ),
        'siguiente': 998,
    },
    {
        'id': 370, 'orden': 370, 'tipo': 'respuesta_texto',
        'codigo': 'handoff_rechazado', 'nombre': 'Handoff rechazado',
        'mensaje': (
            '👍 Perfecto. Si más adelante quieres avanzar, escríbenos cuando '
            'gustes. ¡Estamos para ayudarte!'
        ),
        'siguiente': 998,
    },

    {
        'id': 900, 'orden': 900, 'tipo': 'respuesta_texto',
        'codigo': 'error_api', 'nombre': 'Error genérico de API',
        'mensaje': '⚠️ Hubo un problema al hablar con el servidor. Intenta más tarde.',
        'siguiente': 999,
    },
    {
        'id': 998, 'orden': 998, 'tipo': 'asignar_variable',
        'codigo': 'reset_sesion', 'nombre': 'Reset de variables',
        'asigna': {
            'cedula': '', 'nombres': '', 'apellidos': '', 'email': '',
            'fecha_nacimiento': '', 'edad_titular': '', 'sexo_titular': '',
            'telefono': '', 'encontrado_cli': '', 'confirma_correo': '',
            'planes_list': '', 'dental_options': '', 'total_planes': '',
            'plan_id_1': '', 'plan_dental_id_1': '',
            'plan_id_2': '', 'plan_dental_id_2': '',
            'plan_id_3': '', 'plan_dental_id_3': '',
            'anadir_otro_1': '', 'anadir_otro_2': '',
            'quiere_asesor': '',
            'cotizacion_status': '', 'cotizacion_mensaje': '',
        },
        'siguiente': 999,
    },
    {
        'id': 999, 'orden': 999, 'tipo': 'fin_conversacion',
        'codigo': 'despedida', 'nombre': 'Fin',
        'mensaje': (
            '¡Hasta pronto! 👋 Cuando quieras volver a cotizar, aquí estaré.'
        ),
    },
]


TIPO_MAP = {
    'respuesta_texto':  'respuesta',
    'input_texto':      'pregunta',
    'llamada_http':     'http',
    'llamada_funcion':  'funcion',
    'decision':         'condicional',
    'menu_botones':     'menu',
    'asignar_variable': 'set_variable',
    'fin_conversacion': 'fin',
}


def _normalizar_extraer(extrae_variables):
    if not extrae_variables:
        return []
    out = []
    for k, v in extrae_variables.items():
        nombre = k.lstrip('$')
        path = v[2:] if isinstance(v, str) and v.startswith('$.') else v
        out.append({'variable': nombre, 'jsonpath': path})
    return out


def _parse_literal(s):
    s = (s or '').strip()
    if s == '':
        return ''
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    low = s.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    if low == 'null' or low == 'none':
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def _parse_condicion(expr):
    expr = (expr or '').strip()
    if not expr:
        return [], 'and'
    if '||' in expr:
        partes = [p.strip() for p in expr.split('||')]
        operador = 'or'
    elif '&&' in expr:
        partes = [p.strip() for p in expr.split('&&')]
        operador = 'and'
    else:
        partes, operador = [expr], 'and'
    conds = []
    for p in partes:
        for op in ('==', '!=', '>=', '<=', '>', '<'):
            if op in p:
                izq, der = p.split(op, 1)
                conds.append({
                    'izq': izq.strip(),
                    'op': op,
                    'der': _parse_literal(der.strip()),
                })
                break
    return conds, operador


class Command(BaseCommand):
    help = 'Crea el flujo del cotizador Vida Buena modo MÚLTIPLE (selecciones explícitas).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el depto previo y lo recrea.')
        parser.add_argument('--delete', action='store_true',
                            help='Solo borra el depto y sale.')
        parser.add_argument('--sesion', type=int, default=None,
                            help='ID de SesionWhatsApp para asociar el flujo.')
        parser.add_argument('--base-url', type=str, default=BASE_URL_DEFAULT,
                            help=f'Base URL REST (default: {BASE_URL_DEFAULT}).')
        parser.add_argument('--webhook-url', type=str, default=WEBHOOK_EXTERNO_URL_DEFAULT,
                            help=f'URL del webhook externo (default: {WEBHOOK_EXTERNO_URL_DEFAULT}).')

    def _eliminar_depto(self):
        from crm.models import EstadoFlujoChatbot
        viejos = DepartamentoChatBot.objects.filter(nombre=NOMBRE_DEPTO)
        n_deptos = viejos.count()
        n_estados = EstadoFlujoChatbot.objects.filter(departamento__in=viejos).count()
        n_nodos = OpcionDepartamentoChatBot.objects.filter(departamento__in=viejos).count()
        n_conn = ConexionNodoChatbot.objects.filter(nodo_origen__departamento__in=viejos).count()

        EstadoFlujoChatbot.objects.filter(departamento__in=viejos).delete()
        viejos.delete()

        huerfanos = EstadoFlujoChatbot.objects.filter(departamento__isnull=True)
        n_huerf = huerfanos.count()
        if n_huerf:
            huerfanos.delete()

        return {
            'deptos': n_deptos, 'nodos': n_nodos, 'conexiones': n_conn,
            'estados': n_estados, 'huerfanos': n_huerf,
        }

    def _config_para(self, paso):
        t = paso['tipo']
        if t == 'respuesta_texto' or t == 'fin_conversacion':
            cfg = {'mensaje': paso.get('mensaje', '')}
            if paso.get('cta_url'):
                cfg['cta_url'] = paso['cta_url']
                cfg['cta_display_text'] = paso.get('cta_display_text', 'Abrir')
            return cfg
        if t == 'input_texto':
            return {'pregunta': paso.get('mensaje', '')}
        if t == 'menu_botones':
            cfg = {
                'mensaje': paso.get('mensaje', ''),
                'opciones': [
                    {'etiqueta': o['etiqueta'], 'valor': o['valor'], 'salida': o['valor']}
                    for o in paso.get('opciones', [])
                ],
            }
            if paso.get('opciones_fuente'):
                cfg['opciones_fuente'] = paso['opciones_fuente']
            if paso.get('opcion_default'):
                cfg['opcion_default'] = paso['opcion_default']
            return cfg
        if t == 'decision':
            if paso.get('condiciones'):
                return {
                    'condiciones': paso['condiciones'],
                    'operador': paso.get('operador', 'and'),
                }
            conds, operador = _parse_condicion(paso.get('condicion', ''))
            return {'condiciones': conds, 'operador': operador}
        if t == 'asignar_variable':
            return {'asignaciones': [
                {'variable': k, 'expresion': v}
                for k, v in (paso.get('asigna') or {}).items()
            ]}
        if t == 'llamada_http':
            cfg = {
                'metodo': paso.get('metodo', 'GET'),
                'path': paso.get('path', ''),
                'query': paso.get('query') or {},
                'headers': paso.get('headers') or {},
                'body': paso.get('body') or {},
                'extraer': _normalizar_extraer(paso.get('extrae_variables')),
                'timeout_seg': paso.get('timeout_seg', 15),
            }
            if paso.get('envia_correo'):
                cfg['envia_correo'] = True
            return cfg
        if t == 'llamada_funcion':
            cfg = {
                'funcion_codigo': paso.get('funcion_codigo', ''),
                'metodo': paso.get('metodo', 'POST'),
                'body': paso.get('body') or {},
                'extraer': _normalizar_extraer(paso.get('extrae_variables')),
                'timeout_seg': paso.get('timeout_seg', 30),
            }
            if paso.get('envia_correo'):
                cfg['envia_correo'] = True
            return cfg
        return {}

    def _crear_nodo(self, depto, eps, paso):
        t = paso['tipo']
        validacion_tipo = 'none'
        validacion_expr = ''
        if paso.get('validacion_tipo'):
            validacion_tipo = paso['validacion_tipo']
            validacion_expr = paso.get('validacion', '') or ''
        elif paso.get('validacion'):
            validacion_tipo = 'regex'
            validacion_expr = paso['validacion']

        endpoint_obj = None
        if t == 'llamada_http':
            endpoint_obj = eps.get(paso.get('endpoint_key') or 'rest')
        elif t == 'llamada_funcion':
            ep_key = paso.get('endpoint_key')
            if ep_key:
                endpoint_obj = eps.get(ep_key)

        return OpcionDepartamentoChatBot.objects.create(
            departamento=depto,
            nombre=paso.get('nombre') or paso.get('codigo', ''),
            tipo_nodo=TIPO_MAP[t],
            config=self._config_para(paso),
            es_inicio=bool(paso.get('es_inicio')),
            endpoint=endpoint_obj,
            variable_destino=paso.get('guardar_en', '') or '',
            validacion_tipo=validacion_tipo,
            validacion_expresion=validacion_expr,
            mensaje_error='',
            reintentos_max=3,
            orden=paso.get('orden', 0),
        )

    def _crear_conexiones(self, mapa, paso):
        origen = mapa[paso['id']]
        t = paso['tipo']

        if t == 'menu_botones':
            opt_def = paso.get('opcion_default') or {}
            if opt_def:
                if paso.get('siguiente_si') in mapa:
                    ConexionNodoChatbot.objects.create(
                        nodo_origen=origen, nodo_destino=mapa[paso['siguiente_si']],
                        etiqueta=opt_def.get('salida_si', '') or '', orden=1,
                    )
                if paso.get('siguiente_otra') in mapa:
                    ConexionNodoChatbot.objects.create(
                        nodo_origen=origen, nodo_destino=mapa[paso['siguiente_otra']],
                        etiqueta=opt_def.get('salida_otra', '') or '', orden=2,
                    )
                return

            for i, o in enumerate(paso.get('opciones', []), start=1):
                destino_id = o.get('siguiente')
                if destino_id and destino_id in mapa:
                    ConexionNodoChatbot.objects.create(
                        nodo_origen=origen, nodo_destino=mapa[destino_id],
                        etiqueta=o['valor'], orden=i,
                    )
            destino_default = paso.get('siguiente')
            if destino_default and destino_default in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen, nodo_destino=mapa[destino_default],
                    etiqueta='', orden=99,
                )
            return

        if t == 'decision':
            if paso.get('siguiente_si') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen, nodo_destino=mapa[paso['siguiente_si']],
                    etiqueta='true', orden=1,
                )
            if paso.get('siguiente_no') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen, nodo_destino=mapa[paso['siguiente_no']],
                    etiqueta='false', orden=2,
                )
            return

        if t in ('llamada_http', 'llamada_funcion'):
            if paso.get('siguiente_ok') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen, nodo_destino=mapa[paso['siguiente_ok']],
                    etiqueta='ok', orden=1,
                )
            if paso.get('siguiente_error') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen, nodo_destino=mapa[paso['siguiente_error']],
                    etiqueta='error', orden=2,
                )
            return

        if paso.get('siguiente') in mapa:
            ConexionNodoChatbot.objects.create(
                nodo_origen=origen, nodo_destino=mapa[paso['siguiente']],
                etiqueta='', orden=1,
            )

    @transaction.atomic
    def handle(self, *args, **opts):
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
                    f'Conexiones: {res["conexiones"]}'
                ))
            return

        if opts['reset']:
            res = self._eliminar_depto()
            self.stdout.write(self.style.WARNING(
                f'Reset: borrado depto "{NOMBRE_DEPTO}" '
                f'({res["nodos"]} nodos, {res["conexiones"]} conexiones).'
            ))

        depto, creado = DepartamentoChatBot.objects.get_or_create(
            nombre=NOMBRE_DEPTO,
            defaults={
                'color': BOT['color_primario'],
                'mensaje_saludo': BOT['mensaje_inicial'],
                'palabras_clave': BOT['palabras_clave'],
                'es_default': False,
                'activo_tradicional': True,
                'reset_triggers': BOT['reset_triggers'],
                'mensaje_reset': BOT['mensaje_reset'],
            },
        )
        if not creado:
            self.stdout.write(self.style.WARNING(
                'El depto ya existía. Usa --reset para recrearlo.'
            ))
            return

        credencial, _ = CredencialApiChatbot.objects.get_or_create(
            nombre=CREDENCIAL_NOMBRE,
            tipo='none',
            status=True,
            defaults={
                'secretos': {},
                'descripcion': 'API REST pública del cotizador Vida Buena (CSRF-exempt).',
            },
        )
        ep, _ = EndpointApiChatbot.objects.get_or_create(
            nombre=ENDPOINT_NOMBRE,
            base_url=opts['base_url'].rstrip('/'),
            status=True,
            defaults={
                'credencial': credencial,
                'headers_default': {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                'timeout_seg': 60,
                'descripcion': (
                    'Endpoint base REST del cotizador Vida Buena '
                    '(lectura de cliente, planes, recomendar).'
                ),
            },
        )
        if ep.credencial_id != credencial.id:
            ep.credencial = credencial
            ep.save()

        webhook_ext_credencial, _ = CredencialApiChatbot.objects.get_or_create(
            nombre=WEBHOOK_EXTERNO_CREDENCIAL_NOMBRE,
            tipo='none',
            status=True,
            defaults={
                'secretos': {},
                'descripcion': 'Credencial dummy para webhook externo (sin auth).',
            },
        )
        webhook_ext_ep, _ = EndpointApiChatbot.objects.get_or_create(
            nombre=WEBHOOK_EXTERNO_ENDPOINT_NOMBRE,
            defaults={
                'base_url': opts['webhook_url'],
                'status': True,
                'credencial': webhook_ext_credencial,
                'headers_default': {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                'timeout_seg': WEBHOOK_EXTERNO_TIMEOUT_DEFAULT,
                'descripcion': (
                    'Webhook EXTERNO del cotizador médico Vida Buena. Las '
                    'funciones `cotizar_am` y `cotizar_am_multiple` (registry '
                    'crm.funciones_chatbot) usan este endpoint para hacer el '
                    'POST outbound. Editá la base_url acá para cambiar de '
                    'proveedor sin tocar código.'
                ),
            },
        )

        eps = {'rest': ep, 'webhook_externo': webhook_ext_ep}

        mapa = {}
        for paso in PASOS:
            mapa[paso['id']] = self._crear_nodo(depto, eps, paso)

        for paso in PASOS:
            self._crear_conexiones(mapa, paso)

        if opts.get('sesion'):
            from whatsapp.models import SesionWhatsApp
            try:
                s = SesionWhatsApp.objects.get(pk=opts['sesion'])
            except SesionWhatsApp.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f'Sesión #{opts["sesion"]} no existe.'
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
                    f'modo_bot={s.modo_bot}.'
                ))

        total_nodos = depto.opciondepartamentochatbot_set.count()
        total_conns = ConexionNodoChatbot.objects.filter(
            nodo_origen__departamento=depto
        ).count()
        self.stdout.write(self.style.SUCCESS(
            f'\n[OK] Flujo creado: "{depto.nombre}"\n'
            f'   Nodos: {total_nodos}  |  Conexiones: {total_conns}\n'
            f'   Endpoint REST        : {ep.nombre} -> {ep.base_url}\n'
            f'   Endpoint Webhook ext : {webhook_ext_ep.nombre} -> {webhook_ext_ep.base_url}\n'
            f'   Credencial REST      : {credencial.nombre} ({credencial.get_tipo_display()})\n'
            f'   Función registrada   : cotizar_am_multiple (crm.funciones_chatbot)\n'
        ))
