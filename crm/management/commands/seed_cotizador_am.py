"""
Seed del cotizador Vida Buena (asistencia médica — función Python + webhook).

Mismo enfoque que `seed_cotizador` (ARIA):
  1. El flujo recolecta cliente + miembros del grupo + intención de presupuesto.
  2. Llega al nodo `funcion=cotizar_am` (registrado en `crm.funciones_chatbot`).
  3. Esa función arma el body con `members[]` (titular + dependientes), hace
     POST al webhook externo del cotizador médico (URL leída desde el
     `EndpointApiChatbot` 'Vida Buena — Webhook Cotizador (externo)' —
     editable desde /crm/endpoints_api/ sin tocar este archivo).
  4. El webhook hace el resto en background: corre el decision engine,
     genera PDFs, envía correo y manda el resumen por WhatsApp si vino
     `id_conversacion`.

El cliente recibe en WhatsApp solo "estamos procesando" (ok) o
"intentá más tarde" (error). La recomendación, el plan y los PDFs los
manda el webhook por email + WhatsApp en background.

Flujo (resumido):
  saludo → cédula → GET ?action=cliente&cedula= →
    encontrado: confirmar email/teléfono faltantes; si faltan edad/sexo,
                pedirlos como número (no fecha).
    no encontrado: pedir nombres / apellidos / email / teléfono / edad / sexo.
  → tipo de grupo (individual / titular+1 / familia)
  → si titular+1 o familia: edades de los demás miembros (lista por coma)
  → intención de presupuesto (económico / equilibrio / alta protección)
  → "⏳ analizando..." → función cotizar_am → mensaje de cierre
  → handoff opcional al asesor.

Uso:
    python manage.py seed_cotizador_am
    python manage.py seed_cotizador_am --reset
    python manage.py seed_cotizador_am --delete
    python manage.py seed_cotizador_am --sesion 5
    python manage.py seed_cotizador_am --base-url https://otro.dominio.ec/cotimedica-api/v1/
    python manage.py seed_cotizador_am --webhook-url https://otro.dominio.ec/cotimedica/webhook/
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'Vida Buena — Cotizador asistencia médica'

BASE_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/cotimedica-api/v1/'

CREDENCIAL_NOMBRE = 'Vida Buena REST - AllowAny'
ENDPOINT_NOMBRE = 'Cotizador Vida Buena REST v1'

WEBHOOK_EXTERNO_CREDENCIAL_NOMBRE = 'Vida Buena Webhook Externo (sin auth)'
WEBHOOK_EXTERNO_ENDPOINT_NOMBRE = 'Vida Buena — Webhook Cotizador (externo)'
WEBHOOK_EXTERNO_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/cotimedica/webhook/'
WEBHOOK_EXTERNO_TIMEOUT_DEFAULT = 45


BOT = {
    'codigo': 'vida_buena',
    'nombre': NOMBRE_DEPTO,
    'descripcion': (
        'Asistente virtual que recomienda un plan de asistencia médica '
        'Vida Buena y deriva al asesor para cierre.'
    ),
    'mensaje_inicial': (
        'Hola 👋 Soy tu asesor de Vida Buena 🏥. Te ayudo a encontrar el plan '
        'ideal sin complicarte. Solo necesito unos datos rápidos.'
    ),
    'color_primario': '#198754',
    'palabras_clave': (
        'vida buena\nasistencia\nmedica\nmédica\nplan medico\nplan médico\n'
        'salud\nseguro medico\nseguro médico\ncotizar salud\ncotizar plan\n'
        'cotizar medico\ncotizar médico'
    ),
    'reset_triggers': [
        'reiniciar', 'cancelar', 'volver al inicio', 'empezar de nuevo',
        'otra cotizacion', 'cotizar otra', 'otra persona', 'reset',
    ],
    'mensaje_reset': '🔄 Listo, empezamos de nuevo. Olvidé los datos anteriores.',
}


PASOS = [
    # ── 10 — Saludo ─────────────────────────────────────────────
    {
        'id': 10, 'orden': 10, 'tipo': 'respuesta_texto',
        'codigo': 'saludo_inicial', 'nombre': 'Saludo de bienvenida',
        'es_inicio': True,
        'mensaje': BOT['mensaje_inicial'],
        'siguiente': 20,
    },

    # ── 20/30/40 — Cédula + lookup cliente ─────────────────────
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
        'siguiente_ok': 40, 'siguiente_error': 100,
    },
    {
        'id': 40, 'orden': 40, 'tipo': 'decision',
        'codigo': 'cliente_encontrado', 'nombre': '¿Cliente encontrado?',
        'condicion': '{{variables.encontrado_cli}} == true',
        'siguiente_si': 50, 'siguiente_no': 100,
    },

    # ── 50 — Mostrar datos encontrados ─────────────────────────
    {
        'id': 50, 'orden': 50, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_cliente', 'nombre': 'Mostrar datos del cliente',
        'mensaje': (
            '✅ Encontré tus datos:\n'
            '• Nombre: *{{variables.nombres}} {{variables.apellidos}}*'
        ),
        'siguiente': 60,
    },

    # ── 60/62 — Email faltante ─────────────────────────────────
    {
        'id': 60, 'orden': 60, 'tipo': 'decision',
        'codigo': 'email_vacio', 'nombre': '¿Email vacío?',
        'condiciones': [{'izq': '{{variables.email}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 62, 'siguiente_no': 70,
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
        'siguiente': 70,
    },

    # ── 70/72 — Teléfono faltante ──────────────────────────────
    {
        'id': 70, 'orden': 70, 'tipo': 'decision',
        'codigo': 'telefono_vacio', 'nombre': '¿Teléfono vacío?',
        'condiciones': [{'izq': '{{variables.telefono}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 72, 'siguiente_no': 80,
    },
    {
        'id': 72, 'orden': 72, 'tipo': 'input_texto',
        'codigo': 'pedir_telefono_faltante', 'nombre': 'Pedir teléfono (faltante)',
        'mensaje': '📱 ¿Tu *celular*? (10 dígitos, empieza con 0)',
        'guardar_en': 'telefono',
        'validacion': r'^0[0-9]{9}$',
        'siguiente': 80,
    },

    # ── 80/90 — Edad faltante (siempre número, no fecha) ───────
    {
        'id': 80, 'orden': 80, 'tipo': 'decision',
        'codigo': 'edad_vacia', 'nombre': '¿Edad vacía?',
        'condiciones': [{'izq': '{{variables.edad_titular}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 90, 'siguiente_no': 85,
    },
    {
        'id': 90, 'orden': 90, 'tipo': 'input_texto',
        'codigo': 'pedir_edad', 'nombre': 'Pedir edad (titular)',
        'mensaje': '🎂 ¿Cuál es tu *edad*? (solo el número, ej: 35)',
        'guardar_en': 'edad_titular',
        'validacion': r'^\d{1,3}$',
        'siguiente': 85,
    },

    # ── 85/95 — Sexo faltante ──────────────────────────────────
    {
        'id': 85, 'orden': 85, 'tipo': 'decision',
        'codigo': 'sexo_vacio', 'nombre': '¿Sexo vacío?',
        'condiciones': [{'izq': '{{variables.sexo_titular}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 95, 'siguiente_no': 170,
    },
    {
        'id': 95, 'orden': 95, 'tipo': 'menu_botones',
        'codigo': 'pedir_sexo', 'nombre': 'Pedir sexo (titular)',
        'mensaje': '👤 ¿Cuál es tu *sexo*?',
        'guardar_en': 'sexo_titular',
        'opciones': [
            {'etiqueta': '👨 Masculino', 'valor': 'M', 'siguiente': 170},
            {'etiqueta': '👩 Femenino',  'valor': 'F', 'siguiente': 170},
        ],
    },

    # ── 100..150 — Cliente NO encontrado: pedir todo manual ────
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
        'codigo': 'pedir_telefono_nuevo', 'nombre': 'Pedir teléfono',
        'mensaje': '📱 ¿Tu *celular*? (10 dígitos, empieza con 0)',
        'guardar_en': 'telefono',
        'validacion': r'^0[0-9]{9}$',
        'siguiente': 140,
    },
    {
        'id': 140, 'orden': 140, 'tipo': 'input_texto',
        'codigo': 'pedir_edad_nuevo', 'nombre': 'Pedir edad',
        'mensaje': '🎂 ¿Cuál es tu *edad*? (solo el número, ej: 35)',
        'guardar_en': 'edad_titular',
        'validacion': r'^\d{1,3}$',
        'siguiente': 150,
    },
    {
        'id': 150, 'orden': 150, 'tipo': 'menu_botones',
        'codigo': 'pedir_sexo_nuevo', 'nombre': 'Pedir sexo',
        'mensaje': '👤 ¿Cuál es tu *sexo*?',
        'guardar_en': 'sexo_titular',
        'opciones': [
            {'etiqueta': '👨 Masculino', 'valor': 'M', 'siguiente': 170},
            {'etiqueta': '👩 Femenino',  'valor': 'F', 'siguiente': 170},
        ],
    },

    # ── 170 — Tipo de grupo ────────────────────────────────────
    {
        'id': 170, 'orden': 170, 'tipo': 'menu_botones',
        'codigo': 'tipo_grupo', 'nombre': 'Tipo de grupo',
        'mensaje': '👨‍👩‍👧 ¿El plan es solo para ti o también para tu familia?',
        'guardar_en': 'tipo_grupo',
        'opciones': [
            {'etiqueta': '🙋 Solo para mí',     'valor': 'individual',      'siguiente': 200},
            {'etiqueta': '👫 Yo y una persona', 'valor': 'titular_mas_uno', 'siguiente': 180},
            {'etiqueta': '👨‍👩‍👧 Mi familia', 'valor': 'familia',         'siguiente': 180},
        ],
    },

    # ── 180 — Edades de los miembros adicionales ───────────────
    {
        'id': 180, 'orden': 180, 'tipo': 'input_texto',
        'codigo': 'pedir_edades_miembros', 'nombre': 'Edades de miembros',
        'mensaje': (
            '🎂 Indícame las *edades* de los demás miembros separadas por coma '
            '(ej: 38, 16, 12):'
        ),
        'guardar_en': 'edades_miembros',
        'validacion': r'^\s*\d{1,3}(\s*,\s*\d{1,3})*\s*$',
        'siguiente': 200,
    },

    # ── 200 — Intención de presupuesto ─────────────────────────
    {
        'id': 200, 'orden': 200, 'tipo': 'menu_botones',
        'codigo': 'budget_intent', 'nombre': 'Intención de presupuesto',
        'mensaje': '💰 ¿Buscas algo más económico, equilibrado o con mayor protección?',
        'guardar_en': 'budget_intent',
        'opciones': [
            {'etiqueta': '💵 Económico',        'valor': 'economico',       'siguiente': 210},
            {'etiqueta': '⚖️ Equilibrado',      'valor': 'equilibrio',      'siguiente': 210},
            {'etiqueta': '🛡️ Mayor protección', 'valor': 'alta_proteccion', 'siguiente': 210},
        ],
    },

    # ── 210 — Aviso "esperando cotización" ─────────────────────
    {
        'id': 210, 'orden': 210, 'tipo': 'respuesta_texto',
        'codigo': 'esperando_cotizacion', 'nombre': 'Mensaje esperando',
        'mensaje': (
            '⏳ Estamos analizando tu perfil y preparando la mejor recomendación...'
        ),
        'siguiente': 220,
    },

    # ── 220 — Función interna `cotizar_am` (POST al webhook) ────
    {
        'id': 220, 'orden': 220, 'tipo': 'llamada_funcion',
        'codigo': 'fn_cotizar_am',
        'nombre': 'Función → Cotizar Vida Buena + email asesores',
        'funcion_codigo': 'cotizar_am',
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
                'telefono':         '{{variables.telefono}}',
            },
            'budget_intent':         '{{variables.budget_intent}}',
            'network_preference':    'desconocido',
            'wants_max_protection':  False,
        },
        'extrae_variables': {
            '$cotizacion_status':  '$.status',
            '$cotizacion_mensaje': '$.message',
        },
        'siguiente_ok': 230, 'siguiente_error': 240,
    },

    # ── 230 — Confirmación inmediata (la recomendación llega
    #          por el webhook async vía WhatsApp + correo) ───────
    {
        'id': 230, 'orden': 230, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_encolada', 'nombre': 'Cotización en proceso',
        'mensaje': (
            '✅ ¡Listo! Estamos procesando tu cotización.\n\n'
            'En breve recibirás aquí mismo la *recomendación de plan* y '
            'el detalle por *correo electrónico*. 🏥💜'
        ),
        'siguiente': 250,
    },

    # ── 240 — Error al cotizar ─────────────────────────────────
    {
        'id': 240, 'orden': 240, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_error', 'nombre': 'Error al cotizar',
        'mensaje': (
            '⚠️ No pudimos procesar tu cotización en este momento. '
            'Por favor inténtalo más tarde. 🙏'
        ),
        'siguiente': 999,
    },

    # ── 250..270 — Handoff a asesor ────────────────────────────
    {
        'id': 250, 'orden': 250, 'tipo': 'menu_botones',
        'codigo': 'handoff_asesor', 'nombre': '¿Contactar asesor?',
        'mensaje': (
            '¿Deseas que un *asesor* te contacte para validar datos y avanzar '
            'con la activación?'
        ),
        'guardar_en': 'quiere_asesor',
        'opciones': [
            {'etiqueta': '✅ Sí, contáctenme',  'valor': 'si', 'siguiente': 260},
            {'etiqueta': '👀 Solo informativo', 'valor': 'no', 'siguiente': 270},
        ],
    },
    {
        'id': 260, 'orden': 260, 'tipo': 'respuesta_texto',
        'codigo': 'handoff_aceptado', 'nombre': 'Handoff aceptado',
        'mensaje': (
            '🤝 Excelente. Un asesor te contactará en breve para confirmar '
            'la tarifa exacta y la activación.'
        ),
        'siguiente': 998,
    },
    {
        'id': 270, 'orden': 270, 'tipo': 'respuesta_texto',
        'codigo': 'handoff_rechazado', 'nombre': 'Handoff rechazado',
        'mensaje': (
            '👍 Perfecto. Si más adelante quieres avanzar, escríbenos cuando '
            'gustes. ¡Estamos para ayudarte!'
        ),
        'siguiente': 998,
    },

    # ── Salidas terminales ─────────────────────────────────────
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
            'cedula': '', 'nombres': '', 'apellidos': '',
            'email': '', 'telefono': '',
            'fecha_nacimiento': '', 'edad_titular': '', 'sexo_titular': '',
            'tipo_grupo': '', 'edades_miembros': '',
            'budget_intent': '', 'quiere_asesor': '',
            'cotizacion_status': '', 'cotizacion_mensaje': '',
            'encontrado_cli': '',
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
    help = 'Crea el flujo del cotizador Vida Buena (asistencia médica).'

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
                    'Webhook EXTERNO del cotizador médico Vida Buena. La '
                    'función `cotizar_am` (registry crm.funciones_chatbot) '
                    'usa este endpoint para hacer el POST outbound. Editá '
                    'la base_url acá para cambiar de proveedor sin tocar '
                    'código.'
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
            f'   Función registrada   : cotizar_am (crm.funciones_chatbot)\n'
        ))
