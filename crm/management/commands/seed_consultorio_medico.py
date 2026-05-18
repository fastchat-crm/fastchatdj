"""Seed del flujo determinístico "Consultorio Médico — Agenda".

Crea (o recrea con --reset) un DepartamentoChatBot vinculado a un GrupoAgenda
existente (sembrado por `scripts/seed_agenda_consultorio_medico.py`). El flujo:

  1. Lee config del grupo (moneda, recordatorio_h, zona_horaria) vía
     función interna `agenda_init` (no HTTP).
  2. Pide cédula → HTTP al endpoint MGA (reusa `Cotizador Vida Buena REST v1`)
     `?action=cliente&cedula=` para autocompletar nombres/apellidos/email/edad.
  3. Si el lookup falla o trae campos vacíos → pide solo lo faltante.
  4. Elige servicio → recurso (con atajo "cualquiera") → fecha → slot.
  5. Pide motivo (opcional, "-"/"saltar" para omitir).
  6. Muestra resumen (precio solo si > 0) → confirma.
  7. Función `agenda_registrar_turno` crea el Turno (origen=chatbot,
     estado=confirmed).

Uso:
    python manage.py seed_consultorio_medico --grupo 1
    python manage.py seed_consultorio_medico --grupo 1 --reset
    python manage.py seed_consultorio_medico --grupo-nombre "Consultorio Medico"
    python manage.py seed_consultorio_medico --delete
    python manage.py seed_consultorio_medico --grupo 1 --sesion 5
    python manage.py seed_consultorio_medico --base-url https://otro.dominio/aria-api/v1/

Pre-requisito: ya existe el GrupoAgenda (correr antes
`python scripts/seed_agenda_consultorio_medico.py`).
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from agenda.models import GrupoAgenda
from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'Consultorio Médico — Agenda'
GRUPO_NOMBRE_DEFAULT = 'Consultorio Medico'

CLIENTE_ENDPOINT_NOMBRE = 'Cotizador Vida Buena REST v1'
CLIENTE_BASE_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/cotimedica-api/v1/'
CLIENTE_CREDENCIAL_NOMBRE = 'Vida Buena REST - AllowAny'


BOT = {
    'nombre': NOMBRE_DEPTO,
    'mensaje_inicial': (
        '¡Hola! 👋 Soy el asistente del consultorio. '
        'Voy a ayudarte a reservar tu turno. 🩺'
    ),
    'color': '#0ea5e9',
    'palabras_clave': (
        'turno\ncita\nreservar\nagendar\nagenda\nconsulta\nmedico\nmédico\n'
        'doctor\nconsultorio'
    ),
    'reset_triggers': [
        'reiniciar', 'cancelar', 'volver al inicio', 'empezar de nuevo',
        'otra fecha', 'cambiar fecha', 'otro turno', 'otro horario',
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
        'siguiente': 15,
    },

    # ── 15 — Init agenda (lee depto.grupo_agenda) ───────────────
    {
        'id': 15, 'orden': 15, 'tipo': 'llamada_funcion',
        'codigo': 'fn_agenda_init', 'nombre': 'Init agenda (grupo + tz + recordatorio)',
        'funcion_codigo': 'agenda_init',
        'metodo': 'POST', 'timeout_seg': 5, 'body': {},
        'extrae_variables': {
            '$grupo_agenda_id': '$.grupo_agenda_id',
            '$grupo_nombre':    '$.grupo_nombre',
            '$moneda':          '$.moneda',
            '$recordatorio_h':  '$.recordatorio_h',
            '$zona_horaria':    '$.zona_horaria',
        },
        'siguiente_ok': 20, 'siguiente_error': 900,
    },

    # ── 20/30/40 — Cédula + lookup MGA ──────────────────────────
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
        'codigo': 'http_cliente', 'nombre': 'GET ?action=cliente (Vida Buena)',
        'metodo': 'GET', 'path': '',
        'query': {'action': 'cliente', 'cedula': '{{variables.cedula}}'},
        'timeout_seg': 15,
        'extrae_variables': {
            '$encontrado_cli': '$.data.encontrado',
            '$nombres':        '$.data.nombres',
            '$apellidos':      '$.data.apellidos',
            '$email':          '$.data.email',
            '$driver_age':     '$.data.edad',
        },
        'siguiente_ok': 40, 'siguiente_error': 50,
    },
    {
        'id': 40, 'orden': 40, 'tipo': 'decision',
        'codigo': 'cliente_encontrado', 'nombre': '¿Cliente encontrado?',
        'condicion': '{{variables.encontrado_cli}} == true',
        'siguiente_si': 60, 'siguiente_no': 50,
    },

    # ── 50 — Cliente no encontrado o error API → pedimos todo ───
    {
        'id': 50, 'orden': 50, 'tipo': 'respuesta_texto',
        'codigo': 'cliente_no_encontrado', 'nombre': 'Cliente no encontrado',
        'mensaje': 'No te encontré en nuestra base. Te pido unos datos rápidos. 📝',
        'siguiente': 51,
    },
    {
        'id': 51, 'orden': 51, 'tipo': 'input_texto',
        'codigo': 'pedir_nombres', 'nombre': 'Pedir nombres',
        'mensaje': '¿Cuál es tu *nombre*?',
        'guardar_en': 'nombres',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'siguiente': 52,
    },
    {
        'id': 52, 'orden': 52, 'tipo': 'input_texto',
        'codigo': 'pedir_apellidos', 'nombre': 'Pedir apellidos',
        'mensaje': '¿Y tus *apellidos*?',
        'guardar_en': 'apellidos',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'siguiente': 53,
    },
    {
        'id': 53, 'orden': 53, 'tipo': 'input_texto',
        'codigo': 'pedir_email', 'nombre': 'Pedir email',
        'mensaje': '📧 ¿A qué *correo* te enviamos la confirmación?',
        'guardar_en': 'email',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 54,
    },
    {
        'id': 54, 'orden': 54, 'tipo': 'input_texto',
        'codigo': 'pedir_edad', 'nombre': 'Pedir edad',
        'mensaje': '🎂 ¿Cuál es tu *edad*?',
        'guardar_en': 'driver_age',
        'validacion_tipo': 'numero',
        'siguiente': 55,
    },
    {
        'id': 55, 'orden': 55, 'tipo': 'input_texto',
        'codigo': 'pedir_fecha_nac', 'nombre': 'Pedir fecha de nacimiento',
        'mensaje': '🗓️ ¿Cuál es tu *fecha de nacimiento*? (formato DD/MM/AAAA)',
        'guardar_en': 'fecha_nacimiento',
        'validacion': r'^\d{2}/\d{2}/\d{4}$',
        'siguiente': 100,
    },

    # ── 60 — Cliente encontrado: mostrar + completar vacíos ─────
    {
        'id': 60, 'orden': 60, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_paciente', 'nombre': 'Mostrar datos del paciente',
        'mensaje': (
            '✅ Encontré tus datos:\n'
            '• Nombre: *{{variables.nombres}} {{variables.apellidos}}*'
        ),
        'siguiente': 70,
    },
    {
        'id': 70, 'orden': 70, 'tipo': 'decision',
        'codigo': 'email_vacio', 'nombre': '¿Email vacío?',
        'condiciones': [{'izq': '{{variables.email}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 71, 'siguiente_no': 72,
    },
    {
        'id': 71, 'orden': 71, 'tipo': 'input_texto',
        'codigo': 'pedir_email_faltante', 'nombre': 'Pedir email faltante',
        'mensaje': '📧 No tenemos tu correo. Escribilo:',
        'guardar_en': 'email',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 80,
    },
    {
        'id': 72, 'orden': 72, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_email', 'nombre': 'Mostrar correo del paciente',
        'mensaje': '📧 Correo: *{{variables.email}}*',
        'siguiente': 80,
    },
    {
        'id': 80, 'orden': 80, 'tipo': 'decision',
        'codigo': 'edad_vacia', 'nombre': '¿Edad vacía?',
        'condiciones': [{'izq': '{{variables.driver_age}}', 'op': 'vacio', 'der': ''}],
        'operador': 'and',
        'siguiente_si': 81, 'siguiente_no': 82,
    },
    {
        'id': 81, 'orden': 81, 'tipo': 'input_texto',
        'codigo': 'pedir_edad_faltante', 'nombre': 'Pedir edad faltante',
        'mensaje': '🎂 No tenemos tu edad. ¿Cuántos años tenés?',
        'guardar_en': 'driver_age',
        'validacion_tipo': 'numero',
        'siguiente': 90,
    },
    {
        'id': 82, 'orden': 82, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_edad', 'nombre': 'Mostrar edad del paciente',
        'mensaje': '🎂 Edad: *{{variables.driver_age}}*',
        'siguiente': 90,
    },

    # ── 90/91/92/93 — Menú "ver mis citas" o "agendar nuevo" ────
    {
        'id': 90, 'orden': 90, 'tipo': 'menu_botones',
        'codigo': 'menu_accion', 'nombre': '¿Ver citas o agendar?',
        'mensaje': '¿Qué querés hacer?',
        'guardar_en': 'accion_principal',
        'opciones': [
            {'etiqueta': '📅 Ver mis citas', 'valor': 'ver',   'siguiente': 91},
            {'etiqueta': '🆕 Agendar turno', 'valor': 'nuevo', 'siguiente': 100},
        ],
    },
    {
        'id': 91, 'orden': 91, 'tipo': 'llamada_funcion',
        'codigo': 'fn_listar_mis_citas', 'nombre': 'Listar mis citas',
        'funcion_codigo': 'agenda_listar_mis_citas',
        'metodo': 'POST', 'timeout_seg': 10, 'body': {'limite': 5},
        'extrae_variables': {
            '$citas_text':   '$.citas_text',
            '$total_citas':  '$.total_citas',
            '$tiene_citas':  '$.tiene_citas',
        },
        'siguiente_ok': 92, 'siguiente_error': 900,
    },
    {
        'id': 92, 'orden': 92, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_mis_citas', 'nombre': 'Mostrar mis citas',
        'mensaje': '{{variables.citas_text}}',
        'siguiente': 93,
    },
    {
        'id': 93, 'orden': 93, 'tipo': 'menu_botones',
        'codigo': 'agendar_otra', 'nombre': '¿Agendar nueva?',
        'mensaje': '¿Querés *agendar* una cita nueva?',
        'guardar_en': 'agendar_nueva',
        'opciones': [
            {'etiqueta': '✅ Sí, agendar', 'valor': 'si', 'siguiente': 100},
            {'etiqueta': '❌ No, gracias', 'valor': 'no', 'siguiente': 999},
        ],
    },

    # ── 100/110 — Servicios ─────────────────────────────────────
    {
        'id': 100, 'orden': 100, 'tipo': 'llamada_funcion',
        'codigo': 'fn_listar_servicios', 'nombre': 'Listar servicios del grupo',
        'funcion_codigo': 'agenda_listar_servicios',
        'metodo': 'POST', 'timeout_seg': 10, 'body': {},
        'extrae_variables': {'$servicios': '$.servicios'},
        'siguiente_ok': 110, 'siguiente_error': 900,
    },
    {
        'id': 110, 'orden': 110, 'tipo': 'menu_botones',
        'codigo': 'elegir_servicio', 'nombre': 'Elegir servicio',
        'mensaje': '🩺 ¿Qué *servicio* querés agendar?',
        'guardar_en': 'servicio_id',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.servicios',
            'campo_id': 'id',
            'campo_etiqueta': 'etiqueta',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 120,
    },

    # ── 120 — Atajo "cualquier médico" ──────────────────────────
    {
        'id': 120, 'orden': 120, 'tipo': 'menu_botones',
        'codigo': 'pref_medico_default', 'nombre': 'Preferencia médico (atajo)',
        'guardar_en': 'recurso_id',
        'opciones': [],
        'opcion_default': {
            'valor':         '0',
            'etiqueta':      'Cualquiera',
            'pregunta':      '👨‍⚕️ ¿Tenés preferencia de médico?',
            'etiqueta_si':   '✅ Cualquier médico',
            'etiqueta_otra': '👨‍⚕️ Elegir médico',
            'salida_si':     'si',
            'salida_otra':   'otra',
        },
        'siguiente_si':   138,
        'siguiente_otra': 132,
    },
    {
        'id': 132, 'orden': 132, 'tipo': 'llamada_funcion',
        'codigo': 'fn_listar_recursos', 'nombre': 'Listar recursos del servicio',
        'funcion_codigo': 'agenda_listar_recursos',
        'metodo': 'POST', 'timeout_seg': 10, 'body': {},
        'extrae_variables': {'$recursos': '$.recursos'},
        'siguiente_ok': 134, 'siguiente_error': 900,
    },
    {
        'id': 134, 'orden': 134, 'tipo': 'menu_botones',
        'codigo': 'elegir_recurso', 'nombre': 'Elegir médico',
        'mensaje': '👨‍⚕️ Elegí el *médico*:',
        'guardar_en': 'recurso_id',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.recursos',
            'campo_id': 'id',
            'campo_etiqueta': 'etiqueta',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 138,
    },

    # ── 138/140/150 — Día (7 próximos) + disponibilidad ─────────
    {
        'id': 138, 'orden': 138, 'tipo': 'llamada_funcion',
        'codigo': 'fn_listar_dias', 'nombre': 'Listar próximos 7 días',
        'funcion_codigo': 'agenda_listar_dias',
        'metodo': 'POST', 'timeout_seg': 5, 'body': {},
        'extrae_variables': {'$dias': '$.dias'},
        'siguiente_ok': 140, 'siguiente_error': 900,
    },
    {
        'id': 140, 'orden': 140, 'tipo': 'menu_botones',
        'codigo': 'elegir_dia', 'nombre': 'Elegir día (próximos 7)',
        'mensaje': '📅 ¿Para qué *día* querés el turno?',
        'guardar_en': 'fecha',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.dias',
            'campo_id': 'id',
            'campo_etiqueta': 'etiqueta',
            'salida': '',
            'limite': 7,
        },
        'siguiente': 150,
    },
    {
        'id': 150, 'orden': 150, 'tipo': 'llamada_funcion',
        'codigo': 'fn_disponibilidad', 'nombre': 'Disponibilidad de turnos',
        'funcion_codigo': 'agenda_disponibilidad',
        'metodo': 'POST', 'timeout_seg': 15, 'body': {},
        'extrae_variables': {'$turnos_disponibles': '$.turnos_disponibles'},
        'siguiente_ok': 160, 'siguiente_error': 900,
    },
    {
        'id': 160, 'orden': 160, 'tipo': 'decision',
        'codigo': 'hay_turnos', 'nombre': '¿Hay turnos disponibles?',
        'condiciones': [
            {'izq': '{{variables.turnos_disponibles}}', 'op': 'vacio', 'der': ''},
        ],
        'operador': 'and',
        'siguiente_si': 170, 'siguiente_no': 180,
    },
    {
        'id': 170, 'orden': 170, 'tipo': 'respuesta_texto',
        'codigo': 'sin_cupos', 'nombre': 'Sin cupos esa fecha',
        'mensaje': (
            '😕 No hay cupos disponibles para *{{variables.fecha}}*. '
            'Probá con otro día.'
        ),
        'siguiente': 138,
    },
    {
        'id': 180, 'orden': 180, 'tipo': 'menu_botones',
        'codigo': 'elegir_slot', 'nombre': 'Elegir horario',
        'mensaje': '⏰ Estos son los horarios disponibles. Elegí uno:',
        'guardar_en': 'slot_seleccionado',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.turnos_disponibles',
            'campo_id': 'id',
            'campo_etiqueta': 'etiqueta',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 190,
    },

    # ── 190 — Motivo (opcional) ─────────────────────────────────
    {
        'id': 190, 'orden': 190, 'tipo': 'input_texto',
        'codigo': 'pedir_motivo', 'nombre': 'Motivo de consulta (opcional)',
        'mensaje': (
            '📝 Contame brevemente el *motivo* de tu consulta '
            '(o escribí "-" para saltar):'
        ),
        'guardar_en': 'motivo',
        'validacion': r'^.{1,200}$',
        'siguiente': 195,
    },
    {
        'id': 195, 'orden': 195, 'tipo': 'llamada_funcion',
        'codigo': 'fn_armar_resumen', 'nombre': 'Armar resumen pre-confirmación',
        'funcion_codigo': 'agenda_armar_resumen',
        'metodo': 'POST', 'timeout_seg': 5, 'body': {},
        'extrae_variables': {
            '$resumen_texto':    '$.resumen_texto',
            '$turno_inicio_iso': '$.turno_inicio_iso',
            '$turno_recurso_id': '$.turno_recurso_id',
            '$motivo_limpio':    '$.motivo_limpio',
        },
        'siguiente_ok': 197, 'siguiente_error': 900,
    },
    {
        'id': 197, 'orden': 197, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_resumen', 'nombre': 'Mostrar resumen',
        'mensaje': '{{variables.resumen_texto}}',
        'siguiente': 200,
    },
    {
        'id': 200, 'orden': 200, 'tipo': 'menu_botones',
        'codigo': 'confirmar_turno', 'nombre': '¿Confirmar turno?',
        'mensaje': '¿Confirmo el turno?',
        'guardar_en': 'confirma_turno',
        'opciones': [
            {'etiqueta': '✅ Confirmar',     'valor': 'si',     'siguiente': 207},
            {'etiqueta': '✏️ Cambiar fecha', 'valor': 'cambiar', 'siguiente': 138},
            {'etiqueta': '❌ Cancelar',      'valor': 'cancelar', 'siguiente': 999},
        ],
    },

    # ── 207 — Persistir Cliente local (cédula UK) ──────────────
    {
        'id': 207, 'orden': 207, 'tipo': 'llamada_funcion',
        'codigo': 'fn_cliente_upsert', 'nombre': 'Guardar Cliente + origen',
        'funcion_codigo': 'cliente_upsert',
        'metodo': 'POST', 'timeout_seg': 5,
        'body': {'canal_origen': 'agenda'},
        'extrae_variables': {
            '$cliente_id':     '$.cliente_id',
            '$cliente_creado': '$.cliente_creado',
        },
        'siguiente_ok': 210, 'siguiente_error': 210,
    },

    # ── 210 — Registrar turno ───────────────────────────────────
    {
        'id': 210, 'orden': 210, 'tipo': 'llamada_funcion',
        'codigo': 'fn_registrar_turno', 'nombre': 'Registrar turno en agenda',
        'funcion_codigo': 'agenda_registrar_turno',
        'metodo': 'POST', 'timeout_seg': 15, 'body': {},
        'extrae_variables': {
            '$turno_id':         '$.turno_id',
            '$turno_fecha_fmt':  '$.turno_fecha_fmt',
            '$medico_nombre':    '$.medico_nombre',
            '$servicio_nombre':  '$.servicio_nombre',
        },
        'siguiente_ok': 220, 'siguiente_error': 230,
    },
    {
        'id': 220, 'orden': 220, 'tipo': 'respuesta_texto',
        'codigo': 'turno_confirmado', 'nombre': 'Turno confirmado',
        'mensaje': (
            '✅ ¡Listo! Tu turno quedó *confirmado*:\n\n'
            '• {{variables.servicio_nombre}}\n'
            '• Con: *{{variables.medico_nombre}}*\n'
            '• Fecha: *{{variables.turno_fecha_fmt}}*\n\n'
            'Te enviaremos un recordatorio *{{variables.recordatorio_h}}h* '
            'antes. ¡Te esperamos! 🩺'
        ),
        'siguiente': 998,
    },
    {
        'id': 230, 'orden': 230, 'tipo': 'respuesta_texto',
        'codigo': 'turno_error', 'nombre': 'Error al registrar turno',
        'mensaje': (
            '⚠️ No pudimos reservar el turno (puede que el horario ya '
            'esté tomado). Probá con otro horario.'
        ),
        'siguiente': 138,
    },

    # ── Salidas terminales ──────────────────────────────────────
    {
        'id': 900, 'orden': 900, 'tipo': 'respuesta_texto',
        'codigo': 'error_api', 'nombre': 'Error genérico',
        'mensaje': '⚠️ Hubo un problema procesando tu solicitud. Intentá más tarde.',
        'siguiente': 999,
    },
    {
        'id': 998, 'orden': 998, 'tipo': 'asignar_variable',
        'codigo': 'reset_variables', 'nombre': 'Reset variables',
        'asigna': {
            'cedula': '', 'nombres': '', 'apellidos': '', 'email': '',
            'driver_age': '', 'fecha_nacimiento': '', 'encontrado_cli': '',
            'accion_principal': '', 'agendar_nueva': '',
            'citas_text': '', 'total_citas': '', 'tiene_citas': '',
            'servicio_id': '', 'recurso_id': '', 'fecha': '', 'dias': '',
            'slot_seleccionado': '', 'motivo': '', 'motivo_limpio': '',
            'turno_inicio_iso': '', 'turno_recurso_id': '',
            'resumen_texto': '', 'turno_id': '',
            'confirma_turno': '',
        },
        'siguiente': 999,
    },
    {
        'id': 999, 'orden': 999, 'tipo': 'fin_conversacion',
        'codigo': 'despedida', 'nombre': 'Fin',
        'mensaje': '¡Hasta pronto! 👋 Cuando quieras reservar otro turno, acá estaré.',
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
    help = 'Crea el flujo "Consultorio Médico — Agenda" (chatbot determinístico).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el depto previo y lo recrea.')
        parser.add_argument('--delete', action='store_true',
                            help='Solo borra el depto y sale.')
        parser.add_argument('--sesion', type=int, default=None,
                            help='ID de SesionWhatsApp para asociar el flujo.')
        parser.add_argument('--grupo', type=int, default=None,
                            help='ID del GrupoAgenda a vincular.')
        parser.add_argument('--grupo-nombre', type=str, default=GRUPO_NOMBRE_DEFAULT,
                            help=f'Nombre del GrupoAgenda si no se pasa --grupo (default: "{GRUPO_NOMBRE_DEFAULT}").')
        parser.add_argument('--base-url', type=str, default=CLIENTE_BASE_URL_DEFAULT,
                            help=f'Base URL del endpoint MGA /cliente/ (default: {CLIENTE_BASE_URL_DEFAULT}).')

    def _resolver_grupo(self, opts):
        if opts.get('grupo'):
            try:
                return GrupoAgenda.objects.get(id=opts['grupo'], status=True)
            except GrupoAgenda.DoesNotExist:
                raise CommandError(f'No existe GrupoAgenda activo id={opts["grupo"]}')
        nombre = opts.get('grupo_nombre') or GRUPO_NOMBRE_DEFAULT
        grupo = GrupoAgenda.objects.filter(nombre__iexact=nombre, status=True).first()
        if not grupo:
            raise CommandError(
                f'No existe GrupoAgenda con nombre "{nombre}". '
                f'Ejecutá primero: python scripts/seed_agenda_consultorio_medico.py'
            )
        return grupo

    def _eliminar_depto(self):
        from crm.models import EstadoFlujoChatbot
        viejos = DepartamentoChatBot.objects.filter(nombre=NOMBRE_DEPTO)
        n_deptos = viejos.count()
        n_nodos = OpcionDepartamentoChatBot.objects.filter(departamento__in=viejos).count()
        n_conn = ConexionNodoChatbot.objects.filter(nodo_origen__departamento__in=viejos).count()
        EstadoFlujoChatbot.objects.filter(departamento__in=viejos).delete()
        viejos.delete()
        huerfanos = EstadoFlujoChatbot.objects.filter(departamento__isnull=True)
        n_huerf = huerfanos.count()
        if n_huerf:
            huerfanos.delete()
        return {'deptos': n_deptos, 'nodos': n_nodos, 'conexiones': n_conn,
                'huerfanos': n_huerf}

    def _config_para(self, paso):
        t = paso['tipo']
        if t in ('respuesta_texto', 'fin_conversacion'):
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
            return {
                'metodo': paso.get('metodo', 'GET'),
                'path': paso.get('path', ''),
                'query': paso.get('query') or {},
                'headers': paso.get('headers') or {},
                'body': paso.get('body') or {},
                'extraer': _normalizar_extraer(paso.get('extrae_variables')),
                'timeout_seg': paso.get('timeout_seg', 15),
            }
        if t == 'llamada_funcion':
            return {
                'funcion_codigo': paso.get('funcion_codigo', ''),
                'metodo': paso.get('metodo', 'POST'),
                'body': paso.get('body') or {},
                'extraer': _normalizar_extraer(paso.get('extrae_variables')),
                'timeout_seg': paso.get('timeout_seg', 30),
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
            endpoint_obj = eps.get(paso.get('endpoint_key') or 'cliente_mga')
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
                    f'No había depto "{NOMBRE_DEPTO}" para borrar.'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'[DELETE OK] "{NOMBRE_DEPTO}" eliminado. '
                    f'Nodos: {res["nodos"]} | Conexiones: {res["conexiones"]}'
                ))
            return

        grupo = self._resolver_grupo(opts)

        if opts['reset']:
            res = self._eliminar_depto()
            self.stdout.write(self.style.WARNING(
                f'Reset: borrado depto "{NOMBRE_DEPTO}" '
                f'({res["nodos"]} nodos, {res["conexiones"]} conexiones).'
            ))

        depto, creado = DepartamentoChatBot.objects.get_or_create(
            nombre=NOMBRE_DEPTO,
            defaults={
                'color': BOT['color'],
                'mensaje_saludo': BOT['mensaje_inicial'],
                'palabras_clave': BOT['palabras_clave'],
                'es_default': False,
                'activo_tradicional': True,
                'reset_triggers': BOT['reset_triggers'],
                'mensaje_reset': BOT['mensaje_reset'],
                'grupo_agenda': grupo,
            },
        )
        if not creado:
            self.stdout.write(self.style.WARNING(
                'El depto ya existía. Usá --reset para recrearlo.'
            ))
            return

        if depto.grupo_agenda_id != grupo.id:
            depto.grupo_agenda = grupo
            depto.save(update_fields=['grupo_agenda'])

        cliente_credencial, _ = CredencialApiChatbot.objects.get_or_create(
            nombre=CLIENTE_CREDENCIAL_NOMBRE,
            tipo='none',
            status=True,
            defaults={
                'secretos': {},
                'descripcion': 'API REST pública MGA (CSRF-exempt). Reusada por consultorio.',
            },
        )
        cliente_ep, _ = EndpointApiChatbot.objects.get_or_create(
            nombre=CLIENTE_ENDPOINT_NOMBRE,
            defaults={
                'base_url': opts['base_url'].rstrip('/'),
                'status': True,
                'credencial': cliente_credencial,
                'headers_default': {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                'timeout_seg': 60,
                'descripcion': 'Endpoint REST MGA para lookup de cliente por cédula.',
            },
        )
        if cliente_ep.credencial_id != cliente_credencial.id:
            cliente_ep.credencial = cliente_credencial
            cliente_ep.save()

        eps = {'cliente_mga': cliente_ep}

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
        total_conns = ConexionNodoChatbot.objects.filter(nodo_origen__departamento=depto).count()
        self.stdout.write(self.style.SUCCESS(
            f'\n[OK] Flujo creado: "{depto.nombre}"\n'
            f'   Grupo agenda      : #{grupo.id} "{grupo.nombre}" '
            f'({grupo.moneda} · {grupo.recordatorio_horas_antes}h · {grupo.zona_horaria})\n'
            f'   Nodos             : {total_nodos}\n'
            f'   Conexiones        : {total_conns}\n'
            f'   Endpoint lookup   : {cliente_ep.nombre} -> {cliente_ep.base_url}\n'
            f'   Funciones agenda  : agenda_init, agenda_listar_servicios, '
            f'agenda_listar_recursos, agenda_listar_dias, agenda_disponibilidad, '
            f'agenda_armar_resumen, agenda_registrar_turno\n'
        ))
