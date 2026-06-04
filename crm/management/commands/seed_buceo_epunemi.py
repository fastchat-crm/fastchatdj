"""
Seed del flujo de inscripción al curso de Buceo Industrial & Subacuático de EPUNEMI.

Bot tradicional (motor de flujo) que:
  1. Saluda y pide la cédula (10 dígitos).
  2. Consulta la cédula con la función interna `consultar_cedula_sagest`
     (crm.funciones_chatbot), que hace el GET a la API SAGEST (recurso
     consultacedulapersona/, cascada persona → unemi → ister) → trae origen,
     nombres, apellidos, fecha de nacimiento y edad. Rama ok=encontrada,
     error=no encontrada → captura manual.
  3. Valida mayoría de edad (>= 18). Si es menor, cierra cordialmente.
  4. Menú informativo (curso, requisitos, costos, duración) + opción inscribirse.
  5. Captura correo y ciudad, registra la pre-inscripción (POST) en SAGEST.
  6. Termina notificando a un asesor (handoff → auto_asignar_agente).

Sigue el mismo patrón que `seed_cotizador_asistenciamedica_multiple`.

Uso:
    python manage.py seed_buceo_epunemi
    python manage.py seed_buceo_epunemi --reset
    python manage.py seed_buceo_epunemi --delete
    python manage.py seed_buceo_epunemi --sesion 39
    python manage.py seed_buceo_epunemi --base-url https://sagest.epunemi.gob.ec/apimobile/v1/
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'EPUNEMI — Inscripción Buceo Industrial'

BASE_URL_DEFAULT = 'https://sagest.epunemi.gob.ec/apimobile/v1/'

CREDENCIAL_NOMBRE = 'SAGEST EPUNEMI REST (sin auth)'
ENDPOINT_NOMBRE = 'SAGEST EPUNEMI apimobile v1'


BOT = {
    'nombre': NOMBRE_DEPTO,
    'mensaje_inicial': (
        '¡Hola! 👋 Bienvenido a *EPUNEMI* — Formación Técnica en '
        '*Buceo Industrial & Subacuático* ⚓\n\n'
        'Para darte información personalizada necesito tu número de cédula.'
    ),
    'color_primario': '#0d6efd',
    'palabras_clave': (
        'buceo\nbuceo industrial\ncurso buceo\nbuceo subacuatico\n'
        'inscripcion buceo\nepunemi buceo\nformacion buceo'
    ),
    'reset_triggers': [
        'reiniciar', 'cancelar', 'volver al inicio', 'empezar de nuevo',
        'menu', 'inicio', 'reset',
    ],
    'mensaje_reset': '🔄 Listo, empezamos de nuevo desde el inicio.',
}


# IDs de nodos
ID_SALUDO = 10
ID_PEDIR_CEDULA = 20
ID_HTTP_CEDULA = 30
ID_EVAL_EDAD = 40
ID_CONFIRMA_DATOS = 45
ID_MENU = 50
ID_INFO_CURSO = 60
ID_REQUISITOS = 70
ID_COSTOS = 80
ID_DURACION = 90
ID_PREGUNTA_INSC = 100
ID_DEC_CORREO = 105
ID_PEDIR_CORREO = 110
ID_PEDIR_CIUDAD = 120
ID_REGISTRAR = 130
ID_CONFIRMACION = 140
# Captura manual (cuando la API no trae datos)
ID_MAN_NOMBRES = 300
ID_MAN_APELLIDOS = 310
ID_MAN_EDAD = 320
# Corrección de nombres/apellidos (desde el nodo de confirmación)
ID_FIX_NOMBRES = 340
ID_FIX_APELLIDOS = 350
ID_MENOR_EDAD = 950
ID_DESPEDIDA_NO = 960
ID_ERR_REGISTRO = 970
ID_HANDOFF_ASESOR = 990


# Posiciones (x, y) para el editor visual. Columnas:
#   izquierda (40)  = captura manual
#   centro (440)    = camino feliz (de arriba a abajo)
#   derecha (840)   = nodos informativos (vuelven al menú)
#   extrema (1240)  = terminales (fin / handoff)
COORDS = {
    ID_SALUDO:          (440, 40),
    ID_PEDIR_CEDULA:    (440, 180),
    ID_HTTP_CEDULA:     (440, 320),
    ID_EVAL_EDAD:       (440, 460),
    ID_CONFIRMA_DATOS:  (640, 460),
    ID_FIX_NOMBRES:     (640, 600),
    ID_FIX_APELLIDOS:   (640, 740),
    ID_MENU:            (440, 620),
    ID_PREGUNTA_INSC:   (440, 900),
    ID_DEC_CORREO:      (440, 1040),
    ID_PEDIR_CORREO:    (440, 1180),
    ID_PEDIR_CIUDAD:    (440, 1320),
    ID_REGISTRAR:       (440, 1460),
    ID_CONFIRMACION:    (440, 1600),
    # Informativos (derecha)
    ID_INFO_CURSO:      (840, 540),
    ID_REQUISITOS:      (840, 680),
    ID_COSTOS:          (840, 820),
    ID_DURACION:        (840, 960),
    # Captura manual (izquierda)
    ID_MAN_NOMBRES:     (40, 320),
    ID_MAN_APELLIDOS:   (40, 460),
    ID_MAN_EDAD:        (40, 600),
    # Terminales (extrema derecha)
    ID_MENOR_EDAD:      (1240, 460),
    ID_DESPEDIDA_NO:    (1240, 900),
    ID_HANDOFF_ASESOR:  (1240, 1040),
    ID_ERR_REGISTRO:    (1240, 1460),
}


PASOS = [
    {
        'id': ID_SALUDO, 'orden': 10, 'tipo': 'respuesta_texto',
        'codigo': 'saludo_inicial', 'nombre': 'Saludo de bienvenida',
        'es_inicio': True,
        'mensaje': BOT['mensaje_inicial'],
        'siguiente': ID_PEDIR_CEDULA,
    },
    {
        'id': ID_PEDIR_CEDULA, 'orden': 20, 'tipo': 'input_texto',
        'codigo': 'pedir_cedula', 'nombre': 'Pedir cédula',
        'mensaje': 'Por favor, escribe tu *cédula* (10 dígitos):',
        'guardar_en': 'cedula',
        'validacion': r'^[0-9]{10}$',
        'mensaje_error': '⚠️ La cédula debe tener exactamente 10 dígitos numéricos. Inténtalo de nuevo:',
        'siguiente': ID_HTTP_CEDULA,
    },
    {
        'id': ID_HTTP_CEDULA, 'orden': 30, 'tipo': 'llamada_funcion',
        'codigo': 'fn_consulta_cedula', 'nombre': 'Consulta cédula (API SAGEST)',
        'funcion_codigo': 'consultar_cedula_sagest',
        'timeout_seg': 20,
        'body': {'cedula': '{{variables.cedula}}'},
        'extrae_variables': {
            '$origen':           '$.origen',
            '$nombres':          '$.data.nombres',
            '$apellidos':        '$.data.apellidos',
            '$fecha_nacimiento': '$.data.fecha_nacimiento',
            '$edad':             '$.data.edad',
        },
        'siguiente_ok': ID_EVAL_EDAD, 'siguiente_error': ID_MAN_NOMBRES,
    },
    {
        'id': ID_EVAL_EDAD, 'orden': 40, 'tipo': 'decision',
        'codigo': 'eval_edad', 'nombre': '¿Mayor de edad?',
        'condicion': '{{variables.edad}} >= 18',
        'siguiente_si': ID_CONFIRMA_DATOS, 'siguiente_no': ID_MENOR_EDAD,
    },

    {
        'id': ID_CONFIRMA_DATOS, 'orden': 45, 'tipo': 'menu_botones',
        'codigo': 'confirma_datos', 'nombre': 'Confirmar nombres/apellidos',
        'mensaje': (
            'Antes de continuar, confirmemos tus datos:\n\n'
            '👤 *{{variables.nombres}} {{variables.apellidos}}*\n\n'
            '¿Están correctos?'
        ),
        'guardar_en': 'confirma_datos',
        'opciones': [
            {'etiqueta': '✅ Sí, correctos', 'valor': 'si',       'siguiente': ID_MENU},
            {'etiqueta': '✏️ Corregir',      'valor': 'corregir', 'siguiente': ID_FIX_NOMBRES},
        ],
    },
    {
        'id': ID_FIX_NOMBRES, 'orden': 340, 'tipo': 'input_texto',
        'codigo': 'fix_nombres', 'nombre': 'Corregir nombres',
        'mensaje': '👤 Escribe tus *nombres* correctamente (solo el nombre, sin apellidos — ej: Juan Carlos):',
        'guardar_en': 'nombres',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'mensaje_error': '⚠️ Escribe tus nombres (solo letras):',
        'siguiente': ID_FIX_APELLIDOS,
    },
    {
        'id': ID_FIX_APELLIDOS, 'orden': 350, 'tipo': 'input_texto',
        'codigo': 'fix_apellidos', 'nombre': 'Corregir apellidos',
        'mensaje': '👤 Ahora tus *apellidos* (ej: Pérez Gómez):',
        'guardar_en': 'apellidos',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'mensaje_error': '⚠️ Escribe tus apellidos (solo letras):',
        'siguiente': ID_CONFIRMA_DATOS,
    },

    {
        'id': ID_MENU, 'orden': 50, 'tipo': 'menu_botones',
        'codigo': 'menu_principal', 'nombre': 'Menú principal',
        'mensaje': (
            '¡Hola *{{variables.nombres}} {{variables.apellidos}}*! 👋 '
            '(edad: {{variables.edad}} años ✅)\n\n'
            'Cumples con el requisito de edad. ¿Qué deseas hacer?\n\n'
            '1️⃣ Conocer el curso e información\n'
            '2️⃣ Ver requisitos y restricciones\n'
            '3️⃣ Costos y formas de pago\n'
            '4️⃣ Duración y fechas\n'
            '5️⃣ Quiero inscribirme directamente'
        ),
        'guardar_en': 'opcion_menu',
        'opciones': [
            {'etiqueta': '⚓ Conocer el curso',      'valor': 'curso',      'siguiente': ID_INFO_CURSO},
            {'etiqueta': '📋 Requisitos',            'valor': 'requisitos', 'siguiente': ID_REQUISITOS},
            {'etiqueta': '💰 Costos y pagos',        'valor': 'costos',     'siguiente': ID_COSTOS},
            {'etiqueta': '📅 Duración y fechas',     'valor': 'duracion',   'siguiente': ID_DURACION},
            {'etiqueta': '✅ Quiero inscribirme',    'valor': 'inscribir',  'siguiente': ID_PREGUNTA_INSC},
        ],
    },
    {
        'id': ID_INFO_CURSO, 'orden': 60, 'tipo': 'respuesta_texto',
        'codigo': 'info_curso', 'nombre': 'Información del curso',
        'mensaje': (
            '⚓ *FORMACIÓN TÉCNICA EN BUCEO INDUSTRIAL & SUBACUÁTICO*\n\n'
            '🌊 Formación presencial intensiva en Ayangue – Ecuador\n'
            '🛠️ Manejo de herramientas subacuáticas, rescate, seguridad y '
            'trabajos industriales bajo el agua\n'
            '✅ Certificación de formación técnica\n'
            '✅ Prácticas presenciales especializadas\n'
            '✅ Entrenamiento con estándares internacionales\n'
            '🎓 Evento de clausura en UNEMI\n\n'
            '📚 *Temario por niveles:*\n'
            '🔹 A1–A2: Fundamentos, física del buceo, anatomía, buceo autónomo '
            '-30m, primeros auxilios.\n'
            '🔹 A3: Cámaras hiperbáricas, soldadura y corte subacuático, '
            'herramientas, seguridad offshore, buceo -50m.\n\n'
            'Escribe *menú* para volver a las opciones.'
        ),
        'siguiente': ID_MENU,
    },
    {
        'id': ID_REQUISITOS, 'orden': 70, 'tipo': 'respuesta_texto',
        'codigo': 'requisitos', 'nombre': 'Requisitos y restricciones',
        'mensaje': (
            '📋 *REQUISITOS Y RESTRICCIONES*\n\n'
            '✅ Edad mínima: 18 años\n'
            '✅ Apto médico (certificado de salud)\n'
            '✅ Buena condición física\n'
            '✅ Grado bachiller (mínimo)\n'
            '✅ Disposición de tiempo completo (formación presencial intensiva)\n\n'
            '⚠️ *Importante:* formación exclusiva con *cupos limitados*. '
            'Modalidad 100% presencial en Ayangue – Ecuador.\n\n'
            'Escribe *menú* para volver a las opciones.'
        ),
        'siguiente': ID_MENU,
    },
    {
        'id': ID_COSTOS, 'orden': 80, 'tipo': 'respuesta_texto',
        'codigo': 'costos', 'nombre': 'Costos y pagos',
        'mensaje': (
            '💰 *INVERSIÓN TOTAL: $6.000*\n\n'
            '🔹 Inscripción: $500\n'
            '🔹 1ª cuota: $1.500\n'
            '🔹 2 cuotas de: $2.000 c/u\n\n'
            '✅ *Incluye:* manuales y material multimedia, uniforme completo '
            '(mameluco, botas, EPP), instructores y supervisores, equipos '
            '(cámaras hiperbáricas, herramientas hidráulicas, trajes secos, '
            'casco pro) y logística según estándar.\n\n'
            '⚠️ Cupos limitados — formación exclusiva.\n\n'
            'Escribe *menú* para volver a las opciones.'
        ),
        'siguiente': ID_MENU,
    },
    {
        'id': ID_DURACION, 'orden': 90, 'tipo': 'respuesta_texto',
        'codigo': 'duracion', 'nombre': 'Duración y fechas',
        'mensaje': (
            '📅 *DURACIÓN Y FECHAS*\n\n'
            '⏳ Duración: *3 meses* (formación intensiva)\n'
            '📆 Inicio tentativo: *Agosto 2026*\n'
            '📍 Modalidad: *Presencial* en Ayangue – Ecuador\n'
            '🕐 Carga horaria: formación técnica intensiva por niveles (A1, A2, A3)\n\n'
            'Escribe *menú* para volver a las opciones.'
        ),
        'siguiente': ID_MENU,
    },

    {
        'id': ID_PREGUNTA_INSC, 'orden': 100, 'tipo': 'menu_botones',
        'codigo': 'pregunta_inscripcion', 'nombre': '¿Inscribirse?',
        'mensaje': (
            '🎯 *{{variables.nombres}}*, ¿deseas reservar tu cupo e inscribirte '
            'en el curso de Buceo Industrial & Subacuático?\n\n'
            '⚠️ Recuerda: cupos limitados.\n\n'
            '1️⃣ ✅ SÍ, quiero inscribirme\n'
            '2️⃣ ❌ No por ahora\n'
            '3️⃣ Tengo una pregunta (hablar con asesor)'
        ),
        'guardar_en': 'quiere_inscribirse',
        'opciones': [
            {'etiqueta': '✅ Sí, inscribirme',   'valor': 'si',     'siguiente': ID_DEC_CORREO},
            {'etiqueta': '❌ No por ahora',       'valor': 'no',     'siguiente': ID_DESPEDIDA_NO},
            {'etiqueta': '👨‍💼 Hablar con asesor', 'valor': 'asesor', 'siguiente': ID_HANDOFF_ASESOR},
        ],
    },
    {
        'id': ID_DEC_CORREO, 'orden': 105, 'tipo': 'decision',
        'codigo': 'correo_vacio', 'nombre': '¿Falta el correo?',
        'condiciones': [{'izq': '{{variables.correo}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': ID_PEDIR_CORREO, 'siguiente_no': ID_PEDIR_CIUDAD,
    },
    {
        'id': ID_PEDIR_CORREO, 'orden': 110, 'tipo': 'input_texto',
        'codigo': 'pedir_correo', 'nombre': 'Pedir correo',
        'mensaje': 'Perfecto 🙌 Solo necesito un par de datos más.\n\n📧 ¿Cuál es tu *correo electrónico*?',
        'guardar_en': 'correo',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]+$',
        'mensaje_error': '⚠️ Ese correo no parece válido. Escríbelo de nuevo (ejemplo: nombre@correo.com):',
        'siguiente': ID_PEDIR_CIUDAD,
    },
    {
        'id': ID_PEDIR_CIUDAD, 'orden': 120, 'tipo': 'input_texto',
        'codigo': 'pedir_ciudad', 'nombre': 'Pedir ciudad',
        'mensaje': '🏙️ ¿En qué *ciudad* resides?',
        'guardar_en': 'ciudad',
        'validacion': r'^.{2,}$',
        'mensaje_error': '⚠️ Escribe el nombre de tu ciudad:',
        'siguiente': ID_REGISTRAR,
    },
    {
        'id': ID_REGISTRAR, 'orden': 130, 'tipo': 'llamada_funcion',
        'codigo': 'fn_cliente_upsert', 'nombre': 'Guardar Cliente + origen',
        # Función GENÉRICA del CRM (crm.funciones_cliente): get_or_create por
        # cédula, no pisa el origen, registra ciudad y ClienteOrigen. La misma
        # que usan agenda/cotizador. Lee cedula/nombres/apellidos/correo/edad/
        # fecha_nacimiento/ciudad de las variables del flujo.
        'funcion_codigo': 'cliente_upsert',
        'timeout_seg': 5,
        'body': {'canal_origen': 'chatbot'},
        'extrae_variables': {
            '$cliente_id':     '$.cliente_id',
            '$cliente_creado': '$.cliente_creado',
        },
        'siguiente_ok': ID_CONFIRMACION, 'siguiente_error': ID_ERR_REGISTRO,
    },

    {
        'id': ID_MAN_NOMBRES, 'orden': 300, 'tipo': 'input_texto',
        'codigo': 'man_nombres', 'nombre': 'Captura manual: nombres',
        'mensaje': (
            '😕 No pude validar esa cédula automáticamente. No te preocupes, '
            'sigamos con tus datos.\n\n👤 ¿Cuáles son tus *nombres*? '
            '(solo el nombre, sin apellidos — ej: Juan Carlos)'
        ),
        'guardar_en': 'nombres',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'mensaje_error': '⚠️ Escribe tus nombres (solo letras):',
        'siguiente': ID_MAN_APELLIDOS,
    },
    {
        'id': ID_MAN_APELLIDOS, 'orden': 310, 'tipo': 'input_texto',
        'codigo': 'man_apellidos', 'nombre': 'Captura manual: apellidos',
        'mensaje': '👤 Ahora tus *apellidos* (ej: Pérez Gómez):',
        'guardar_en': 'apellidos',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'mensaje_error': '⚠️ Escribe tus apellidos (solo letras):',
        'siguiente': ID_MAN_EDAD,
    },
    {
        'id': ID_MAN_EDAD, 'orden': 320, 'tipo': 'input_texto',
        'codigo': 'man_edad', 'nombre': 'Captura manual: edad',
        'mensaje': '🎂 ¿Cuál es tu *edad*? (solo el número, ej: 25)',
        'guardar_en': 'edad',
        'validacion': r'^\d{1,3}$',
        'mensaje_error': '⚠️ Escribe tu edad en números (ej: 25):',
        'siguiente': ID_EVAL_EDAD,
    },

    {
        'id': ID_CONFIRMACION, 'orden': 140, 'tipo': 'fin_conversacion',
        'codigo': 'confirmacion', 'nombre': 'Pre-inscripción OK (fin)',
        'notificar_asesor': True,
        'mensaje_asesor': (
            'Nueva pre-inscripción al curso de Buceo Industrial. Contactar al '
            'cliente para coordinar el pago de la inscripción ($500) y el apto médico.'
        ),
        'mensaje': (
            '✅ ¡Listo, *{{variables.nombres}} {{variables.apellidos}}*! Tu '
            'pre-inscripción quedó registrada. 🎉\n\n'
            '📋 *Resumen:*\n'
            '👤 {{variables.nombres}} {{variables.apellidos}}\n'
            '🆔 {{variables.cedula}}\n'
            '📧 {{variables.correo}}\n'
            '🏙️ {{variables.ciudad}}\n'
            '⚓ Curso: Buceo Industrial & Subacuático\n\n'
            '💰 *Inversión total del curso: $6.000*\n'
            '🔹 Inscripción: $500\n'
            '🔹 1ª cuota: $1.500\n'
            '🔹 2 cuotas de: $2.000 c/u\n\n'
            '📞 *En un momento, uno de nuestros asesores se pondrá en contacto '
            'contigo* para coordinar el pago de la inscripción ($500), el apto '
            'médico y los siguientes pasos.\n\n'
            '¡Gracias por tu interés y bienvenido a la élite del buceo! 🌊'
        ),
    },

    {
        'id': ID_MENOR_EDAD, 'orden': 950, 'tipo': 'fin_conversacion',
        'codigo': 'menor_edad', 'nombre': 'Menor de edad',
        'mensaje': (
            'Hola {{variables.nombres}}, gracias por tu interés. 🙏\n\n'
            'Lamentablemente, uno de los requisitos del curso es tener '
            '*mínimo 18 años de edad*, y según nuestros registros aún no '
            'cumples con ese requisito.\n\n'
            'Te invitamos a contactarnos más adelante. ¡Te esperamos! ⚓'
        ),
    },
    {
        'id': ID_DESPEDIDA_NO, 'orden': 960, 'tipo': 'fin_conversacion',
        'codigo': 'despedida_no', 'nombre': 'No por ahora',
        'mensaje': (
            '¡Entendido, {{variables.nombres}}! 😊 Quedamos atentos cuando '
            'quieras inscribirte.\n\nRecuerda que los *cupos son limitados*. '
            'Cuando estés listo, solo escríbenos de nuevo. ¡Te esperamos en '
            'EPUNEMI! ⚓'
        ),
    },
    {
        'id': ID_ERR_REGISTRO, 'orden': 970, 'tipo': 'handoff_humano',
        'codigo': 'err_registro', 'nombre': 'Error al registrar + asesor',
        'mensaje': (
            'Gracias {{variables.nombres}}. Registramos tu interés, pero '
            'tuvimos un detalle técnico al guardar la inscripción '
            'automáticamente.\n\n📞 No te preocupes: un asesor se pondrá en '
            'contacto contigo en breve para completar tu inscripción manualmente.'
        ),
    },
    {
        'id': ID_HANDOFF_ASESOR, 'orden': 990, 'tipo': 'handoff_humano',
        'codigo': 'handoff_asesor', 'nombre': 'Transferir a asesor',
        'mensaje': (
            '👨‍💼 Te conecto con un asesor de *EPUNEMI*. En breve te responderán '
            'por este mismo chat para resolver todas tus dudas.\n\n'
            'Gracias por tu paciencia. ⚓'
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
    'handoff_humano':   'handoff',
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
    if low in ('null', 'none'):
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
    help = 'Crea el flujo de inscripción al curso de Buceo Industrial de EPUNEMI.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el depto previo y lo recrea.')
        parser.add_argument('--delete', action='store_true',
                            help='Solo borra el depto y sale.')
        parser.add_argument('--sesion', type=int, default=None,
                            help='ID de SesionWhatsApp para asociar el flujo.')
        parser.add_argument('--base-url', type=str, default=BASE_URL_DEFAULT,
                            help=f'Base URL REST (default: {BASE_URL_DEFAULT}).')

    def _eliminar_depto(self):
        from crm.models import EstadoFlujoChatbot
        viejos = DepartamentoChatBot.objects.filter(nombre=NOMBRE_DEPTO)
        n_deptos = viejos.count()
        n_nodos = OpcionDepartamentoChatBot.objects.filter(departamento__in=viejos).count()
        n_conn = ConexionNodoChatbot.objects.filter(nodo_origen__departamento__in=viejos).count()

        EstadoFlujoChatbot.objects.filter(departamento__in=viejos).delete()
        viejos.delete()

        huerfanos = EstadoFlujoChatbot.objects.filter(departamento__isnull=True)
        if huerfanos.exists():
            huerfanos.delete()

        return {'deptos': n_deptos, 'nodos': n_nodos, 'conexiones': n_conn}

    def _config_para(self, paso):
        t = paso['tipo']
        if t in ('respuesta_texto', 'fin_conversacion', 'handoff_humano'):
            return {'mensaje': paso.get('mensaje', '')}
        if t == 'input_texto':
            return {'pregunta': paso.get('mensaje', '')}
        if t == 'menu_botones':
            return {
                'mensaje': paso.get('mensaje', ''),
                'opciones': [
                    {'etiqueta': o['etiqueta'], 'valor': o['valor'], 'salida': o['valor']}
                    for o in paso.get('opciones', [])
                ],
            }
        if t == 'decision':
            if paso.get('condiciones'):
                return {'condiciones': paso['condiciones'],
                        'operador': paso.get('operador', 'and')}
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
                'body': paso.get('body') or {},
                'extraer': _normalizar_extraer(paso.get('extrae_variables')),
                'timeout_seg': paso.get('timeout_seg', 30),
            }
            if paso.get('path_inscripcion'):
                cfg['path_inscripcion'] = paso['path_inscripcion']
            if paso.get('envia_correo'):
                cfg['envia_correo'] = True
            return cfg
        return {}

    def _crear_nodo(self, depto, eps, paso):
        t = paso['tipo']
        validacion_tipo = 'none'
        validacion_expr = ''
        if paso.get('validacion'):
            validacion_tipo = 'regex'
            validacion_expr = paso['validacion']

        endpoint_obj = eps.get('rest') if t == 'llamada_http' else None

        pos_x, pos_y = COORDS.get(paso['id'], (0, 0))

        cfg = self._config_para(paso)
        # Flag por-nodo: notificar a los asesores disponibles de la sesión
        # (email + campanita), independiente del handoff. Sirve en cualquier tipo.
        if paso.get('notificar_asesor'):
            cfg['notificar_asesor'] = True
            cfg['mensaje_asesor'] = paso.get('mensaje_asesor', '') or ''

        return OpcionDepartamentoChatBot.objects.create(
            departamento=depto,
            nombre=paso.get('nombre') or paso.get('codigo', ''),
            tipo_nodo=TIPO_MAP[t],
            config=cfg,
            es_inicio=bool(paso.get('es_inicio')),
            endpoint=endpoint_obj,
            variable_destino=paso.get('guardar_en', '') or '',
            validacion_tipo=validacion_tipo,
            validacion_expresion=validacion_expr,
            mensaje_error=paso.get('mensaje_error', '') or '',
            reintentos_max=3,
            orden=paso.get('orden', 0),
            posicion_x=pos_x,
            posicion_y=pos_y,
        )

    def _crear_conexiones(self, mapa, paso):
        origen = mapa[paso['id']]
        t = paso['tipo']

        if t == 'menu_botones':
            for i, o in enumerate(paso.get('opciones', []), start=1):
                destino_id = o.get('siguiente')
                if destino_id and destino_id in mapa:
                    ConexionNodoChatbot.objects.create(
                        nodo_origen=origen, nodo_destino=mapa[destino_id],
                        etiqueta=o['valor'], orden=i,
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

        # handoff_humano y fin_conversacion son terminales: sin salida.
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
                    f'No había depto "{NOMBRE_DEPTO}" para borrar.'
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
                'descripcion': 'API REST pública SAGEST EPUNEMI (consulta de cédula en cascada: persona/unemi/ister).',
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
                'timeout_seg': 30,
                'descripcion': 'Endpoint base SAGEST apimobile v1 (EPUNEMI) — consultacedulapersona.',
            },
        )
        if ep.credencial_id != credencial.id:
            ep.credencial = credencial
            ep.save()

        eps = {'rest': ep}

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
            f'   Endpoint REST : {ep.nombre} -> {ep.base_url}\n'
            f'   Credencial    : {credencial.nombre} ({credencial.get_tipo_display()})\n'
            f'   Termina notificando a un asesor (handoff → auto_asignar_agente).\n'
        ))
