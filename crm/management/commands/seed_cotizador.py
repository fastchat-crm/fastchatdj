"""
Seed del flujo "ARIA — Cotizador de seguros" (tenant fguerrero).

Asistente conversacional que cotiza seguros vehiculares contra la API de
fguerrero.mgaseguros.ec. Todo el backend del cotizador vive en un solo
endpoint POST /aria/ con un parámetro `action` que distingue iniciar / paso /
listar_planes / detalle_plan / seleccionar_plan / etc.

Modelo del flujo:
  - 1 DepartamentoChatBot "ARIA — Cotizador de seguros".
  - 1 CredencialApiChatbot tipo none (la API es AllowAny por sesión Django).
  - 1 EndpointApiChatbot apuntando a https://fguerrero.mgaseguros.ec/aria/.
  - Nodos del flujo creados desde el descriptor PASOS en este archivo.
  - Conexiones según `siguiente` / `siguiente_ok` / `siguiente_error` /
    `siguiente_si` / `siguiente_no` y `opciones[].siguiente`.

Uso:
    python manage.py seed_cotizador
    python manage.py seed_cotizador --reset
    python manage.py seed_cotizador --delete
    python manage.py seed_cotizador --sesion 5
    python manage.py seed_cotizador --base-url https://otro.dominio.ec/aria/
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'ARIA — Cotizador de seguros'
BASE_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/aria/'


# Provincias EC (códigos INEC). Si el broker usa otra tabla, ajustar valor.
PROVINCIAS_EC = [
    ('01', 'Azuay'),            ('02', 'Bolívar'),
    ('03', 'Cañar'),            ('04', 'Carchi'),
    ('05', 'Cotopaxi'),         ('06', 'Chimborazo'),
    ('07', 'El Oro'),           ('08', 'Esmeraldas'),
    ('09', 'Guayas'),           ('10', 'Imbabura'),
    ('11', 'Loja'),             ('12', 'Los Ríos'),
    ('13', 'Manabí'),           ('14', 'Morona Santiago'),
    ('15', 'Napo'),             ('16', 'Pastaza'),
    ('17', 'Pichincha'),        ('18', 'Tungurahua'),
    ('19', 'Zamora Chinchipe'), ('20', 'Galápagos'),
    ('21', 'Sucumbíos'),        ('22', 'Orellana'),
    ('23', 'Santo Domingo'),    ('24', 'Santa Elena'),
]


def _opciones_provincia(siguiente_id):
    """Genera el array `opciones` del menú de provincias EC."""
    return [
        {'etiqueta': nombre, 'valor': cod, 'siguiente': siguiente_id}
        for cod, nombre in PROVINCIAS_EC
    ]


# ─────────────────────────────────────────────────────────────────
# Bot config (= DepartamentoChatBot)
# ─────────────────────────────────────────────────────────────────
BOT = {
    'codigo': 'aria',
    'nombre': NOMBRE_DEPTO,
    'descripcion': (
        'Asistente virtual que cotiza seguros vehiculares ante Zurich, AIG, '
        'Generali, Aseguradora del Sur, Chubb, Atlántida y aseguradoras locales. '
        'Conduce al usuario por una conversación guiada hasta elegir un plan.'
    ),
    'mensaje_inicial': '¡Hola! 👋 Soy ARIA 🤖, tu asistente para cotizar tu seguro vehicular. ¿Comenzamos? 🚗',
    'mensaje_identificacion': '🪪 Para empezar necesito tu cédula o RUC.',
    'mensaje_sin_datos': '🔎 No encontré tus datos en el sistema. Tranquilo, los registramos juntos.',
    'mensaje_despedida': '¡Gracias por usar ARIA! 💜 Cuando quieras volver a cotizar, aquí estaré.',
    'avatar': 'https://fguerrero.mgaseguros.ec/static/img/aria.png',
    'color_primario': '#6f42c1',
    'palabras_clave': 'aria\ncotizar\nseguro\nseguros\nplaca\nvehiculo\nvehículo\ncarro\nauto',
    'configuracion_extra': {
        'url_aria': 'https://fguerrero.mgaseguros.ec/aria/',
        'url_cotizador': 'https://fguerrero.mgaseguros.ec/cotizar/',
        'url_elegir_plan': 'https://fguerrero.mgaseguros.ec/elegir-plan/',
        'url_pdf_plan': 'https://fguerrero.mgaseguros.ec/cotizacion/cotizacion-enviada/',
        'session_key': 'cotichat_datos',
        'timeout_seg': 15,
    },
}


# ─────────────────────────────────────────────────────────────────
# Descriptor del flujo (id JSON → conexiones)
# ─────────────────────────────────────────────────────────────────
PASOS = [
    # ── Saludo + identificación ─────────────────────────────────
    {
        'id': 10, 'orden': 10, 'tipo': 'respuesta_texto',
        'codigo': 'saludo_inicial', 'nombre': 'Saludo de bienvenida',
        'es_inicio': True,
        'mensaje': '¡Hola! 👋 Soy ARIA 🤖, tu asistente para cotizar tu seguro vehicular. ¿Comenzamos? 🚗',
        'siguiente': 20,
    },
    {
        'id': 20, 'orden': 20, 'tipo': 'input_texto',
        'codigo': 'pedir_cedula', 'nombre': 'Pedir cédula / RUC',
        'mensaje': '🪪 Para empezar necesito tu cédula o RUC. (10 dígitos cédula · 13 dígitos RUC)',
        'guardar_en': 'cedula',
        'validacion': r'^[0-9]{10}([0-9]{3})?$',
        'siguiente': 30,
    },
    {
        'id': 30, 'orden': 30, 'tipo': 'llamada_http',
        'codigo': 'http_iniciar', 'nombre': 'API POST /aria/ (action=iniciar)',
        'metodo': 'POST', 'body': {'action': 'iniciar'},
        'extrae_variables': {
            '$paso': '$.paso', '$bot_msg': '$.bot',
            '$tipo': '$.tipo', '$opciones': '$.opciones',
        },
        'siguiente_ok': 40, 'siguiente_error': 900,
    },
    {
        'id': 40, 'orden': 40, 'tipo': 'llamada_http',
        'codigo': 'http_paso_cedula', 'nombre': 'API POST /aria/ (paso=cedula)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'cedula', 'valor': '{{variables.cedula}}'},
        'extrae_variables': {
            '$paso': '$.paso', '$bot_msg': '$.bot', '$tipo': '$.tipo',
            '$opciones': '$.opciones', '$error': '$.error',
        },
        'siguiente_ok': 50, 'siguiente_error': 900,
    },
    {
        'id': 50, 'orden': 50, 'tipo': 'decision',
        'codigo': 'cliente_encontrado',
        'nombre': '¿La API Zurich encontró cliente con esa cédula?',
        'condicion': "{{variables.paso}} == 'confirmar_cliente'",
        'siguiente_si': 60, 'siguiente_no': 70,
    },
    {
        'id': 60, 'orden': 60, 'tipo': 'menu_botones',
        'codigo': 'menu_confirmar_cliente', 'nombre': 'Confirmar datos del cliente',
        'mensaje': '{{variables.bot_msg}}',
        'guardar_en': 'confirmar_cliente_resp',
        'opciones': [
            {'etiqueta': '✅ Sí, son mis datos',     'valor': 'si', 'siguiente': 65},
            {'etiqueta': '✏️ Quiero actualizarlos', 'valor': 'no', 'siguiente': 70},
        ],
    },
    {
        'id': 65, 'orden': 65, 'tipo': 'llamada_http',
        'codigo': 'http_confirmar_cliente',
        'nombre': 'API POST /aria/ (paso=confirmar_cliente)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'confirmar_cliente',
                 'valor': '{{variables.confirmar_cliente_resp}}'},
        'extrae_variables': {
            '$paso': '$.paso', '$bot_msg': '$.bot',
            '$tipo': '$.tipo', '$opciones': '$.opciones',
        },
        'siguiente_ok': 200, 'siguiente_error': 900,
    },

    # ── Datos personales (alta de cliente) ──────────────────────
    {
        'id': 70, 'orden': 70, 'tipo': 'input_texto',
        'codigo': 'pedir_nombres', 'nombre': 'Pedir nombres',
        'mensaje': '¿Cuál es tu nombre? (primer y segundo nombre)',
        'guardar_en': 'nombres',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'siguiente': 71,
    },
    {
        'id': 71, 'orden': 71, 'tipo': 'llamada_http',
        'codigo': 'http_paso_nombres', 'nombre': 'API POST /aria/ (paso=nombres)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'nombres', 'valor': '{{variables.nombres}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot', '$tipo': '$.tipo'},
        'siguiente_ok': 72, 'siguiente_error': 900,
    },
    {
        'id': 72, 'orden': 72, 'tipo': 'input_texto',
        'codigo': 'pedir_apellidos', 'nombre': 'Pedir apellidos',
        'mensaje': '¿Y tus apellidos? (primer y segundo apellido)',
        'guardar_en': 'apellidos',
        'validacion': r'^[A-Za-zÁÉÍÓÚáéíóúüÜñÑ\s\-]{2,}$',
        'siguiente': 73,
    },
    {
        'id': 73, 'orden': 73, 'tipo': 'llamada_http',
        'codigo': 'http_paso_apellidos', 'nombre': 'API POST /aria/ (paso=apellidos)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'apellidos', 'valor': '{{variables.apellidos}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 74, 'siguiente_error': 900,
    },
    {
        'id': 74, 'orden': 74, 'tipo': 'input_texto',
        'codigo': 'pedir_email', 'nombre': 'Pedir email',
        'mensaje': '¿A qué correo te mando la cotización?',
        'guardar_en': 'email',
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 75,
    },
    {
        'id': 75, 'orden': 75, 'tipo': 'llamada_http',
        'codigo': 'http_paso_email', 'nombre': 'API POST /aria/ (paso=email)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'email', 'valor': '{{variables.email}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 76, 'siguiente_error': 900,
    },
    {
        'id': 76, 'orden': 76, 'tipo': 'input_texto',
        'codigo': 'pedir_telefono', 'nombre': 'Pedir celular',
        'mensaje': '¿Y tu número de celular? (10 dígitos, empieza con 0)',
        'guardar_en': 'telefono',
        'validacion': r'^0[0-9]{9}$',
        'siguiente': 77,
    },
    {
        'id': 77, 'orden': 77, 'tipo': 'llamada_http',
        'codigo': 'http_paso_telefono', 'nombre': 'API POST /aria/ (paso=telefono)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'telefono', 'valor': '{{variables.telefono}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 78, 'siguiente_error': 900,
    },
    {
        'id': 78, 'orden': 78, 'tipo': 'input_texto',
        'codigo': 'pedir_edad', 'nombre': 'Pedir edad',
        'mensaje': '¿Cuántos años tienes? (18 a 100)',
        'guardar_en': 'edad',
        'validacion': r'^[1-9][0-9]?$',
        'siguiente': 79,
    },
    {
        'id': 79, 'orden': 79, 'tipo': 'llamada_http',
        'codigo': 'http_paso_edad', 'nombre': 'API POST /aria/ (paso=edad)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'edad', 'valor': '{{variables.edad}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 80, 'siguiente_error': 900,
    },
    {
        'id': 80, 'orden': 80, 'tipo': 'menu_botones',
        'codigo': 'menu_civil_status', 'nombre': 'Pedir estado civil',
        'mensaje': '¿Cuál es tu estado civil?',
        'guardar_en': 'civil_status',
        'opciones': [
            {'etiqueta': 'Soltero/a',     'valor': 'SOLTERO',     'siguiente': 81},
            {'etiqueta': 'Casado/a',      'valor': 'CASADO',      'siguiente': 81},
            {'etiqueta': 'Unión libre',   'valor': 'UNION LIBRE', 'siguiente': 81},
            {'etiqueta': 'Divorciado/a',  'valor': 'DIVORCIADO',  'siguiente': 81},
            {'etiqueta': 'Viudo/a',       'valor': 'VIUDO',       'siguiente': 81},
        ],
    },
    {
        'id': 81, 'orden': 81, 'tipo': 'llamada_http',
        'codigo': 'http_paso_civil', 'nombre': 'API POST /aria/ (paso=civil_status)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'civil_status', 'valor': '{{variables.civil_status}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 82, 'siguiente_error': 900,
    },
    {
        'id': 82, 'orden': 82, 'tipo': 'menu_botones',
        'codigo': 'menu_genero', 'nombre': 'Pedir género',
        'mensaje': '¡Último dato personal! ¿Cuál es tu género?',
        'guardar_en': 'genero',
        'opciones': [
            {'etiqueta': 'Masculino', 'valor': 'M', 'siguiente': 83},
            {'etiqueta': 'Femenino',  'valor': 'F', 'siguiente': 83},
        ],
    },
    {
        'id': 83, 'orden': 83, 'tipo': 'llamada_http',
        'codigo': 'http_paso_genero', 'nombre': 'API POST /aria/ (paso=genero)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'genero', 'valor': '{{variables.genero}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 200, 'siguiente_error': 900,
    },

    # ── Vehículo: con o sin placa ───────────────────────────────
    {
        'id': 200, 'orden': 200, 'tipo': 'menu_botones',
        'codigo': 'menu_tiene_placa', 'nombre': '¿Tienes la placa a mano?',
        'mensaje': '🚗 Ahora cuéntame sobre tu vehículo. ¿Tienes la placa?',
        'guardar_en': 'tiene_placa',
        'opciones': [
            {'etiqueta': '✅ Sí, la tengo',          'valor': '1', 'siguiente': 210},
            {'etiqueta': '🔍 No, busquemos sin placa', 'valor': '0', 'siguiente': 310},
        ],
    },

    # Rama CON placa
    {
        'id': 210, 'orden': 210, 'tipo': 'input_texto',
        'codigo': 'pedir_placa', 'nombre': 'Pedir placa',
        'mensaje': '¡Genial! Escríbeme la placa (ej: ABC-1234).',
        'guardar_en': 'placa',
        'validacion': r'^[A-Za-z0-9-]{5,8}$',
        'siguiente': 211,
    },
    {
        'id': 211, 'orden': 211, 'tipo': 'llamada_http',
        'codigo': 'http_paso_placa',
        'nombre': 'API POST /aria/ (paso=placa) — lookup Zurich Vehículo',
        'metodo': 'POST', 'timeout_seg': 20,
        'body': {'action': 'paso', 'paso': 'placa', 'valor': '{{variables.placa}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot', '$tipo': '$.tipo'},
        'siguiente_ok': 212, 'siguiente_error': 900,
    },
    {
        'id': 212, 'orden': 212, 'tipo': 'decision',
        'codigo': 'vehiculo_encontrado',
        'nombre': '¿La API devolvió datos del vehículo?',
        'condicion': "{{variables.paso}} == 'confirmar_vehiculo_placa'",
        'siguiente_si': 213, 'siguiente_no': 215,
    },
    {
        'id': 213, 'orden': 213, 'tipo': 'menu_botones',
        'codigo': 'menu_confirmar_vehiculo', 'nombre': 'Confirmar datos del vehículo',
        'mensaje': '{{variables.bot_msg}}',
        'guardar_en': 'confirmar_vehiculo_resp',
        'opciones': [
            {'etiqueta': '✅ Sí, son correctos',  'valor': 'si', 'siguiente': 214},
            {'etiqueta': '✏️ Quiero modificarlos', 'valor': 'no', 'siguiente': 215},
        ],
    },
    {
        'id': 214, 'orden': 214, 'tipo': 'llamada_http',
        'codigo': 'http_confirmar_vehiculo',
        'nombre': 'API POST /aria/ (paso=confirmar_vehiculo_placa)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'confirmar_vehiculo_placa',
                 'valor': '{{variables.confirmar_vehiculo_resp}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 216, 'siguiente_error': 900,
    },
    {
        'id': 215, 'orden': 215, 'tipo': 'input_texto',
        'codigo': 'pedir_color_placa', 'nombre': 'Pedir color (con placa)',
        'mensaje': '¿De qué color es el carro? (escribe el ID de /ajaxrequest/listarcolores)',
        'guardar_en': 'color_placa',
        'siguiente': 2151,
    },
    {
        'id': 2151, 'orden': 2151, 'tipo': 'llamada_http',
        'codigo': 'http_paso_color_placa',
        'nombre': 'API POST /aria/ (paso=color_placa)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'color_placa', 'valor': '{{variables.color_placa}}'},
        'extrae_variables': {'$paso': '$.paso'},
        'siguiente_ok': 216, 'siguiente_error': 900,
    },
    {
        'id': 216, 'orden': 216, 'tipo': 'menu_botones',
        'codigo': 'pedir_provincia_placa', 'nombre': 'Pedir provincia',
        'mensaje': '¿En qué provincia circula el vehículo?',
        'guardar_en': 'provincia_placa',
        'opciones': _opciones_provincia(217),
    },
    {
        'id': 217, 'orden': 217, 'tipo': 'llamada_http',
        'codigo': 'http_paso_provincia_placa',
        'nombre': 'API POST /aria/ (paso=provincia_placa)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'provincia_placa',
                 'valor': '{{variables.provincia_placa}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 218, 'siguiente_error': 900,
    },
    {
        'id': 218, 'orden': 218, 'tipo': 'input_texto',
        'codigo': 'pedir_valor_placa', 'nombre': 'Pedir valor del vehículo',
        'mensaje': '¿Cuánto vale el vehículo hoy? (USD, solo números, entre 1.000 y 500.000)',
        'guardar_en': 'valor_placa',
        'validacion': r'^[0-9]{4,6}$',
        'siguiente': 219,
    },
    {
        'id': 219, 'orden': 219, 'tipo': 'llamada_http',
        'codigo': 'http_paso_valor_placa',
        'nombre': 'API POST /aria/ (paso=valor_placa)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'valor_placa', 'valor': '{{variables.valor_placa}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 220, 'siguiente_error': 900,
    },
    {
        'id': 220, 'orden': 220, 'tipo': 'input_texto',
        'codigo': 'pedir_accesorios_placa', 'nombre': 'Pedir valor de accesorios',
        'mensaje': '¿Tiene accesorios extras? (USD, 0 si nada). Máximo 20% del valor.',
        'guardar_en': 'accesorios_placa',
        'validacion': r'^[0-9]+$',
        'siguiente': 221,
    },
    {
        'id': 221, 'orden': 221, 'tipo': 'llamada_http',
        'codigo': 'http_paso_accesorios_placa',
        'nombre': 'API POST /aria/ (paso=accesorios_placa) — DISPARA cotización',
        'metodo': 'POST', 'timeout_seg': 60,
        'body': {'action': 'paso', 'paso': 'accesorios_placa',
                 'valor': '{{variables.accesorios_placa}}'},
        'extrae_variables': {
            '$paso': '$.paso', '$ok': '$.ok', '$cotpk': '$.cotpk',
            '$redirect': '$.redirect', '$bot_msg': '$.bot',
            '$resumen': '$.resumen', '$tipo_error': '$.tipo_error',
            '$error': '$.error',
        },
        'siguiente_ok': 400, 'siguiente_error': 900,
    },

    # Rama SIN placa
    {
        'id': 310, 'orden': 310, 'tipo': 'input_texto',
        'codigo': 'pedir_marca', 'nombre': 'Pedir marca',
        'mensaje': '¿Cuál es la marca del vehículo? (texto, mínimo 2 letras)',
        'guardar_en': 'marca',
        'siguiente': 311,
    },
    {
        'id': 311, 'orden': 311, 'tipo': 'llamada_http',
        'codigo': 'http_paso_marca', 'nombre': 'API POST /aria/ (paso=marca)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'marca', 'valor': '{{variables.marca}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 312, 'siguiente_error': 900,
    },
    {
        'id': 312, 'orden': 312, 'tipo': 'input_texto',
        'codigo': 'pedir_modelo', 'nombre': 'Pedir modelo',
        'mensaje': '¿Y el modelo?',
        'guardar_en': 'modelo',
        'siguiente': 313,
    },
    {
        'id': 313, 'orden': 313, 'tipo': 'llamada_http',
        'codigo': 'http_paso_modelo', 'nombre': 'API POST /aria/ (paso=modelo)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'modelo', 'valor': '{{variables.modelo}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 314, 'siguiente_error': 900,
    },
    {
        'id': 314, 'orden': 314, 'tipo': 'input_texto',
        'codigo': 'pedir_anio', 'nombre': 'Pedir año',
        'mensaje': '¿De qué año es el vehículo? (1990 al año en curso + 1)',
        'guardar_en': 'anio',
        'validacion': r'^(19[9][0-9]|20[0-9]{2})$',
        'siguiente': 315,
    },
    {
        'id': 315, 'orden': 315, 'tipo': 'llamada_http',
        'codigo': 'http_paso_anio', 'nombre': 'API POST /aria/ (paso=anio)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'anio', 'valor': '{{variables.anio}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 316, 'siguiente_error': 900,
    },
    {
        'id': 316, 'orden': 316, 'tipo': 'input_texto',
        'codigo': 'pedir_color_sin_placa', 'nombre': 'Pedir color',
        'mensaje': '¿Color del vehículo? (ID de /ajaxrequest/listarcolores)',
        'guardar_en': 'color',
        'siguiente': 317,
    },
    {
        'id': 317, 'orden': 317, 'tipo': 'llamada_http',
        'codigo': 'http_paso_color_sin_placa',
        'nombre': 'API POST /aria/ (paso=color)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'color', 'valor': '{{variables.color}}'},
        'extrae_variables': {'$paso': '$.paso'},
        'siguiente_ok': 318, 'siguiente_error': 900,
    },
    {
        'id': 318, 'orden': 318, 'tipo': 'menu_botones',
        'codigo': 'pedir_provincia_sin_placa', 'nombre': 'Pedir provincia',
        'mensaje': '¿En qué provincia circula?',
        'guardar_en': 'provincia',
        'opciones': _opciones_provincia(319),
    },
    {
        'id': 319, 'orden': 319, 'tipo': 'llamada_http',
        'codigo': 'http_paso_provincia_sin_placa',
        'nombre': 'API POST /aria/ (paso=provincia)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'provincia', 'valor': '{{variables.provincia}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 320, 'siguiente_error': 900,
    },
    {
        'id': 320, 'orden': 320, 'tipo': 'input_texto',
        'codigo': 'pedir_valor_sin_placa', 'nombre': 'Pedir valor del vehículo',
        'mensaje': '¿Cuánto vale el vehículo? (USD, 1.000 a 500.000)',
        'guardar_en': 'valor',
        'validacion': r'^[0-9]{4,6}$',
        'siguiente': 321,
    },
    {
        'id': 321, 'orden': 321, 'tipo': 'llamada_http',
        'codigo': 'http_paso_valor_sin_placa',
        'nombre': 'API POST /aria/ (paso=valor)',
        'metodo': 'POST',
        'body': {'action': 'paso', 'paso': 'valor', 'valor': '{{variables.valor}}'},
        'extrae_variables': {'$paso': '$.paso', '$bot_msg': '$.bot'},
        'siguiente_ok': 322, 'siguiente_error': 900,
    },
    {
        'id': 322, 'orden': 322, 'tipo': 'input_texto',
        'codigo': 'pedir_accesorios_sin_placa', 'nombre': 'Pedir accesorios',
        'mensaje': '¿Accesorios extras? (USD, 0 si no tiene). Máx 20% del valor.',
        'guardar_en': 'accesorios',
        'validacion': r'^[0-9]+$',
        'siguiente': 323,
    },
    {
        'id': 323, 'orden': 323, 'tipo': 'llamada_http',
        'codigo': 'http_paso_accesorios_sin_placa',
        'nombre': 'API POST /aria/ (paso=accesorios) — DISPARA cotización',
        'metodo': 'POST', 'timeout_seg': 60,
        'body': {'action': 'paso', 'paso': 'accesorios', 'valor': '{{variables.accesorios}}'},
        'extrae_variables': {
            '$paso': '$.paso', '$ok': '$.ok', '$cotpk': '$.cotpk',
            '$redirect': '$.redirect', '$bot_msg': '$.bot',
            '$resumen': '$.resumen', '$tipo_error': '$.tipo_error',
            '$error': '$.error',
        },
        'siguiente_ok': 400, 'siguiente_error': 900,
    },

    # ── Cotización lista, listar planes, detalle, seleccionar ───
    {
        'id': 400, 'orden': 400, 'tipo': 'decision',
        'codigo': 'cotizacion_ok', 'nombre': '¿La cotización fue exitosa?',
        'condicion': '{{variables.ok}} == true && {{variables.cotpk}} != null',
        'siguiente_si': 410, 'siguiente_no': 405,
    },
    {
        'id': 405, 'orden': 405, 'tipo': 'menu_botones',
        'codigo': 'menu_reintentar', 'nombre': 'Cotización falló',
        'mensaje': '⚠️ {{variables.error}} — ¿quieres reintentar?',
        'guardar_en': 'reintentar_resp',
        'opciones': [
            {'etiqueta': '🔁 Reintentar', 'valor': 'reintentar', 'siguiente': 406},
            {'etiqueta': '👋 Terminar',   'valor': 'fin',        'siguiente': 999},
        ],
    },
    {
        'id': 406, 'orden': 406, 'tipo': 'llamada_http',
        'codigo': 'http_reintentar',
        'nombre': 'API POST /aria/ (action=reintentar_cotizacion)',
        'metodo': 'POST', 'timeout_seg': 60,
        'body': {'action': 'reintentar_cotizacion'},
        'extrae_variables': {'$ok': '$.ok', '$cotpk': '$.cotpk', '$error': '$.error'},
        'siguiente_ok': 400, 'siguiente_error': 900,
    },
    {
        'id': 410, 'orden': 410, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_resumen', 'nombre': 'Mostrar resumen de la cotización',
        'mensaje': (
            '✅ ¡Listo! Cotización generada (ID *{{variables.cotpk}}*).\n\n'
            '📋 *Resumen:*\n{{variables.resumen}}\n\n'
            'Buscando planes disponibles…'
        ),
        'siguiente': 430,
    },
    {
        'id': 430, 'orden': 430, 'tipo': 'llamada_http',
        'codigo': 'http_listar_planes',
        'nombre': 'API POST /aria/ (action=listar_planes)',
        'metodo': 'POST', 'timeout_seg': 60,
        'body': {'action': 'listar_planes', 'cotpk': '{{variables.cotpk}}'},
        'extrae_variables': {'$planes': '$.planes', '$ok': '$.ok'},
        'siguiente_ok': 450, 'siguiente_error': 900,
    },
    {
        'id': 450, 'orden': 450, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_planes', 'nombre': 'Mostrar planes',
        'mensaje': (
            '🛒 *Planes disponibles:*\n\n'
            '{% for p in variables.planes %}'
            '*ID {{p.id}}* · _{{p.aseguradora}}_ — {{p.plan}}\n'
            '  Anual: ${{p.anual}} · Mensual: ${{p.mensual}}\n\n'
            '{% endfor %}'
            'Escribe el *ID* del plan que te interesa para ver el detalle.'
        ),
        'siguiente': 460,
    },
    {
        'id': 460, 'orden': 460, 'tipo': 'input_texto',
        'codigo': 'pedir_detalle_id', 'nombre': 'Pedir ID del plan a detallar',
        'mensaje': 'Pega el ID del plan que te interesa:',
        'guardar_en': 'detalle_id',
        'validacion': r'^[0-9]+$',
        'siguiente': 470,
    },
    {
        'id': 470, 'orden': 470, 'tipo': 'llamada_http',
        'codigo': 'http_detalle_plan',
        'nombre': 'API POST /aria/ (action=detalle_plan)',
        'metodo': 'POST', 'timeout_seg': 20,
        'body': {'action': 'detalle_plan', 'detalle_id': '{{variables.detalle_id}}'},
        'extrae_variables': {
            '$ok': '$.ok', '$plan': '$.plan', '$aseg': '$.aseguradora',
            '$tasa': '$.tasa', '$total': '$.total',
            '$anual': '$.anual', '$mensual': '$.mensual',
            '$coberturas': '$.coberturas', '$deducibles': '$.deducibles',
        },
        'siguiente_ok': 475, 'siguiente_error': 900,
    },
    {
        'id': 475, 'orden': 475, 'tipo': 'menu_botones',
        'codigo': 'menu_detalle_plan', 'nombre': 'Plan detallado',
        'mensaje': (
            '*{{variables.aseg}} — {{variables.plan}}*\n'
            'Anual: ${{variables.anual}} · Mensual: ${{variables.mensual}}\n'
            '¿Lo seleccionas?'
        ),
        'guardar_en': 'confirmar_seleccion',
        'opciones': [
            {'etiqueta': '✅ Sí, este plan',   'valor': 'si',    'siguiente': 480},
            {'etiqueta': '🔍 Ver otro plan',   'valor': 'otro',  'siguiente': 460},
            {'etiqueta': '📋 Ver lista',       'valor': 'lista', 'siguiente': 450},
        ],
    },
    {
        'id': 480, 'orden': 480, 'tipo': 'llamada_http',
        'codigo': 'http_seleccionar_plan',
        'nombre': 'API POST /aria/ (action=seleccionar_plan)',
        'metodo': 'POST', 'timeout_seg': 30,
        'body': {'action': 'seleccionar_plan',
                 'detalle_id': '{{variables.detalle_id}}',
                 'cliente_id': '{{variables.cliente_id}}'},
        'extrae_variables': {
            '$ok': '$.ok', '$pdf_url': '$.pdf_url',
            '$cliente_email': '$.cliente_email',
            '$cliente_nombre': '$.cliente_nombre',
        },
        'siguiente_ok': 490, 'siguiente_error': 900,
    },
    {
        'id': 490, 'orden': 490, 'tipo': 'respuesta_texto',
        'codigo': 'plan_seleccionado', 'nombre': 'Confirmación final',
        'mensaje': (
            '🎉 ¡Plan seleccionado, {{variables.cliente_nombre}}!\n'
            'Te enviamos la cotización en PDF a *{{variables.cliente_email}}*.\n'
            'PDF: {{variables.pdf_url}}'
        ),
        'siguiente': 998,
    },

    # ── Salidas terminales ──────────────────────────────────────
    {
        'id': 900, 'orden': 900, 'tipo': 'respuesta_texto',
        'codigo': 'error_api', 'nombre': 'Error en API',
        'mensaje': '⚠️ Hubo un problema al hablar con el servidor. Intenta más tarde.',
        'siguiente': 999,
    },
    {
        'id': 998, 'orden': 998, 'tipo': 'asignar_variable',
        'codigo': 'reset_sesion', 'nombre': 'Reset de variables de sesión',
        'asigna': {
            'cedula': '', 'nombres': '', 'apellidos': '',
            'email': '', 'telefono': '', 'edad': '',
            'civil_status': '', 'genero': '', 'tiene_placa': '',
            'placa': '', 'cotpk': '', 'detalle_id': '',
        },
        'siguiente': 999,
    },
    {
        'id': 999, 'orden': 999, 'tipo': 'fin_conversacion',
        'codigo': 'despedida', 'nombre': 'Fin de conversación',
        'mensaje': '¡Gracias por usar ARIA! 💜 Cuando quieras volver a cotizar, aquí estaré.',
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
    """Convierte {'$paso': '$.paso', ...} a [{'variable':'paso','jsonpath':'paso'}]."""
    if not extrae_variables:
        return []
    out = []
    for k, v in extrae_variables.items():
        nombre = k.lstrip('$')
        path = v[2:] if isinstance(v, str) and v.startswith('$.') else v
        out.append({'variable': nombre, 'jsonpath': path})
    return out


class Command(BaseCommand):
    help = 'Crea el flujo del cotizador ARIA (fguerrero.mgaseguros.ec).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el depto previo y lo recrea.')
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
        """Arma el dict `config` del nodo según el tipo del paso."""
        t = paso['tipo']
        if t == 'respuesta_texto' or t == 'fin_conversacion':
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
            return {'expresion': paso.get('condicion', '')}
        if t == 'asignar_variable':
            return {'asignaciones': [
                {'variable': k, 'expresion': v}
                for k, v in (paso.get('asigna') or {}).items()
            ]}
        if t == 'llamada_http':
            return {
                'metodo': paso.get('metodo', 'POST'),
                'path': '',  # El endpoint base ya tiene la URL completa
                'headers': paso.get('headers') or {},
                'body': paso.get('body') or {},
                'extraer': _normalizar_extraer(paso.get('extrae_variables')),
                'timeout_seg': paso.get('timeout_seg', 15),
            }
        return {}

    def _crear_nodo(self, depto, ep, paso):
        t = paso['tipo']
        tipo_nodo = TIPO_MAP[t]
        # Validación: si paso tiene `validacion` (regex), aplicar.
        validacion_tipo = 'none'
        validacion_expr = ''
        if paso.get('validacion'):
            validacion_tipo = 'regex'
            validacion_expr = paso['validacion']

        return OpcionDepartamentoChatBot.objects.create(
            departamento=depto,
            nombre=paso.get('nombre') or paso.get('codigo', ''),
            tipo_nodo=tipo_nodo,
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
        """Crea aristas saliendo del nodo creado para `paso`."""
        origen = mapa[paso['id']]
        t = paso['tipo']
        orden = 1

        # menu → una arista por opción, etiquetada con `valor`.
        if t == 'menu_botones':
            for o in paso.get('opciones', []):
                destino_id = o.get('siguiente')
                if destino_id and destino_id in mapa:
                    ConexionNodoChatbot.objects.create(
                        nodo_origen=origen,
                        nodo_destino=mapa[destino_id],
                        etiqueta=o['valor'],
                        orden=orden,
                    )
                    orden += 1
            return

        # decision → ramas 'true' / 'false'.
        if t == 'decision':
            if paso.get('siguiente_si') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen,
                    nodo_destino=mapa[paso['siguiente_si']],
                    etiqueta='true', orden=1,
                )
            if paso.get('siguiente_no') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen,
                    nodo_destino=mapa[paso['siguiente_no']],
                    etiqueta='false', orden=2,
                )
            return

        # http → ramas 'ok' / 'error'.
        if t == 'llamada_http':
            if paso.get('siguiente_ok') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen,
                    nodo_destino=mapa[paso['siguiente_ok']],
                    etiqueta='ok', orden=1,
                )
            if paso.get('siguiente_error') in mapa:
                ConexionNodoChatbot.objects.create(
                    nodo_origen=origen,
                    nodo_destino=mapa[paso['siguiente_error']],
                    etiqueta='error', orden=2,
                )
            return

        # respuesta / pregunta / set_variable → arista default por `siguiente`.
        if paso.get('siguiente') in mapa:
            ConexionNodoChatbot.objects.create(
                nodo_origen=origen,
                nodo_destino=mapa[paso['siguiente']],
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
                    f'Conexiones: {res["conexiones"]} | Estados: {res["estados"]}'
                ))
            return

        if opts['reset']:
            res = self._eliminar_depto()
            self.stdout.write(self.style.WARNING(
                f'Depto "{NOMBRE_DEPTO}" previo eliminado '
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
            },
        )
        if not creado:
            self.stdout.write(self.style.WARNING(
                'El depto ya existía. Usa --reset para recrearlo desde cero.'
            ))
            return

        # ── Credencial + endpoint ───────────────────────────
        credencial = CredencialApiChatbot.objects.create(
            nombre='ARIA - AllowAny', tipo='none', secretos={},
            descripcion='APIs del cotizador ARIA (sesión Django, AllowAny).',
        )
        ep = EndpointApiChatbot.objects.create(
            nombre='Cotizador ARIA',
            base_url=opts['base_url'].rstrip('/'),
            credencial=credencial,
            headers_default={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout_seg=BOT['configuracion_extra']['timeout_seg'],
            descripcion='Endpoint base del cotizador conversacional ARIA (fguerrero).',
        )

        # ── Pase 1: crear todos los nodos (id_json → instancia) ──
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
                    f'modo_bot={s.modo_bot}.'
                ))

        total_nodos = depto.opciondepartamentochatbot_set.count()
        total_conns = ConexionNodoChatbot.objects.filter(nodo_origen__departamento=depto).count()
        self.stdout.write(self.style.SUCCESS(
            f'\n[OK] Flujo creado: "{depto.nombre}"\n'
            f'   Nodos: {total_nodos}  |  Conexiones: {total_conns}\n'
            f'   Endpoint: {ep.nombre} -> {ep.base_url}\n'
            f'   Credencial: {credencial.nombre} ({credencial.get_tipo_display()})\n'
        ))
