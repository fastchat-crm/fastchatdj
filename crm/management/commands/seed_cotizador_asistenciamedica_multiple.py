"""
Seed del cotizador Vida Buena — modo MÚLTIPLE (titular + N dependientes).

Usa el nodo `loop` del motor para iterar sobre los N miembros en lugar de
duplicar 5 veces el mismo subflujo. Pasa de ~82 a ~30 nodos.

Las variables por miembro se nombran dinamicamente con
`cedula_m{{variables.i}}`, `edad_m{{variables.i}}`, etc. — el motor expande
el nombre de la variable usando `resolver_expresion` (2 pasadas).

Reglas del diálogo:
  1. Pide datos del titular (cédula + lookup REST; si falta algo se pide manual).
  2. Pregunta tipo de presupuesto (al final, antes de procesar).
  3. Pregunta si la cotización es solo titular o titular + N personas.
  4. Si va con N personas, pide N (1..5) y entra al LOOP de captura.
     Cada iteración pide cédula → lookup → si no encontrado pide edad/sexo
     manual → parentesco → muestra datos. Vuelve al loop hasta agotar N.
  5. Otro LOOP de resumen muestra cada miembro antes de disparar
     `cotizar_am_multiple` con `members[]` al webhook externo.

Coexiste con `seed_cotizador_am`.

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

MAX_DEPENDIENTES = 5


BOT = {
    'codigo': 'vida_buena_multiple',
    'nombre': NOMBRE_DEPTO,
    'descripcion': (
        'Asistente Vida Buena que cotiza para titular + N dependientes '
        '(hasta 5) capturando los datos de cada uno paso a paso con loop.'
    ),
    'mensaje_inicial': (
        'Hola 👋 Soy tu asesor de Vida Buena 🏥. Te ayudo a cotizar para ti '
        'o para tu familia en pocos pasos. Empecemos con tus datos.'
    ),
    'color_primario': '#0d6efd',
    'palabras_clave': (
        'vida buena familia\nplan familiar\ncotizar familia\n'
        'titular dependientes\ncotizacion grupo medico\n'
        'plan medico familia\ndependientes salud'
    ),
    'reset_triggers': [
        'reiniciar', 'cancelar', 'volver al inicio', 'empezar de nuevo',
        'otra cotizacion', 'cotizar otra', 'otra persona', 'reset',
    ],
    'mensaje_reset': '🔄 Listo, empezamos de nuevo. Olvidé los datos anteriores.',
}


LOOP_CAPTURA = 222
BODY_CEDULA = 230
BODY_HTTP = 231
BODY_DEC_ENCON = 232
BODY_EDAD = 233
BODY_SEXO = 234
BODY_PAREN = 235
BODY_SHOW = 236

ID_RESUMEN = 450
LOOP_RESUMEN = 451
BODY_RESUMEN_SHOW = 452

ID_BUDGET = 500
ID_ESPERANDO = 510
ID_PERSISTIR_CLIENTE = 515
ID_FN = 520
ID_OK = 530
ID_ERR = 540
ID_HANDOFF = 600
ID_HANDOFF_SI = 610
ID_HANDOFF_NO = 620
ID_ERROR_API = 900
ID_RESET = 998
ID_FIN = 999


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
        'codigo': 'pedir_cedula', 'nombre': 'Pedir cédula del titular',
        'mensaje': '🪪 Para empezar, dame tu *cédula* (10 dígitos):',
        'guardar_en': 'cedula',
        'validacion': r'^[0-9]{10}([0-9]{3})?$',
        'siguiente': 30,
    },
    {
        'id': 30, 'orden': 30, 'tipo': 'llamada_http',
        'codigo': 'http_cliente_titular',
        'nombre': 'GET ?action=cliente — titular',
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
        'codigo': 'cliente_encontrado', 'nombre': '¿Titular encontrado?',
        'condicion': '{{variables.encontrado_cli}} == true',
        'siguiente_si': 50, 'siguiente_no': 100,
    },

    {
        'id': 50, 'orden': 50, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_titular', 'nombre': 'Mostrar datos del titular',
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
        'codigo': 'pedir_email_nuevo_confirm', 'nombre': 'Pedir correo nuevo',
        'mensaje': '📧 Escríbeme el *correo nuevo* al que quieres recibir la cotización:',
        'guardar_en': 'email',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 80,
    },
    {
        'id': 80, 'orden': 80, 'tipo': 'decision',
        'codigo': 'sexo_vacio', 'nombre': '¿Sexo titular vacío?',
        'condiciones': [{'izq': '{{variables.sexo_titular}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 90, 'siguiente_no': 200,
    },
    {
        'id': 90, 'orden': 90, 'tipo': 'menu_botones',
        'codigo': 'pedir_sexo_titular', 'nombre': 'Pedir sexo (titular)',
        'mensaje': '👤 ¿Cuál es tu *sexo*?',
        'guardar_en': 'sexo_titular',
        'opciones': [
            {'etiqueta': '👨 Masculino', 'valor': 'M', 'siguiente': 200},
            {'etiqueta': '👩 Femenino',  'valor': 'F', 'siguiente': 200},
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
        'siguiente': 140,
    },
    {
        'id': 140, 'orden': 140, 'tipo': 'input_texto',
        'codigo': 'pedir_edad_titular', 'nombre': 'Pedir edad (titular)',
        'mensaje': '🎂 Confírmame también tu *edad* (solo el número, ej: 35):',
        'guardar_en': 'edad_titular',
        'validacion': r'^\d{1,3}$',
        'siguiente': 150,
    },
    {
        'id': 150, 'orden': 150, 'tipo': 'menu_botones',
        'codigo': 'pedir_sexo_nuevo', 'nombre': 'Pedir sexo (titular)',
        'mensaje': '👤 ¿Cuál es tu *sexo*?',
        'guardar_en': 'sexo_titular',
        'opciones': [
            {'etiqueta': '👨 Masculino', 'valor': 'M', 'siguiente': 200},
            {'etiqueta': '👩 Femenino',  'valor': 'F', 'siguiente': 200},
        ],
    },

    {
        'id': 200, 'orden': 200, 'tipo': 'menu_botones',
        'codigo': 'tipo_grupo', 'nombre': '¿Solo titular o con familia?',
        'mensaje': (
            '👨‍👩‍👧 ¿Vas a cotizar *solo para ti* o *para ti y otras '
            'personas*?'
        ),
        'guardar_en': 'tipo_cobertura',
        'opciones': [
            {'etiqueta': '🙋 Solo para mí',          'valor': 'solo', 'siguiente': 210},
            {'etiqueta': '👨‍👩‍👧 Con otras personas', 'valor': 'mas',  'siguiente': 220},
        ],
    },
    {
        'id': 210, 'orden': 210, 'tipo': 'asignar_variable',
        'codigo': 'set_num_dep_cero', 'nombre': 'num_dependientes = 0',
        'asigna': {'num_dependientes': '0'},
        'siguiente': ID_BUDGET,
    },
    {
        'id': 220, 'orden': 220, 'tipo': 'input_texto',
        'codigo': 'pedir_num_dependientes', 'nombre': '¿Cuántas personas más?',
        'mensaje': (
            f'🔢 ¿Cuántas personas *además de ti* van en la cotización? '
            f'(escribe un número del 1 al {MAX_DEPENDIENTES})'
        ),
        'guardar_en': 'num_dependientes',
        'validacion': rf'^[1-{MAX_DEPENDIENTES}]$',
        'siguiente': LOOP_CAPTURA,
    },

    {
        'id': LOOP_CAPTURA, 'orden': LOOP_CAPTURA, 'tipo': 'loop_iter',
        'codigo': 'loop_captura_miembros', 'nombre': 'Loop captura miembros',
        'iterations_expr': '{{variables.num_dependientes}}',
        'index_var': 'i',
        'base_index': 1,
        'siguiente_body': BODY_CEDULA,
        'siguiente_done': ID_BUDGET,
    },
    {
        'id': BODY_CEDULA, 'orden': BODY_CEDULA, 'tipo': 'input_texto',
        'codigo': 'pedir_cedula_miembro', 'nombre': 'Cédula miembro {{i}}',
        'mensaje': (
            '🪪 Dame la *cédula* del miembro #{{variables.i}} (10 dígitos). '
            'Si no la tienes a mano, escribe `0` y luego pediré su edad.'
        ),
        'guardar_en': 'cedula_m{{variables.i}}',
        'validacion': r'^(0|[0-9]{10}([0-9]{3})?)$',
        'siguiente': BODY_HTTP,
    },
    {
        'id': BODY_HTTP, 'orden': BODY_HTTP, 'tipo': 'llamada_http',
        'codigo': 'http_cliente_miembro',
        'nombre': 'GET ?action=cliente miembro {{i}}',
        'metodo': 'GET', 'path': '',
        'query': {
            'action': 'cliente',
            'cedula': '{{variables.cedula_m{{variables.i}}}}',
        },
        'timeout_seg': 20,
        'extrae_variables': {
            '$encontrado_m{{variables.i}}': '$.data.encontrado',
            '$edad_m{{variables.i}}':       '$.data.edad',
            '$sexo_m{{variables.i}}':       '$.data.sexo',
            '$nombres_m{{variables.i}}':    '$.data.nombres',
            '$apellidos_m{{variables.i}}':  '$.data.apellidos',
        },
        'siguiente_ok': BODY_DEC_ENCON, 'siguiente_error': BODY_EDAD,
    },
    {
        'id': BODY_DEC_ENCON, 'orden': BODY_DEC_ENCON, 'tipo': 'decision',
        'codigo': 'decision_encontrado_miembro',
        'nombre': '¿Miembro {{i}} en registro civil?',
        'condicion': '{{variables.encontrado_m{{variables.i}}}} == true',
        'siguiente_si': BODY_PAREN, 'siguiente_no': BODY_EDAD,
    },
    {
        'id': BODY_EDAD, 'orden': BODY_EDAD, 'tipo': 'input_texto',
        'codigo': 'pedir_edad_miembro', 'nombre': 'Edad miembro {{i}}',
        'mensaje': (
            '🎂 ¿Qué *edad* tiene el miembro #{{variables.i}}? '
            '(solo el número, ej: 12)'
        ),
        'guardar_en': 'edad_m{{variables.i}}',
        'validacion': r'^\d{1,3}$',
        'siguiente': BODY_SEXO,
    },
    {
        'id': BODY_SEXO, 'orden': BODY_SEXO, 'tipo': 'menu_botones',
        'codigo': 'pedir_sexo_miembro', 'nombre': 'Sexo miembro {{i}}',
        'mensaje': '👤 ¿Cuál es el *sexo* del miembro #{{variables.i}}?',
        'guardar_en': 'sexo_m{{variables.i}}',
        'opciones': [
            {'etiqueta': '👨 Masculino', 'valor': 'M', 'siguiente': BODY_PAREN},
            {'etiqueta': '👩 Femenino',  'valor': 'F', 'siguiente': BODY_PAREN},
        ],
    },
    {
        'id': BODY_PAREN, 'orden': BODY_PAREN, 'tipo': 'menu_botones',
        'codigo': 'pedir_parentesco_miembro',
        'nombre': 'Parentesco miembro {{i}}',
        'mensaje': (
            '👨‍👩‍👧 ¿Qué *parentesco* tiene el miembro #{{variables.i}} contigo?'
        ),
        'guardar_en': 'parentesco_m{{variables.i}}',
        'opciones': [
            {'etiqueta': '💑 Cónyuge', 'valor': 'CONYUGE', 'siguiente': BODY_SHOW},
            {'etiqueta': '🧒 Hijo/a',  'valor': 'HIJO',    'siguiente': BODY_SHOW},
            {'etiqueta': '👨 Padre',    'valor': 'PADRE',   'siguiente': BODY_SHOW},
            {'etiqueta': '👩 Madre',    'valor': 'MADRE',   'siguiente': BODY_SHOW},
            {'etiqueta': '👤 Otro',     'valor': 'OTRO',    'siguiente': BODY_SHOW},
        ],
    },
    {
        'id': BODY_SHOW, 'orden': BODY_SHOW, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_datos_miembro',
        'nombre': 'Mostrar datos miembro {{i}}',
        'mensaje': (
            '✅ Datos del miembro #{{variables.i}} registrados:\n'
            '• Parentesco: *{{variables.parentesco_m{{variables.i}}}}*\n'
            '• Edad: *{{variables.edad_m{{variables.i}}}}*\n'
            '• Sexo: *{{variables.sexo_m{{variables.i}}}}*'
        ),
        'siguiente': LOOP_CAPTURA,
    },

    {
        'id': ID_BUDGET, 'orden': ID_BUDGET, 'tipo': 'menu_botones',
        'codigo': 'budget_intent', 'nombre': 'Intención de presupuesto',
        'mensaje': (
            '💰 ¿Qué *tipo de plan* querés cotizar? Elige según tu '
            'presupuesto:'
        ),
        'guardar_en': 'budget_intent',
        'opciones': [
            {'etiqueta': '💵 Económico',         'valor': 'economico',       'siguiente': ID_RESUMEN},
            {'etiqueta': '⚖️ Equilibrado',       'valor': 'equilibrio',      'siguiente': ID_RESUMEN},
            {'etiqueta': '🛡️ Mayor protección',  'valor': 'alta_proteccion', 'siguiente': ID_RESUMEN},
        ],
    },
    {
        'id': ID_RESUMEN, 'orden': ID_RESUMEN, 'tipo': 'respuesta_texto',
        'codigo': 'resumen_titular', 'nombre': 'Resumen titular + plan',
        'mensaje': (
            '📋 ¡Listo! Cotizaremos con estos datos:\n\n'
            '👤 *Titular*\n'
            '• Nombre: *{{variables.nombres}} {{variables.apellidos}}*\n'
            '• Cédula: *{{variables.cedula}}*\n'
            '• Edad: *{{variables.edad_titular}}*\n'
            '• Sexo: *{{variables.sexo_titular}}*\n'
            '• Email: *{{variables.email}}*\n\n'
            '💰 Tipo de plan: *{{variables.budget_intent}}*'
        ),
        'siguiente': LOOP_RESUMEN,
    },

    {
        'id': LOOP_RESUMEN, 'orden': LOOP_RESUMEN, 'tipo': 'loop_iter',
        'codigo': 'loop_resumen_miembros', 'nombre': 'Loop resumen miembros',
        'iterations_expr': '{{variables.num_dependientes}}',
        'index_var': 'i',
        'base_index': 1,
        'siguiente_body': BODY_RESUMEN_SHOW,
        'siguiente_done': ID_ESPERANDO,
    },
    {
        'id': BODY_RESUMEN_SHOW, 'orden': BODY_RESUMEN_SHOW, 'tipo': 'respuesta_texto',
        'codigo': 'resumen_miembro', 'nombre': 'Resumen miembro {{i}}',
        'mensaje': (
            '👥 *Miembro {{variables.i}}*\n'
            '• Parentesco: *{{variables.parentesco_m{{variables.i}}}}*\n'
            '• Edad: *{{variables.edad_m{{variables.i}}}}*\n'
            '• Sexo: *{{variables.sexo_m{{variables.i}}}}*'
        ),
        'siguiente': LOOP_RESUMEN,
    },

    {
        'id': ID_ESPERANDO, 'orden': ID_ESPERANDO, 'tipo': 'respuesta_texto',
        'codigo': 'esperando_cotizacion', 'nombre': 'Mensaje esperando',
        'mensaje': (
            '⏳ Estamos analizando tu perfil y preparando la mejor '
            'recomendación...'
        ),
        'siguiente': ID_PERSISTIR_CLIENTE,
    },
    {
        'id': ID_PERSISTIR_CLIENTE, 'orden': ID_PERSISTIR_CLIENTE, 'tipo': 'llamada_funcion',
        'codigo': 'fn_cliente_upsert', 'nombre': 'Guardar Cliente + origen',
        'funcion_codigo': 'cliente_upsert',
        'metodo': 'POST', 'timeout_seg': 5,
        'body': {'canal_origen': 'cotizador'},
        'extrae_variables': {
            '$cliente_id':     '$.cliente_id',
            '$cliente_creado': '$.cliente_creado',
        },
        # No bloquea la cotización si falla el guardado local.
        'siguiente_ok': ID_FN, 'siguiente_error': ID_FN,
    },
    {
        'id': ID_FN, 'orden': ID_FN, 'tipo': 'llamada_funcion',
        'codigo': 'fn_cotizar_am_multiple',
        'nombre': 'Función → Cotizar Vida Buena múltiple (members[])',
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
                'email':            'hllerenaa1h@gmail.com',
            },
            'budget_intent':        '{{variables.budget_intent}}',
        },
        'extrae_variables': {
            '$cotizacion_status':  '$.status',
            '$cotizacion_mensaje': '$.message',
        },
        'siguiente_ok': ID_OK, 'siguiente_error': ID_ERR,
    },
    {
        'id': ID_OK, 'orden': ID_OK, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_encolada', 'nombre': 'Cotización en proceso',
        'mensaje': (
            '✅ ¡Listo! Estamos procesando tu cotización.\n\n'
            'En breve recibirás aquí mismo la *recomendación de plan* y '
            'el detalle por *correo electrónico*. 🏥💜'
        ),
        'siguiente': ID_HANDOFF,
    },
    {
        'id': ID_ERR, 'orden': ID_ERR, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_error', 'nombre': 'Error al cotizar',
        'mensaje': (
            '⚠️ No pudimos procesar tu cotización en este momento. '
            'Por favor inténtalo más tarde. 🙏'
        ),
        'siguiente': ID_FIN,
    },

    {
        'id': ID_HANDOFF, 'orden': ID_HANDOFF, 'tipo': 'menu_botones',
        'codigo': 'handoff_asesor', 'nombre': '¿Contactar asesor?',
        'mensaje': (
            '¿Deseas que un *asesor* te contacte para validar datos y avanzar '
            'con la activación?'
        ),
        'guardar_en': 'quiere_asesor',
        'opciones': [
            {'etiqueta': '✅ Sí, contáctenme',  'valor': 'si', 'siguiente': ID_HANDOFF_SI},
            {'etiqueta': '👀 Solo informativo', 'valor': 'no', 'siguiente': ID_HANDOFF_NO},
        ],
    },
    {
        'id': ID_HANDOFF_SI, 'orden': ID_HANDOFF_SI, 'tipo': 'respuesta_texto',
        'codigo': 'handoff_aceptado', 'nombre': 'Handoff aceptado',
        'mensaje': (
            '🤝 Excelente. Un asesor te contactará en breve para confirmar '
            'la tarifa exacta y la activación.'
        ),
        'siguiente': ID_RESET,
    },
    {
        'id': ID_HANDOFF_NO, 'orden': ID_HANDOFF_NO, 'tipo': 'respuesta_texto',
        'codigo': 'handoff_rechazado', 'nombre': 'Handoff rechazado',
        'mensaje': (
            '👍 Perfecto. Si más adelante quieres avanzar, escríbenos cuando '
            'gustes. ¡Estamos para ayudarte!'
        ),
        'siguiente': ID_RESET,
    },

    {
        'id': ID_ERROR_API, 'orden': ID_ERROR_API, 'tipo': 'respuesta_texto',
        'codigo': 'error_api', 'nombre': 'Error genérico de API',
        'mensaje': '⚠️ Hubo un problema al hablar con el servidor. Intenta más tarde.',
        'siguiente': ID_FIN,
    },
    {
        'id': ID_RESET, 'orden': ID_RESET, 'tipo': 'asignar_variable',
        'codigo': 'reset_sesion', 'nombre': 'Reset de variables',
        'asigna': {
            'cedula': '', 'nombres': '', 'apellidos': '', 'email': '',
            'fecha_nacimiento': '', 'edad_titular': '', 'sexo_titular': '',
            'telefono': '', 'encontrado_cli': '', 'confirma_correo': '',
            'tipo_cobertura': '', 'num_dependientes': '', 'i': '',
            'cedula_m1': '', 'edad_m1': '', 'sexo_m1': '', 'encontrado_m1': '',
            'parentesco_m1': '', 'nombres_m1': '', 'apellidos_m1': '',
            'cedula_m2': '', 'edad_m2': '', 'sexo_m2': '', 'encontrado_m2': '',
            'parentesco_m2': '', 'nombres_m2': '', 'apellidos_m2': '',
            'cedula_m3': '', 'edad_m3': '', 'sexo_m3': '', 'encontrado_m3': '',
            'parentesco_m3': '', 'nombres_m3': '', 'apellidos_m3': '',
            'cedula_m4': '', 'edad_m4': '', 'sexo_m4': '', 'encontrado_m4': '',
            'parentesco_m4': '', 'nombres_m4': '', 'apellidos_m4': '',
            'cedula_m5': '', 'edad_m5': '', 'sexo_m5': '', 'encontrado_m5': '',
            'parentesco_m5': '', 'nombres_m5': '', 'apellidos_m5': '',
            'budget_intent': '', 'quiere_asesor': '',
            'cotizacion_status': '', 'cotizacion_mensaje': '',
        },
        'siguiente': ID_FIN,
    },
    {
        'id': ID_FIN, 'orden': ID_FIN, 'tipo': 'fin_conversacion',
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
    'loop_iter':        'loop',
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
    help = 'Crea el flujo del cotizador Vida Buena modo MÚLTIPLE (titular + N dependientes) usando loop.'

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
        if t == 'loop_iter':
            return {
                'iterations_expr': paso.get('iterations_expr', '0'),
                'index_var': paso.get('index_var', 'i'),
                'base_index': paso.get('base_index', 1),
                'body_label': paso.get('body_label', 'body'),
                'done_label': paso.get('done_label', 'done'),
            }
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

        if t == 'loop_iter':
            body_label = paso.get('body_label', 'body')
            done_label = paso.get('done_label', 'done')
            if paso.get('siguiente_body') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen, nodo_destino=mapa[paso['siguiente_body']],
                    etiqueta=body_label, orden=1,
                )
            if paso.get('siguiente_done') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen, nodo_destino=mapa[paso['siguiente_done']],
                    etiqueta=done_label, orden=2,
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
