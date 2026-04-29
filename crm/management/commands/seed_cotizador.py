"""
Seed del cotizador ARIA v4 (función Python + webhook configurable).

El flujo recolecta cliente + vehículo, y al final dispara la **función
interna** `cotizar_aria` registrada en `crm.funciones_chatbot`. Esa función:

  1. Hace POST al webhook externo (URL leída desde el `EndpointApiChatbot`
     'ARIA — Webhook Cotizador (externo)' — editable desde
     /crm/endpoints_api/ sin tocar este archivo ni el código).
  2. El motor del flujo, viendo `config.envia_correo=True`, dispara correo
     a los asesores del depto al recibir `ok`.

El cliente recibe en WhatsApp solo "estamos procesando" (ok) o
"intentá más tarde" (error). El plan/PDF lo maneja ARIA en background.

Flujo del bot (resumido):
  /info/ → placa → /vehiculo/?placa= → confirmar →
  cédula → /cliente/?cedula= → (si no encontrado: pedir datos básicos) →
  catálogos (tipos-vehiculo, provincias, [cantones si requiere]) → pedir valor →
  función cotizar_aria → mensaje de cierre (éxito o error)

Uso:
    python manage.py seed_cotizador
    python manage.py seed_cotizador --reset
    python manage.py seed_cotizador --delete
    python manage.py seed_cotizador --sesion 5
    python manage.py seed_cotizador --base-url https://otro.dominio.ec/aria-api/v1/
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from crm.models import (
    DepartamentoChatBot, OpcionDepartamentoChatBot,
    ConexionNodoChatbot, CredencialApiChatbot, EndpointApiChatbot,
)


NOMBRE_DEPTO = 'ARIA — Cotizador de seguros'
BASE_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/aria-api/v1/'

# ─────────────────────────────────────────────────────────────────
# Valores por defecto del flujo (semilla — TODOS editables desde la UI
# del editor de pasos sin tener que tocar este archivo).
# Cambia aquí si querés sembrar otro valor inicial; el operador igual
# puede sobreescribirlo en `OpcionDepartamentoChatBot.config.opcion_default`.
# ─────────────────────────────────────────────────────────────────
PROVINCIA_DEFAULT_ID = '19'
PROVINCIA_DEFAULT_ETIQUETA = 'Pichincha'

# Nombres canónicos del seed v1 (legacy) — se borran en --reset para evitar
# que queden colgados credenciales/endpoints obsoletos del flujo /aria/.
LEGACY_CREDENCIAL = 'ARIA - AllowAny'
LEGACY_ENDPOINT = 'Cotizador ARIA'

# Nombres del seed v2 (REST stateless — se mantiene para los catálogos /info/,
# /vehiculo/, /cliente/, /catalogos/...).
CREDENCIAL_NOMBRE = 'ARIA REST - AllowAny'
ENDPOINT_NOMBRE = 'Cotizador ARIA REST v1'

# Endpoint v4: webhook EXTERNO del cotizador. La URL no vive en el código —
# se siembra acá pero el operador la edita desde /crm/endpoints_api/ sin
# tocar nada. Si mañana hay otro cotizador (otra empresa, otro broker),
# se crea un endpoint nuevo con otro nombre + nodo `funcion` que lo use,
# todo desde la UI.
WEBHOOK_EXTERNO_CREDENCIAL_NOMBRE = 'ARIA Webhook Externo (sin auth)'
WEBHOOK_EXTERNO_ENDPOINT_NOMBRE = 'ARIA — Webhook Cotizador (externo)'
WEBHOOK_EXTERNO_URL_DEFAULT = 'https://fguerrero.mgaseguros.ec/webhook/cotizar/'
WEBHOOK_EXTERNO_TIMEOUT_DEFAULT = 45


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
    # Triggers de reset (genéricos del motor — válidos en cualquier paso).
    # El operador puede tunear desde la UI sin tocar el seed.
    'reset_triggers': [
        'reiniciar', 'cancelar', 'volver al inicio', 'empezar de nuevo',
        'otra placa', 'cotizar otra', 'no es mi placa', 'no es esta',
    ],
    'mensaje_reset': (
        '🔄 Listo, empezamos de nuevo. Olvidé los datos anteriores.'
    ),
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
        # `tipo_sugerido` puede venir null aun con `encontrado: true` — en ese
        # caso usamos `tipo_name` (siempre presente cuando hay vehículo) para
        # el mensaje al cliente. El id sugerido se intenta igual: si falta, el
        # cliente elige tipo en el nodo 210.
        'extrae_variables': {
            '$encontrado_veh':      '$.data.encontrado',
            '$marca':               '$.data.vehiculo.marca',
            '$modelo':              '$.data.vehiculo.modelo',
            '$anio':                '$.data.vehiculo.anio',
            '$tipo_vehiculo_id':    '$.data.vehiculo.tipo_sugerido.id',
            '$tipo_vehiculo_nombre': '$.data.vehiculo.tipo_sugerido.nombre',
            '$tipo_name':           '$.data.vehiculo.tipo_name',
            '$color_id':            '$.data.vehiculo.color_id',
            '$color_name':          '$.data.vehiculo.color_name',
        },
        # HTTP 400 = placa inválida según Zurich → mismo destino que `encontrado=false`:
        # nodo 901 envía botón CTA al cotizador web donde puede ingresar manualmente.
        'siguiente_ok': 50, 'siguiente_error': 901,
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
            '• Tipo: *{{variables.tipo_name}}*\n'
            '• Color sugerido: *{{variables.color_name}}*'
        ),
        'siguiente': 65,
    },

    # ── 65 — Confirmar vehículo (botón "no es mi placa" → reset) ─
    # Pregunta opcional pero importante: si la placa devolvió un vehículo
    # incorrecto, el cliente puede volver al inicio sin agotar el flujo.
    # El botón "🔄 No es mi placa" envía el texto "no es mi placa" que
    # matchea con `reset_triggers` del depto y dispara reset (genérico,
    # mismo mecanismo que cualquier otro trigger de texto libre).
    {
        'id': 65, 'orden': 65, 'tipo': 'menu_botones',
        'codigo': 'confirmar_vehiculo', 'nombre': '¿Es tu vehículo?',
        'mensaje': '¿Es este tu vehículo?',
        'guardar_en': 'confirma_vehiculo',
        'opciones': [
            {'etiqueta': '✅ Sí, continuar',     'valor': 'si',              'siguiente': 70},
            {'etiqueta': '🔄 No es mi placa',    'valor': 'no es mi placa',  'siguiente': 30},
        ],
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
        'siguiente_si': 95, 'siguiente_no': 100,
    },

    # ── 95 — Mostrar al cliente los datos que ya tenemos en BD ──
    # Después del lookup exitoso por cédula, confirmamos al cliente los datos
    # que vamos a usar y le ofrecemos corregir el correo (es lo que más
    # cambia entre cotizaciones — el resto raramente se actualiza).
    {
        'id': 95, 'orden': 95, 'tipo': 'respuesta_texto',
        'codigo': 'mostrar_cliente', 'nombre': 'Mostrar datos del cliente',
        'mensaje': (
            '✅ Encontré tus datos en nuestra base:\n'
            '• Nombre: *{{variables.nombres}} {{variables.apellidos}}*\n'
            '• Email: *{{variables.email}}*\n'
            '• Teléfono: *{{variables.telefono}}*'
        ),
        'siguiente': 96,
    },

    # ── 96 — Menu: ¿el correo es correcto? ────────────────────
    {
        'id': 96, 'orden': 96, 'tipo': 'menu_botones',
        'codigo': 'confirmar_correo', 'nombre': '¿Correo correcto?',
        'mensaje': '¿El correo que tenemos sigue siendo el correcto para enviarte la cotización?',
        'guardar_en': 'confirma_correo',
        'opciones': [
            {'etiqueta': '✅ Sí, está bien',   'valor': 'si',     'siguiente': 200},
            {'etiqueta': '✏️ Cambiar correo', 'valor': 'cambiar', 'siguiente': 97},
        ],
    },

    # ── 97 — Pedir correo nuevo y sobreescribir variable email ─
    {
        'id': 97, 'orden': 97, 'tipo': 'input_texto',
        'codigo': 'pedir_email_nuevo', 'nombre': 'Pedir correo actualizado',
        'mensaje': '📧 Escribime el *correo nuevo* al que querés recibir la cotización:',
        'guardar_en': 'email',  # sobreescribe la variable que vino del lookup
        'validacion': r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$',
        'siguiente': 200,
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
        'siguiente': 215,
    },

    # ── 215 — Pre-selección de provincia (atajo Sí/Otra) ─────────
    # Atajo configurable desde la UI: el motor solo muestra 2 botones.
    # "Sí" autoasigna provincia_id = PROVINCIA_DEFAULT_ID y salta directo a
    # cantón. "Otra" carga el catálogo completo (220 → 230). El operador
    # puede cambiar el valor por defecto desde el editor sin tocar el seed.
    {
        'id': 215, 'orden': 215, 'tipo': 'menu_botones',
        'codigo': 'pedir_provincia_default', 'nombre': 'Provincia (atajo)',
        'guardar_en': 'provincia_id',
        'opciones': [],  # ignoradas cuando hay opcion_default
        'opcion_default': {
            'valor':         PROVINCIA_DEFAULT_ID,
            'etiqueta':      PROVINCIA_DEFAULT_ETIQUETA,
            'pregunta':      f'📍 ¿Tu provincia es *{PROVINCIA_DEFAULT_ETIQUETA}*?',
            'etiqueta_si':   f'✅ Sí, {PROVINCIA_DEFAULT_ETIQUETA}',
            'etiqueta_otra': '📍 Otra',
            'salida_si':     'si',
            'salida_otra':   'otra',
        },
        'siguiente_si':   240,  # confirma → cantón
        'siguiente_otra': 220,  # otra → catálogo HTTP
    },

    # ── 220/230 — Catálogo provincias (rama "otra") ─────────────
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
    # Color: NO se pregunta. /vehiculo/ ya devuelve `color_id` listo para
    # reenviar al webhook. Si el tenant no requiere cantón saltamos a 320.
    {
        'id': 240, 'orden': 240, 'tipo': 'decision',
        'codigo': 'requiere_canton', 'nombre': '¿El tenant requiere cantón?',
        'condicion': '{{variables.requiere_canton}} == true',
        'siguiente_si': 250, 'siguiente_no': 320,
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
        'siguiente': 320,
    },

    # ── 320 — Valor del vehículo ───────────────────────────────
    # `precio_accesorios` se manda hardcoded a 0 (ver nodo 340).
    {
        'id': 320, 'orden': 320, 'tipo': 'input_texto',
        'codigo': 'pedir_valor_vehiculo', 'nombre': 'Pedir valor del vehículo',
        'mensaje': '💵 ¿Cuánto vale el vehículo hoy? (USD, entre 1.000 y 500.000)',
        'guardar_en': 'valor_vehiculo',
        'validacion': r'^[0-9]{4,6}$',
        'siguiente': 340,
    },

    # ── 340 — Función interna `cotizar_aria` ────────────────────────
    # Antes: nodo HTTP que pegaba al proxy interno Django, que a su vez
    # pegaba al webhook externo ARIA → 2 saltos HTTP innecesarios para
    # un orquestador interno.
    # Ahora: nodo `funcion` que ejecuta la función Python registrada
    # `cotizar_aria` directamente. Solo se hace HTTP al webhook externo
    # (que sí es remoto y tiene su URL configurable vía EndpointApiChatbot).
    # El motor también dispara el correo a asesores si `envia_correo=True`.
    {
        'id': 340, 'orden': 340, 'tipo': 'llamada_funcion',
        'codigo': 'fn_cotizar_aria',
        'nombre': 'Función → Cotizar ARIA + email asesores',
        'funcion_codigo': 'cotizar_aria',
        'endpoint_key': 'webhook_externo',
        'envia_correo': True,
        'metodo': 'POST',
        'timeout_seg': 45,
        'body': {
            'cliente': {
                'cedula':        '{{variables.cedula}}',
                'email':         '{{variables.email}}',
                'nombres':       '{{variables.nombres}}',
                'apellidos':     '{{variables.apellidos}}',
                'telefono':      '{{variables.telefono}}',
                'edad':          '{{variables.driver_age}}',
                'civil_status':  '{{variables.civil_status}}',
                'genero':        '{{variables.gender}}',
            },
            'vehiculo': {
                'placa':             '{{variables.placa}}',
                'tipo_vehiculo':     '{{variables.tipo_vehiculo_id}}',
                'color':             '{{variables.color_id}}',
                'provincia':         '{{variables.provincia_id}}',
                'canton':            '{{variables.canton_id}}',
                'valor_comercial':   '{{variables.valor_vehiculo}}',
                'precio_accesorios': 0,
            },
            # `all=true` cotiza todas las aseguradoras del tenant. El resto
            # se manda explícitamente en false para que el webhook NO levante
            # un OR ambiguo si decide ignorar `all` y mirar solo las banderas
            # individuales. Si en el futuro querés cotizar solo un subset,
            # poné `all=False` y marcá las aseguradoras específicas en true.
            'aseguradoras': {
                'all':                 True,
                'zurich':              False,
                'aig':                 False,
                'generali':            False,
                'mapfre':              False,
                'latina':              False,
                'alianza':             False,
                'condor':              False,
                'chubb':               False,
                'aseguradora_del_sur': False,
                'atlantida':           False,
            },
        },
        'extrae_variables': {
            '$cotizacion_status':  '$.status',
            '$cotizacion_mensaje': '$.message',
        },
        'siguiente_ok': 350, 'siguiente_error': 360,
    },

    # ── 350 — Cliente: cotización en proceso ───────────────────
    {
        'id': 350, 'orden': 350, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_encolada', 'nombre': 'Cotización en proceso',
        'mensaje': (
            '✅ ¡Listo! Tu cotización está siendo procesada.\n\n'
            'Recibirás los planes disponibles por *correo* en los próximos minutos. '
            'Un asesor también fue notificado y se comunicará contigo si hace falta. '
            '🚗💜'
        ),
        'siguiente': 998,
    },

    # ── 360 — Cliente: error, intenta más tarde ─────────────────
    {
        'id': 360, 'orden': 360, 'tipo': 'respuesta_texto',
        'codigo': 'cotizacion_error_intentar_luego', 'nombre': 'Error — intenta más tarde',
        'mensaje': (
            '⚠️ No pudimos procesar tu cotización en este momento. '
            'Por favor inténtalo más tarde. Disculpa las molestias. 🙏'
        ),
        'siguiente': 999,
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
        'codigo': 'placa_no_encontrada', 'nombre': 'Placa no encontrada / inválida',
        'mensaje': (
            '🔎 No pudimos validar la placa *{{variables.placa}}* en nuestra base. '
            'Puede ser que la placa no exista en Zurich o no tenga el formato correcto.\n\n'
            'Te llevamos al cotizador web donde puedes ingresar marca, modelo y año manualmente:'
        ),
        'cta_url': 'https://fguerrero.mgaseguros.ec/cotizar/',
        'cta_display_text': '🔗 Ir al cotizador web',
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
            'cedula': '', 'placa': '',
            'nombres': '', 'apellidos': '', 'email': '', 'telefono': '',
            'tipo_vehiculo_id': '', 'provincia_id': '', 'canton_id': '',
            'color_id': '', 'valor_vehiculo': '',
            'civil_status': '', 'gender': '', 'driver_age': '',
            'cotizacion_status': '', 'cotizacion_mensaje': '',
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
    'llamada_funcion':  'funcion',
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
            # Atajo Sí/Otra: el motor render solo 2 botones y autoasigna `valor`
            # cuando se confirma. Las opciones estáticas/dinámicas son ignoradas.
            if paso.get('opcion_default'):
                cfg['opcion_default'] = paso['opcion_default']
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
            cfg = {
                'metodo': paso.get('metodo', 'GET'),
                'path': paso.get('path', ''),
                'query': paso.get('query') or {},
                'headers': paso.get('headers') or {},
                'body': paso.get('body') or {},
                'extraer': _normalizar_extraer(paso.get('extrae_variables')),
                'timeout_seg': paso.get('timeout_seg', 15),
            }
            # Flag opcional: marca el nodo como "envía correo" (side-effect)
            # → el editor lo pinta con un badge para que el operador sepa que
            # este paso dispara una notificación además de la llamada HTTP.
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
        """`eps` es un dict {clave: EndpointApiChatbot}. Los pasos http/funcion
        eligen el endpoint con `paso['endpoint_key']` (default: 'aria' para
        http, sin default para funcion)."""
        t = paso['tipo']
        validacion_tipo = 'none'
        validacion_expr = ''
        if paso.get('validacion'):
            validacion_tipo = 'regex'
            validacion_expr = paso['validacion']

        endpoint_obj = None
        if t == 'llamada_http':
            endpoint_obj = eps.get(paso.get('endpoint_key') or 'aria')
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
            # Atajo Sí/Otra: dos conexiones etiquetadas con `salida_si` / `salida_otra`.
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
                'reset_triggers': BOT['reset_triggers'],
                'mensaje_reset': BOT['mensaje_reset'],
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
                'timeout_seg': 60,  # default amplio; nodos pueden subir a 90s
                'descripcion': 'Endpoint base REST del cotizador ARIA v2 (lectura + catálogos).',
            },
        )
        if ep.credencial_id != credencial.id:
            ep.credencial = credencial
            ep.save()

        # ── Endpoint externo: webhook real del cotizador (configurable) ─
        # Lo usa el nodo 340 (`funcion=cotizar_aria`) para hacer el POST
        # outbound. La URL queda persistida en BD; cualquier cambio
        # (otro broker, otro cotizador, otra empresa) se hace desde
        # /crm/endpoints_api/ sin tocar este seed ni el código.
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
                'base_url': WEBHOOK_EXTERNO_URL_DEFAULT,
                'status': True,
                'credencial': webhook_ext_credencial,
                'headers_default': {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                'timeout_seg': WEBHOOK_EXTERNO_TIMEOUT_DEFAULT,
                'descripcion': (
                    'Webhook EXTERNO del cotizador. La función '
                    '`cotizar_aria` (registry crm.funciones_chatbot) usa '
                    'este endpoint para hacer el POST outbound. Editá la '
                    'base_url acá para cambiar de proveedor sin tocar código.'
                ),
            },
        )

        eps = {'aria': ep, 'webhook_externo': webhook_ext_ep}

        # ── Pase 1: nodos ───────────────────────────────────
        mapa = {}
        for paso in PASOS:
            mapa[paso['id']] = self._crear_nodo(depto, eps, paso)

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
            f'\n[OK] Flujo creado: "{depto.nombre}" (función Python v4)\n'
            f'   Nodos: {total_nodos}  |  Conexiones: {total_conns}\n'
            f'   Endpoint ARIA REST   : {ep.nombre} -> {ep.base_url}\n'
            f'   Endpoint Webhook ext : {webhook_ext_ep.nombre} -> {webhook_ext_ep.base_url}\n'
            f'   Credencial REST      : {credencial.nombre} ({credencial.get_tipo_display()})\n'
            f'   Función registrada   : cotizar_aria (crm.funciones_chatbot)\n'
        ))
