"""
Seed del cotizador ARIA v2 (API REST stateless).

Reemplaza la versión anterior basada en /aria/ con `action=paso` (stateful por
sesión Django). La API v2 vive en /aria-api/v1/* y es:
  - REST stateless: cada llamada lleva todos los datos.
  - Pública (AllowAny + CSRF-exempt).
  - Solo soporta cotización CON PLACA.

Flujo del bot (resumido):
  /info/ → placa → /vehiculo/?placa= → confirmar →
  cédula → /cliente/?cedula= → (si no encontrado: pedir nombres/apellidos/email/teléfono) →
  catálogos (tipos-vehiculo, provincias, [cantones si requiere], colores) →
  pedir valor + accesorios → POST /cotizar/ →
  /planes/?cotpk= → elegir → /plan/?detalle_id= → confirmar → POST /seleccionar/

Uso:
    python manage.py seed_cotizador
    python manage.py seed_cotizador --reset
    python manage.py seed_cotizador --delete
    python manage.py seed_cotizador --sesion 5
    python manage.py seed_cotizador --base-url https://otro.dominio.ec/aria-api/v1/
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'ARIA — Cotizador de seguros'
BASE_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/aria-api/v1/'

# Nombres canónicos del seed v1 (legacy) — se borran en --reset para evitar
# que queden colgados credenciales/endpoints obsoletos del flujo /aria/.
LEGACY_CREDENCIAL = 'ARIA - AllowAny'
LEGACY_ENDPOINT = 'Cotizador ARIA'

# Nombres del seed v2 (REST).
CREDENCIAL_NOMBRE = 'ARIA REST - AllowAny'
ENDPOINT_NOMBRE = 'Cotizador ARIA REST v1'


BOT = {
    'codigo': 'aria',
    'nombre': NOMBRE_DEPTO,
    'descripcion': (
        'Asistente virtual que cotiza seguros vehiculares contra Zurich, AIG, '
        'Generali y aseguradoras locales. Versión REST stateless.'
    ),
    'mensaje_inicial': (
        '¡Hola! 👋 Soy ARIA 🤖, tu asistente para cotizar tu seguro vehicular. '
        'Vamos a generar tu cotización en pocos pasos. 🚗'
    ),
    'color_primario': '#6f42c1',
    'palabras_clave': 'aria\ncotizar\nseguro\nseguros\nplaca\nvehiculo\nvehículo\ncarro\nauto',
}


# ─────────────────────────────────────────────────────────────────
# Descriptor del flujo
#   - tipo: respuesta_texto | input_texto | llamada_http | decision |
#           menu_botones | asignar_variable | fin_conversacion
#   - llamada_http: url completa NO se usa; en su lugar `path` relativo al
#     endpoint base. `query` (GET) o `body` (POST). `extrae_variables` con
#     formato '$nombre': '$.data.foo.bar'.
# ─────────────────────────────────────────────────────────────────
PASOS = [
    # ── 10 — Saludo + lectura de flags del tenant ────────────────
    {
        'id': 10, 'orden': 10, 'tipo': 'respuesta_texto',
        'codigo': 'saludo_inicial', 'nombre': 'Saludo de bienvenida',
        'es_inicio': True,
        'mensaje': BOT['mensaje_inicial'],
        'siguiente': 20,
    },
    {
        'id': 20, 'orden': 20, 'tipo': 'llamada_http',
        'codigo': 'http_info', 'nombre': 'GET /info/ — flags del tenant',
        'metodo': 'GET', 'path': 'info/',
        'extrae_variables': {
            '$requiere_canton': '$.data.features.requiere_canton',
            '$solo_con_placa':  '$.data.features.solo_con_placa',
            '$tenant_nombre':   '$.data.tenant.name',
        },
        'siguiente_ok': 30, 'siguiente_error': 900,
    },

    # ── 30/40 — Placa + lookup vehículo ─────────────────────────
    {
        'id': 30, 'orden': 30, 'tipo': 'input_texto',
        'codigo': 'pedir_placa', 'nombre': 'Pedir placa',
        'mensaje': '🚗 Empecemos por el vehículo. Escríbeme la *placa* (ej: ABC-1234):',
        'guardar_en': 'placa',
        'validacion': r'^[A-Za-z0-9-]{5,8}$',
        'siguiente': 40,
    },
    {
        'id': 40, 'orden': 40, 'tipo': 'llamada_http',
        'codigo': 'http_vehiculo',
        'nombre': 'GET /vehiculo/?placa= — lookup en Zurich',
        'metodo': 'GET', 'path': 'vehiculo/',
        'query': {'placa': '{{variables.placa}}'},
        'timeout_seg': 20,
        'extrae_variables': {
            '$encontrado_veh':      '$.data.encontrado',
            '$marca':               '$.data.vehiculo.marca',
            '$modelo':              '$.data.vehiculo.modelo',
            '$anio':                '$.data.vehiculo.anio',
            '$tipo_vehiculo_id':    '$.data.vehiculo.tipo_sugerido.id',
            '$tipo_vehiculo_nombre': '$.data.vehiculo.tipo_sugerido.nombre',
            '$color_id':            '$.data.vehiculo.color_id',
            '$color_name':          '$.data.vehiculo.color_name',
        },
        'siguiente_ok': 50, 'siguiente_error': 900,
    },
    {
        'id': 50, 'orden': 50, 'tipo': 'decision',
        'codigo': 'vehiculo_encontrado', 'nombre': '¿Vehículo encontrado?',
        'condicion': '{{variables.encontrado_veh}} == true',
        'siguiente_si': 60, 'siguiente_no': 901,
    },
    {
        'id': 60, 'orden': 60, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_vehiculo', 'nombre': 'Mostrar datos del vehículo',
        'mensaje': (
            '✅ Encontré el vehículo:\n'
            '• Marca: *{{variables.marca}}*\n'
            '• Modelo: *{{variables.modelo}}*\n'
            '• Año: *{{variables.anio}}*\n'
            '• Tipo: *{{variables.tipo_vehiculo_nombre}}*\n'
            '• Color sugerido: *{{variables.color_name}}*'
        ),
        'siguiente': 70,
    },

    # ── 70/80/90 — Cédula + lookup cliente ─────────────────────
    {
        'id': 70, 'orden': 70, 'tipo': 'input_texto',
        'codigo': 'pedir_cedula', 'nombre': 'Pedir cédula / RUC',
        'mensaje': '🪪 Ahora dame tu *cédula o RUC* (10 dígitos cédula · 13 dígitos RUC):',
        'guardar_en': 'cedula',
        'validacion': r'^[0-9]{10}([0-9]{3})?$',
        'siguiente': 80,
    },
    {
        'id': 80, 'orden': 80, 'tipo': 'llamada_http',
        'codigo': 'http_cliente',
        'nombre': 'GET /cliente/?cedula= — lookup en Zurich',
        'metodo': 'GET', 'path': 'cliente/',
        'query': {'cedula': '{{variables.cedula}}'},
        'timeout_seg': 20,
        'extrae_variables': {
            '$encontrado_cli': '$.data.encontrado',
            '$nombres':        '$.data.cliente.nombres',
            '$apellidos':      '$.data.cliente.apellidos',
            '$email':          '$.data.cliente.email',
            '$telefono':       '$.data.cliente.telefono',
            '$driver_age':     '$.data.cliente.edad',
            '$civil_status':   '$.data.cliente.civil_status',
            '$gender':         '$.data.cliente.gender',
        },
        'siguiente_ok': 90, 'siguiente_error': 900,
    },
    {
        'id': 90, 'orden': 90, 'tipo': 'decision',
        'codigo': 'cliente_encontrado', 'nombre': '¿Cliente encontrado?',
        'condicion': '{{variables.encontrado_cli}} == true',
        'siguiente_si': 200, 'siguiente_no': 100,
    },

    # ── 100..130 — Datos del cliente (si no estaba en BD) ──────
    {
        'id': 100, 'orden': 100, 'tipo': 'input_texto',
        'codigo': 'pedir_nombres', 'nombre': 'Pedir nombres',
        'mensaje': 'No te encontré en el sistema. ¿Cuál es tu *nombre*?',
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
        'codigo': 'pedir_email', 'nombre': 'Pedir email',
        'mensaje': '¿A qué *correo* te mando la cotización?',
        'guardar_en': 'email',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 130,
    },
    {
        'id': 130, 'orden': 130, 'tipo': 'input_texto',
        'codigo': 'pedir_telefono', 'nombre': 'Pedir teléfono',
        'mensaje': '¿Y tu *celular*? (10 dígitos, empieza con 0)',
        'guardar_en': 'telefono',
        'validacion': r'^0[0-9]{9}$',
        'siguiente': 200,
    },

    # ── 200/210 — Catálogo tipos vehículo ──────────────────────
    {
        'id': 200, 'orden': 200, 'tipo': 'llamada_http',
        'codigo': 'http_tipos_vehiculo',
        'nombre': 'GET /catalogos/tipos-vehiculo/',
        'metodo': 'GET', 'path': 'catalogos/tipos-vehiculo/',
        'extrae_variables': {'$tipos': '$.data.tipos'},
        'siguiente_ok': 210, 'siguiente_error': 900,
    },
    {
        'id': 210, 'orden': 210, 'tipo': 'menu_botones',
        'codigo': 'pedir_tipo_vehiculo', 'nombre': 'Elegir tipo de vehículo',
        'mensaje': '🚙 Elige el *tipo de vehículo*:',
        'guardar_en': 'tipo_vehiculo_id',
        'opciones': [],  # dinámicas, se generan desde variables.tipos
        'opciones_fuente': {
            'variable': 'variables.tipos',
            'campo_id': 'id',
            'campo_etiqueta': 'nombre',
            'salida': '',  # arista default
            'limite': 10,
        },
        'siguiente': 220,
    },

    # ── 220/230 — Catálogo provincias ──────────────────────────
    {
        'id': 220, 'orden': 220, 'tipo': 'llamada_http',
        'codigo': 'http_provincias',
        'nombre': 'GET /catalogos/provincias/',
        'metodo': 'GET', 'path': 'catalogos/provincias/',
        'extrae_variables': {'$provincias': '$.data.provincias'},
        'siguiente_ok': 230, 'siguiente_error': 900,
    },
    {
        'id': 230, 'orden': 230, 'tipo': 'menu_botones',
        'codigo': 'pedir_provincia', 'nombre': 'Elegir provincia',
        'mensaje': '📍 Elige tu *provincia*:',
        'guardar_en': 'provincia_id',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.provincias',
            'campo_id': 'id',
            'campo_etiqueta': 'nombre',
            'salida': '',
            'limite': 30,  # 24+ provincias EC, sin tope WhatsApp en preview
        },
        'siguiente': 240,
    },

    # ── 240..260 — Cantones (solo si requiere_canton) ──────────
    {
        'id': 240, 'orden': 240, 'tipo': 'decision',
        'codigo': 'requiere_canton', 'nombre': '¿El tenant requiere cantón?',
        'condicion': '{{variables.requiere_canton}} == true',
        'siguiente_si': 250, 'siguiente_no': 300,
    },
    {
        'id': 250, 'orden': 250, 'tipo': 'llamada_http',
        'codigo': 'http_cantones',
        'nombre': 'GET /catalogos/cantones/?provincia_id=',
        'metodo': 'GET', 'path': 'catalogos/cantones/',
        'query': {'provincia_id': '{{variables.provincia_id}}'},
        'extrae_variables': {'$cantones': '$.data.cantones'},
        'siguiente_ok': 260, 'siguiente_error': 900,
    },
    {
        'id': 260, 'orden': 260, 'tipo': 'menu_botones',
        'codigo': 'pedir_canton', 'nombre': 'Elegir cantón',
        'mensaje': '🏙️ Elige tu *cantón*:',
        'guardar_en': 'canton_id',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.cantones',
            'campo_id': 'id',
            'campo_etiqueta': 'nombre',
            'salida': '',
            'limite': 50,
        },
        'siguiente': 300,
    },

    # ── 300/310 — Catálogo colores ─────────────────────────────
    {
        'id': 300, 'orden': 300, 'tipo': 'llamada_http',
        'codigo': 'http_colores',
        'nombre': 'GET /catalogos/colores/',
        'metodo': 'GET', 'path': 'catalogos/colores/',
        'extrae_variables': {'$colores': '$.data.colores'},
        'siguiente_ok': 310, 'siguiente_error': 900,
    },
    {
        'id': 310, 'orden': 310, 'tipo': 'menu_botones',
        'codigo': 'pedir_color', 'nombre': 'Elegir color',
        'mensaje': '🎨 Elige el *color* (sugerido: {{variables.color_name}}):',
        'guardar_en': 'color_id',
        'opciones': [],
        'opciones_fuente': {
            'variable': 'variables.colores',
            'campo_id': 'id',
            'campo_etiqueta': 'nombre',
            'salida': '',
            'limite': 10,
        },
        'siguiente': 320,
    },

    # ── 320/330 — Valor + accesorios ───────────────────────────
    {
        'id': 320, 'orden': 320, 'tipo': 'input_texto',
        'codigo': 'pedir_valor_vehiculo', 'nombre': 'Pedir valor del vehículo',
        'mensaje': '💵 ¿Cuánto vale el vehículo hoy? (USD, entre 1.000 y 500.000)',
        'guardar_en': 'valor_vehiculo',
        'validacion': r'^[0-9]{4,6}$',
        'siguiente': 330,
    },
    {
        'id': 330, 'orden': 330, 'tipo': 'input_texto',
        'codigo': 'pedir_accesorios', 'nombre': 'Pedir accesorios',
        'mensaje': '🔧 Valor de accesorios extras (USD, 0 si nada). Máximo 20% del valor.',
        'guardar_en': 'accesorios',
        'validacion': r'^[0-9]+$',
        'siguiente': 340,
    },

    # ── 340 — POST /cotizar/ ───────────────────────────────────
    {
        'id': 340, 'orden': 340, 'tipo': 'llamada_http',
        'codigo': 'http_cotizar',
        'nombre': 'POST /cotizar/ — DISPARA cotización',
        'metodo': 'POST', 'path': 'cotizar/',
        'timeout_seg': 60,
        'body': {
            'placa':            '{{variables.placa}}',
            'cedula':           '{{variables.cedula}}',
            'nombres':          '{{variables.nombres}}',
            'apellidos':        '{{variables.apellidos}}',
            'email':            '{{variables.email}}',
            'telefono':         '{{variables.telefono}}',
            'tipo_vehiculo_id': '{{variables.tipo_vehiculo_id}}',
            'provincia_id':     '{{variables.provincia_id}}',
            'canton_id':        '{{variables.canton_id}}',
            'color_id':         '{{variables.color_id}}',
            'valor_vehiculo':   '{{variables.valor_vehiculo}}',
            'accesorios':       '{{variables.accesorios}}',
            'civil_status':     '{{variables.civil_status}}',
            'gender':           '{{variables.gender}}',
            'driver_age':       '{{variables.driver_age}}',
        },
        'extrae_variables': {
            '$cotpk':      '$.data.cotpk',
            '$cliente_id': '$.data.cliente_id',
            '$avaluo':     '$.data.avaluo',
        },
        'siguiente_ok': 350, 'siguiente_error': 902,
    },
    {
        'id': 350, 'orden': 350, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_creada', 'nombre': 'Cotización creada',
        'mensaje': (
            '✅ ¡Listo! Cotización generada (ID *{{variables.cotpk}}*).\n'
            '💰 Avalúo: *${{variables.avaluo}}*\n\n'
            'Buscando los planes disponibles…'
        ),
        'siguiente': 360,
    },

    # ── 360/370 — GET /planes/ + mostrar ───────────────────────
    {
        'id': 360, 'orden': 360, 'tipo': 'llamada_http',
        'codigo': 'http_planes',
        'nombre': 'GET /planes/?cotpk=',
        'metodo': 'GET', 'path': 'planes/',
        'query': {'cotpk': '{{variables.cotpk}}'},
        'timeout_seg': 60,
        'extrae_variables': {
            '$planes':       '$.data.planes',
            '$total_planes': '$.data.total',
        },
        'siguiente_ok': 370, 'siguiente_error': 900,
    },
    {
        'id': 370, 'orden': 370, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_planes', 'nombre': 'Mostrar planes',
        'mensaje': (
            '🛒 *Planes disponibles ({{variables.total_planes}}):*\n\n'
            '{% for p in variables.planes %}'
            '*ID {{p.id}}* · _{{p.aseguradora}}_ — {{p.plan}}\n'
            '  Anual: ${{p.anual}} · Mensual: ${{p.mensual}}\n\n'
            '{% endfor %}'
            'Escribe el *ID* del plan que te interesa para ver el detalle.'
        ),
        'siguiente': 380,
    },
    {
        'id': 380, 'orden': 380, 'tipo': 'input_texto',
        'codigo': 'pedir_detalle_id', 'nombre': 'Pedir ID del plan',
        'mensaje': 'Pega el *ID* del plan:',
        'guardar_en': 'detalle_id',
        'validacion': r'^[0-9]+$',
        'siguiente': 390,
    },

    # ── 390/400 — GET /plan/ detalle ───────────────────────────
    {
        'id': 390, 'orden': 390, 'tipo': 'llamada_http',
        'codigo': 'http_plan_detalle',
        'nombre': 'GET /plan/?detalle_id=',
        'metodo': 'GET', 'path': 'plan/',
        'query': {'detalle_id': '{{variables.detalle_id}}'},
        'timeout_seg': 20,
        'extrae_variables': {
            '$plan_aseguradora': '$.data.aseguradora',
            '$plan_nombre':      '$.data.plan',
            '$plan_anual':       '$.data.anual',
            '$plan_mensual':     '$.data.mensual',
            '$plan_total':       '$.data.total',
            '$plan_tasa':        '$.data.tasa',
            '$plan_coberturas':  '$.data.coberturas',
            '$plan_deducibles':  '$.data.deducibles',
        },
        'siguiente_ok': 400, 'siguiente_error': 900,
    },
    {
        'id': 400, 'orden': 400, 'tipo': 'menu_botones',
        'codigo': 'menu_confirmar_plan', 'nombre': 'Confirmar plan',
        'mensaje': (
            '*{{variables.plan_aseguradora}} — {{variables.plan_nombre}}*\n'
            '💵 Anual: ${{variables.plan_anual}} · Mensual: ${{variables.plan_mensual}}\n'
            '📊 Tasa: {{variables.plan_tasa}}%\n\n'
            '*Coberturas:*\n'
            '{% for c in variables.plan_coberturas %}• {{c.nombre}}: ${{c.valor}}\n{% endfor %}\n'
            '*Deducibles:*\n'
            '{% for d in variables.plan_deducibles %}• {{d.nombre}}\n{% endfor %}\n'
            '¿Lo seleccionas?'
        ),
        'guardar_en': 'confirmar_seleccion',
        'opciones': [
            {'etiqueta': '✅ Sí, este plan',  'valor': 'si',    'siguiente': 410},
            {'etiqueta': '🔍 Ver otro plan',  'valor': 'otro',  'siguiente': 380},
            {'etiqueta': '📋 Ver lista',      'valor': 'lista', 'siguiente': 370},
        ],
    },

    # ── 410/420 — POST /seleccionar/ + entrega PDF ─────────────
    {
        'id': 410, 'orden': 410, 'tipo': 'llamada_http',
        'codigo': 'http_seleccionar',
        'nombre': 'POST /seleccionar/ — confirmar + generar PDF',
        'metodo': 'POST', 'path': 'seleccionar/',
        'timeout_seg': 30,
        'body': {
            'detalle_id': '{{variables.detalle_id}}',
            'cliente_id': '{{variables.cliente_id}}',
        },
        'extrae_variables': {
            '$pdf_url':         '$.data.pdf_url',
            '$cliente_email':   '$.data.cliente_email',
            '$cliente_nombre':  '$.data.cliente_nombre',
            '$confirmado':      '$.data.confirmado',
        },
        'siguiente_ok': 420, 'siguiente_error': 900,
    },
    {
        'id': 420, 'orden': 420, 'tipo': 'respuesta_texto',
        'codigo': 'pdf_listo', 'nombre': 'Confirmación final',
        'mensaje': (
            '🎉 ¡Plan seleccionado, {{variables.cliente_nombre}}!\n\n'
            '📧 Te enviamos la cotización en PDF a *{{variables.cliente_email}}*.\n'
            '📄 PDF: {{variables.pdf_url}}\n\n'
            '¡Gracias por usar ARIA! 💜'
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
        'id': 901, 'orden': 901, 'tipo': 'respuesta_texto',
        'codigo': 'placa_no_encontrada', 'nombre': 'Placa no encontrada',
        'mensaje': (
            '🔎 No encontré información para *{{variables.placa}}* en la base. '
            'Puedes cotizar directamente en nuestro cotizador web '
            '(ahí puedes ingresar marca, modelo y año manualmente):'
        ),
        'cta_url': 'https://fguerrero.mgaseguros.ec/cotizar/',
        'cta_display_text': 'Ir al cotizador web',
        'siguiente': 999,
    },
    {
        'id': 902, 'orden': 902, 'tipo': 'respuesta_texto',
        'codigo': 'cotizar_error', 'nombre': 'Error al cotizar',
        'mensaje': (
            '⚠️ No pude generar la cotización. Verifica que los datos sean correctos '
            'y vuelve a intentarlo más tarde.'
        ),
        'siguiente': 999,
    },
    {
        'id': 998, 'orden': 998, 'tipo': 'asignar_variable',
        'codigo': 'reset_sesion', 'nombre': 'Reset de variables',
        'asigna': {
            'cedula': '', 'placa': '', 'cotpk': '', 'detalle_id': '',
            'nombres': '', 'apellidos': '', 'email': '', 'telefono': '',
            'tipo_vehiculo_id': '', 'provincia_id': '', 'canton_id': '',
            'color_id': '', 'valor_vehiculo': '', 'accesorios': '',
            'civil_status': '', 'gender': '', 'driver_age': '',
        },
        'siguiente': 999,
    },
    {
        'id': 999, 'orden': 999, 'tipo': 'fin_conversacion',
        'codigo': 'despedida', 'nombre': 'Fin',
        'mensaje': '¡Hasta pronto! 👋 Cuando quieras volver a cotizar, aquí estaré.',
    },
]


# Mapping JSON tipo → tipo_nodo del modelo
TIPO_MAP = {
    'respuesta_texto':  'respuesta',
    'input_texto':      'pregunta',
    'llamada_http':     'http',
    'decision':         'condicional',
    'menu_botones':     'menu',
    'asignar_variable': 'set_variable',
    'fin_conversacion': 'fin',
}


def _normalizar_extraer(extrae_variables):
    """Convierte {'$paso': '$.data.foo'} a [{variable:'paso', jsonpath:'data.foo'}]."""
    if not extrae_variables:
        return []
    out = []
    for k, v in extrae_variables.items():
        nombre = k.lstrip('$')
        path = v[2:] if isinstance(v, str) and v.startswith('$.') else v
        out.append({'variable': nombre, 'jsonpath': path})
    return out


def _parse_literal(s):
    """Convierte 'true'/'false'/'null'/'123'/'\"foo\"' a su tipo Python."""
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
    """Parsea 'LHS OP RHS [&& LHS OP RHS]' al formato del motor.

    Retorna (condiciones, operador). Soporta: ==, !=, >=, <=, >, <, &&, ||.
    """
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
    help = 'Crea el flujo del cotizador ARIA v2 (REST stateless).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el depto previo (y legacy) y lo recrea.')
        parser.add_argument('--delete', action='store_true',
                            help='Solo borra el depto y sale.')
        parser.add_argument('--sesion', type=int, default=None,
                            help='ID de SesionWhatsApp para asociar el flujo.')
        parser.add_argument('--base-url', type=str, default=BASE_URL_DEFAULT,
                            help=f'Base URL del cotizador (default: {BASE_URL_DEFAULT}).')

    # ─────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────

    def _eliminar_depto(self):
        """Borra depto, nodos, conexiones, estados runtime y credencial/endpoint
        legacy del cotizador v1 que ya no se usan."""
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

        # Limpieza legacy: credencial+endpoint del seed v1.
        legacy_eps = EndpointApiChatbot.objects.filter(nombre=LEGACY_ENDPOINT)
        n_legacy_ep = legacy_eps.count()
        legacy_eps.delete()
        legacy_creds = CredencialApiChatbot.objects.filter(nombre=LEGACY_CREDENCIAL)
        n_legacy_cred = legacy_creds.count()
        legacy_creds.delete()

        return {
            'deptos': n_deptos, 'nodos': n_nodos, 'conexiones': n_conn,
            'estados': n_estados, 'huerfanos': n_huerf,
            'legacy_ep': n_legacy_ep, 'legacy_cred': n_legacy_cred,
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
            return cfg
        if t == 'decision':
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
        return {}

    def _crear_nodo(self, depto, ep, paso):
        t = paso['tipo']
        validacion_tipo = 'none'
        validacion_expr = ''
        if paso.get('validacion'):
            validacion_tipo = 'regex'
            validacion_expr = paso['validacion']

        return OpcionDepartamentoChatBot.objects.create(
            departamento=depto,
            nombre=paso.get('nombre') or paso.get('codigo', ''),
            tipo_nodo=TIPO_MAP[t],
            config=self._config_para(paso),
            es_inicio=bool(paso.get('es_inicio')),
            endpoint=ep if t == 'llamada_http' else None,
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
            # Conexiones por opción estática (etiqueta = valor del botón).
            for i, o in enumerate(paso.get('opciones', []), start=1):
                destino_id = o.get('siguiente')
                if destino_id and destino_id in mapa:
                    ConexionNodoChatbot.objects.create(
                        nodo_origen=origen, nodo_destino=mapa[destino_id],
                        etiqueta=o['valor'], orden=i,
                    )
            # Conexión default (etiqueta vacía) — usada por opciones dinámicas
            # de catálogo, donde todas las opciones comparten salida=''.
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

        if t == 'llamada_http':
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

    # ─────────────────────────────────────────────────────────
    # Main
    # ─────────────────────────────────────────────────────────

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
                    f'Conexiones: {res["conexiones"]}\n'
                    f'   Legacy borrado: {res["legacy_ep"]} endpoints + '
                    f'{res["legacy_cred"]} credenciales.'
                ))
            return

        if opts['reset']:
            res = self._eliminar_depto()
            self.stdout.write(self.style.WARNING(
                f'Reset: borrado depto "{NOMBRE_DEPTO}" '
                f'({res["nodos"]} nodos, {res["conexiones"]} conexiones) '
                f'+ {res["legacy_ep"]} endpoints legacy + '
                f'{res["legacy_cred"]} credenciales legacy.'
            ))

        depto, creado = DepartamentoChatBot.objects.get_or_create(
            nombre=NOMBRE_DEPTO,
            defaults={
                'color': BOT['color_primario'],
                'mensaje_saludo': BOT['mensaje_inicial'],
                'palabras_clave': BOT['palabras_clave'],
                'es_default': False,
                'activo_tradicional': True,
            },
        )
        if not creado:
            self.stdout.write(self.style.WARNING(
                'El depto ya existía. Usa --reset para recrearlo.'
            ))
            return

        # ── Credencial + endpoint (idempotente) ─────────────
        credencial, _ = CredencialApiChatbot.objects.get_or_create(
            nombre=CREDENCIAL_NOMBRE,
            tipo='none',
            status=True,
            defaults={
                'secretos': {},
                'descripcion': 'API REST pública del cotizador ARIA v2 (CSRF-exempt).',
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
                'descripcion': 'Endpoint base REST del cotizador ARIA v2.',
            },
        )
        if ep.credencial_id != credencial.id:
            ep.credencial = credencial
            ep.save()

        # ── Pase 1: nodos ───────────────────────────────────
        mapa = {}
        for paso in PASOS:
            mapa[paso['id']] = self._crear_nodo(depto, ep, paso)

        # ── Pase 2: conexiones ──────────────────────────────
        for paso in PASOS:
            self._crear_conexiones(mapa, paso)

        # ── Asociar a sesión si se pidió ────────────────────
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
            f'\n[OK] Flujo creado: "{depto.nombre}" (REST v2)\n'
            f'   Nodos: {total_nodos}  |  Conexiones: {total_conns}\n'
            f'   Endpoint: {ep.nombre} -> {ep.base_url}\n'
            f'   Credencial: {credencial.nombre} ({credencial.get_tipo_display()})\n'
        ))
