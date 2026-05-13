"""Registry de funciones internas invocables por nodos `tipo_nodo='funcion'`.

Cuando el motor llega a un nodo de tipo `funcion`, busca el código
configurado en `config.funcion_codigo` y llama la función Python registrada.
Es la alternativa a un nodo HTTP cuando la lógica es interna a Django:
evita el roundtrip de HTTP a sí mismo y permite llamar código Python
directo (con DB, modelos, helpers, etc.) manteniendo el flujo configurable.

Contrato de las funciones registradas:

    @registrar_funcion(
        codigo='mi_codigo',
        descripcion='Qué hace, en una línea',
        parametros={
            'cliente.cedula': 'string requerido — cédula EC',
            'vehiculo.placa': 'string requerido — placa del auto',
        },
        requiere_endpoint=True,
        ejemplo_body={'cliente': {'cedula': '{{variables.cedula}}'}},
    )
    def mi_funcion(conversacion, variables, config, endpoint=None) -> dict:
        return {
            'etiqueta':  'ok' | 'error',  # define la rama del flujo
            'body':      <dict>,           # data extraíble vía config.extraer
            'status':    <int>,            # 200 / 502 / etc.
            'error':     <str | ''>,       # mensaje de error si etiqueta='error'
        }

  - `conversacion`: instancia de `ConversacionWhatsApp` (ya cargada).
  - `variables`: dict de `EstadoFlujoChatbot.variables` (read-only para la fn).
  - `config`: el `nodo.config` completo (incluye keys propias de la función).
  - `endpoint`: instancia opcional de `EndpointApiChatbot` (para URLs externas
    configurables — la función hace HTTP outbound a este endpoint si aplica).

Nada de URLs hardcoded en este módulo: las funciones que necesiten servicios
externos leen la URL desde el `endpoint` que el nodo tiene asociado, y el
operador puede cambiarla desde `/crm/endpoints_api/` sin tocar código.

La metadata del registry alimenta el panel "Funciones disponibles" del editor
de flujo, para que el operador sepa qué códigos puede usar y qué espera cada uno.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import requests


logger = logging.getLogger(__name__)


# Registry global. Llave: código (string corto). Valor: dict con la callable
# y metadata (descripcion, parametros, requiere_endpoint, ejemplo_body).
FUNCIONES_REGISTRADAS: dict[str, dict] = {}


def registrar_funcion(
    codigo: str,
    descripcion: str = '',
    parametros: Optional[dict] = None,
    requiere_endpoint: bool = False,
    ejemplo_body: Optional[dict] = None,
):
    """Decorator que registra una función con su metadata para nodos `funcion`.

    El operador ve esta metadata en el modal "Funciones disponibles" del editor
    para entender qué hace cada código y qué espera.

    Args:
        codigo: identificador único usado en `config.funcion_codigo`.
        descripcion: una línea humana de qué hace la función.
        parametros: dict {nombre: descripcion} de los keys esperados en `config.body`.
        requiere_endpoint: si True, la función necesita un EndpointApiChatbot
            asociado al nodo (para URL externa). El editor lo señala visualmente.
        ejemplo_body: dict de ejemplo del body que el operador puede copiar.
    """
    def deco(fn: Callable) -> Callable:
        if codigo in FUNCIONES_REGISTRADAS:
            logger.warning('Sobrescribiendo función registrada con código "%s".', codigo)
        FUNCIONES_REGISTRADAS[codigo] = {
            'callable': fn,
            'codigo': codigo,
            'descripcion': descripcion or '',
            'parametros': dict(parametros or {}),
            'requiere_endpoint': bool(requiere_endpoint),
            'ejemplo_body': dict(ejemplo_body or {}),
            'modulo': fn.__module__,
            'nombre': fn.__name__,
        }
        return fn
    return deco


def obtener_funcion(codigo: str) -> Optional[Callable]:
    """Devuelve la callable registrada o None si no existe."""
    item = FUNCIONES_REGISTRADAS.get(codigo)
    return item['callable'] if item else None


def obtener_metadata(codigo: str) -> Optional[dict]:
    """Devuelve la metadata registrada (sin la callable) o None."""
    item = FUNCIONES_REGISTRADAS.get(codigo)
    if not item:
        return None
    return {k: v for k, v in item.items() if k != 'callable'}


def listar_codigos() -> list[str]:
    """Códigos disponibles para autocompletar en la UI del editor."""
    return sorted(FUNCIONES_REGISTRADAS.keys())


def listar_metadata() -> list[dict]:
    """Lista [{codigo, descripcion, parametros, ...}] sin las callables.
    Usado por el modal "Funciones disponibles" del editor."""
    return [
        {k: v for k, v in item.items() if k != 'callable'}
        for codigo, item in sorted(FUNCIONES_REGISTRADAS.items())
    ]


# ────────────────────────────────────────────────────────────────────
# Funciones registradas
# ────────────────────────────────────────────────────────────────────

@registrar_funcion(
    codigo='cotizar_aria',
    descripcion='Envía cliente+vehículo+aseguradoras al webhook externo del cotizador y notifica a asesores.',
    parametros={
        'cliente.cedula':         'string · cédula/RUC del cliente',
        'cliente.email':          'string · correo de contacto',
        'cliente.nombres':        'string · nombre(s)',
        'cliente.apellidos':      'string · apellido(s)',
        'cliente.telefono':       'string · celular EC (10 dígitos)',
        'vehiculo.placa':         'string · placa (5-8 chars alfanum)',
        'vehiculo.tipo_vehiculo': 'string · id del catálogo de tipos',
        'vehiculo.color':         'string · id del catálogo de colores',
        'vehiculo.provincia':     'string · id provincia',
        'vehiculo.canton':        'string · id cantón (si tenant lo requiere)',
        'vehiculo.valor_comercial': 'number · valor USD',
        'aseguradoras':           'objeto bool · {all, zurich, aig, ...}',
    },
    requiere_endpoint=True,
    ejemplo_body={
        'cliente': {
            'cedula': '{{variables.cedula}}',
            'email': '{{variables.email}}',
            'nombres': '{{variables.nombres}}',
            'apellidos': '{{variables.apellidos}}',
            'telefono': '{{variables.telefono}}',
        },
        'vehiculo': {
            'placa': '{{variables.placa}}',
            'tipo_vehiculo': '{{variables.tipo_vehiculo_id}}',
            'color': '{{variables.color_id}}',
            'provincia': '{{variables.provincia_id}}',
            'canton': '{{variables.canton_id}}',
            'valor_comercial': '{{variables.valor_vehiculo}}',
            'precio_accesorios': 0,
        },
        'aseguradoras': {'all': True},
    },
)
def cotizar_aria(conversacion, variables, config, endpoint=None) -> dict:
    """Llama al webhook ARIA externo + (opcional) notifica asesores.

    Antes existía un proxy HTTP intermedio (`/crm/api/cotizar/<conv_id>/`)
    que encadenaba dos saltos HTTP innecesarios (Django → Django → externo).
    Ahora el motor invoca esta función directamente y solo se hace HTTP al
    webhook externo (que sí es remoto).

    URL externa: NO hardcodeada — viene del `endpoint` que el nodo tiene
    asociado (`EndpointApiChatbot.base_url`). El operador la edita desde
    `/crm/endpoints_api/` sin tocar este archivo.

    `config` esperado del nodo:
        {
          'metodo': 'POST',
          'body':   {cliente: {...}, vehiculo: {...}, aseguradoras: {...}},
          'extraer': [{variable: 'cotizacion_status', jsonpath: 'status'}, ...],
          'timeout_seg': 45,
          'envia_correo': true,  # side-effect del motor (no de esta función)
        }

    Returns dict {etiqueta, body, status, error}.
    """
    from .motor_flujo_chatbot import resolver_expresion

    if not endpoint:
        return {
            'etiqueta': 'error',
            'body': {},
            'status': 0,
            'error': 'Nodo `funcion=cotizar_aria` sin endpoint configurado. '
                     'Asignale un EndpointApiChatbot en el editor.',
        }

    if conversacion is None:
        return {
            'etiqueta': 'error',
            'body': {},
            'status': 0,
            'error': 'Sin conversación contextual.',
        }
    if getattr(conversacion, 'conversacion_finalizada', False):
        return {
            'etiqueta': 'error',
            'body': {},
            'status': 409,
            'error': 'La conversación ya está finalizada.',
        }

    contexto = {'variables': variables or {}, 'conversacion': conversacion}

    # Resolver templates {{variables.x}} en el body.
    body_raw = config.get('body') or {}
    body = _resolver_dict(body_raw, contexto, resolver_expresion)
    body['id_conversacion'] = conversacion.id

    base_url = (endpoint.base_url or '').strip()
    if not base_url:
        return {
            'etiqueta': 'error', 'body': {}, 'status': 0,
            'error': f'Endpoint "{endpoint.nombre}" no tiene base_url.',
        }

    timeout = int(config.get('timeout_seg') or endpoint.timeout_seg or 30)
    headers = dict(endpoint.headers_default or {})
    headers.setdefault('Content-Type', 'application/json')
    headers.setdefault('Accept', 'application/json')

    try:
        r = requests.post(base_url, json=body, timeout=timeout, headers=headers)
    except requests.RequestException as ex:
        logger.exception('cotizar_aria conv#%s falló: %s', conversacion.id, ex)
        return {
            'etiqueta': 'error', 'body': {}, 'status': 502,
            'error': f'No pudimos contactar el cotizador: {str(ex)[:200]}',
        }

    try:
        resp_json = r.json()
    except ValueError:
        resp_json = {'_raw': r.text[:1000]}

    es_exito = (200 <= r.status_code < 300) and bool(resp_json.get('ok'))
    if not es_exito:
        logger.warning(
            'cotizar_aria conv#%s rechazado: status=%s body=%s',
            conversacion.id, r.status_code, resp_json,
        )
        return {
            'etiqueta': 'error', 'body': resp_json, 'status': r.status_code,
            'error': resp_json.get('error') or f'Cotizador respondió {r.status_code}.',
        }

    return {
        'etiqueta': 'ok',
        'body': {
            'success': True,
            'message': resp_json.get('mensaje') or 'Cotización en proceso.',
            'status': resp_json.get('status') or 'encolado',
            'raw': resp_json,
        },
        'status': r.status_code,
        'error': '',
    }


@registrar_funcion(
    codigo='cotizar_am',
    descripcion='Envía cliente+miembros al webhook de Vida Buena (asistencia médica), recomienda plan y notifica.',
    parametros={
        'cliente.cedula':           'string · cédula del cliente',
        'cliente.nombres':          'string · nombre(s)',
        'cliente.apellidos':        'string · apellido(s)',
        'cliente.fecha_nacimiento': 'string · YYYY-MM-DD (puede venir vacío)',
        'cliente.sexo':             'string · M | F',
        'cliente.email':            'string · correo de contacto',
        'budget_intent':            'economico | equilibrio | alta_proteccion | desconocido',
        'network_preference':       'red_cerrada_ok | quiere_red_abierta | desconocido',
        'wants_max_protection':     'bool',
        'variables.edad_titular':   'number · edad del titular (se usa para construir members[])',
        'variables.sexo_titular':   'M | F · sexo del titular',
        'variables.edades_miembros': 'string · edades de dependientes separadas por coma (opcional)',
        '(auto) cliente.telefono':  'string · número de WhatsApp del contacto (inyectado por la función)',
    },
    requiere_endpoint=True,
    ejemplo_body={
        'cliente': {
            'cedula': '{{variables.cedula}}',
            'nombres': '{{variables.nombres}}',
            'apellidos': '{{variables.apellidos}}',
            'fecha_nacimiento': '{{variables.fecha_nacimiento}}',
            'sexo': '{{variables.sexo_titular}}',
            'email': '{{variables.email}}',
        },
        'budget_intent': '{{variables.budget_intent}}',
        'network_preference': 'desconocido',
        'wants_max_protection': False,
    },
)
def cotizar_am(conversacion, variables, config, endpoint=None) -> dict:
    """Llama al webhook Vida Buena externo (asistencia médica).

    Construye `members[]` a partir de `variables.edad_titular`,
    `variables.sexo_titular` y la lista opcional `variables.edades_miembros`
    (string con edades separadas por coma — los dependientes van como
    `gender='unknown'` y `relationship='otro'`, suficiente para que el
    decision engine recomiende plan).

    Inyecta `cliente.telefono` con el número de WhatsApp del contacto
    (`Contacto.numero_telefono` o, si está vacío, `Contacto.contacto_numero`).
    Esto reemplaza cualquier teléfono que viniera en el body del nodo: la
    fuente de verdad para contactar al cliente es el chat por donde está
    escribiendo en este momento.

    URL externa: leída desde `endpoint.base_url` (editable en
    /crm/endpoints_api/). Devuelve etiqueta `ok` cuando el webhook responde
    `{ok: true}`. La recomendación, PDFs y resumen llegan al cliente
    después por correo + WhatsApp en background (responsabilidad del webhook).
    """
    from .motor_flujo_chatbot import resolver_expresion

    if not endpoint:
        return {
            'etiqueta': 'error',
            'body': {},
            'status': 0,
            'error': 'Nodo `funcion=cotizar_am` sin endpoint configurado. '
                     'Asignale un EndpointApiChatbot en el editor.',
        }

    if conversacion is None:
        return {
            'etiqueta': 'error',
            'body': {},
            'status': 0,
            'error': 'Sin conversación contextual.',
        }
    if getattr(conversacion, 'conversacion_finalizada', False):
        return {
            'etiqueta': 'error',
            'body': {},
            'status': 409,
            'error': 'La conversación ya está finalizada.',
        }

    contexto = {'variables': variables or {}, 'conversacion': conversacion}

    body_raw = config.get('body') or {}
    body = _resolver_dict(body_raw, contexto, resolver_expresion)

    vars_ = variables or {}
    edad_titular = vars_.get('edad_titular')
    sexo_titular = (vars_.get('sexo_titular') or '').strip() or 'unknown'
    edades_miembros_raw = vars_.get('edades_miembros') or ''

    members = []
    try:
        ta = int(str(edad_titular).strip()) if edad_titular not in ('', None) else None
    except (TypeError, ValueError):
        ta = None
    if ta is not None:
        members.append({
            'age': ta,
            'gender': sexo_titular,
            'relationship': 'titular',
        })

    for raw in str(edades_miembros_raw).split(','):
        raw = raw.strip()
        if not raw:
            continue
        try:
            members.append({
                'age': int(raw),
                'gender': 'unknown',
                'relationship': 'otro',
            })
        except ValueError:
            continue

    body['members'] = members
    body['id_conversacion'] = conversacion.id
    body.setdefault('network_preference', 'desconocido')
    body.setdefault('wants_max_protection', False)

    contacto = getattr(conversacion, 'contacto', None)
    wa_telefono = ''
    if contacto is not None:
        wa_telefono = (
            getattr(contacto, 'numero_telefono', '')
            or getattr(contacto, 'contacto_numero', '')
            or ''
        )
    if wa_telefono:
        if not isinstance(body.get('cliente'), dict):
            body['cliente'] = {}
        body['cliente']['telefono'] = wa_telefono

    base_url = (endpoint.base_url or '').strip()
    if not base_url:
        return {
            'etiqueta': 'error', 'body': {}, 'status': 0,
            'error': f'Endpoint "{endpoint.nombre}" no tiene base_url.',
        }

    timeout = int(config.get('timeout_seg') or endpoint.timeout_seg or 30)
    headers = dict(endpoint.headers_default or {})
    headers.setdefault('Content-Type', 'application/json')
    headers.setdefault('Accept', 'application/json')

    try:
        r = requests.post(base_url, json=body, timeout=timeout, headers=headers)
    except requests.RequestException as ex:
        logger.exception('cotizar_am conv#%s falló: %s', conversacion.id, ex)
        return {
            'etiqueta': 'error', 'body': {}, 'status': 502,
            'error': f'No pudimos contactar el cotizador: {str(ex)[:200]}',
        }

    try:
        resp_json = r.json()
    except ValueError:
        resp_json = {'_raw': r.text[:1000]}

    es_exito = (200 <= r.status_code < 300) and bool(resp_json.get('ok'))
    if not es_exito:
        logger.warning(
            'cotizar_am conv#%s rechazado: status=%s body=%s',
            conversacion.id, r.status_code, resp_json,
        )
        return {
            'etiqueta': 'error', 'body': resp_json, 'status': r.status_code,
            'error': resp_json.get('error') or f'Cotizador respondió {r.status_code}.',
        }

    return {
        'etiqueta': 'ok',
        'body': {
            'success': True,
            'message': resp_json.get('mensaje') or 'Cotización en proceso.',
            'status': resp_json.get('status') or 'encolado',
            'raw': resp_json,
        },
        'status': r.status_code,
        'error': '',
    }


@registrar_funcion(
    codigo='cotizar_am_multiple',
    descripcion='Envía cliente + members[] (titular + N dependientes) + budget_intent al webhook Vida Buena. Dispara el decision engine para recomendar plan.',
    parametros={
        'cliente.cedula':              'string · cédula del titular',
        'cliente.nombres':             'string · nombre(s)',
        'cliente.apellidos':           'string · apellido(s)',
        'cliente.fecha_nacimiento':    'string · YYYY-MM-DD',
        'cliente.sexo':                'string · M | F',
        'cliente.email':               'string · correo de contacto',
        'budget_intent':               'economico | equilibrio | alta_proteccion | desconocido',
        'network_preference':          'red_cerrada_ok | quiere_red_abierta | desconocido (default)',
        'wants_max_protection':        'bool (default False)',
        'variables.edad_titular':      'number · edad del titular',
        'variables.sexo_titular':      'M | F · sexo del titular',
        'variables.num_dependientes':  'number 0-5 · cuántos dependientes incluir',
        'variables.edad_m1..m5':       'number · edad de cada dependiente',
        'variables.sexo_m1..m5':       'M | F · sexo de cada dependiente',
        '(auto) cliente.telefono':     'string · número de WhatsApp del contacto (inyectado).',
    },
    requiere_endpoint=True,
    ejemplo_body={
        'cliente': {
            'cedula': '{{variables.cedula}}',
            'nombres': '{{variables.nombres}}',
            'apellidos': '{{variables.apellidos}}',
            'fecha_nacimiento': '{{variables.fecha_nacimiento}}',
            'sexo': '{{variables.sexo_titular}}',
            'email': '{{variables.email}}',
        },
        'budget_intent': '{{variables.budget_intent}}',
        'network_preference': 'desconocido',
        'wants_max_protection': False,
    },
)
COTIZAR_AM_MULTIPLE_DEBUG_EMAIL = 'hllerenaa1h@gmail.com'


def _notificar_error_cotizar_am_multiple(conv_id, etapa, error_msg,
                                          status=None, request_body=None,
                                          response_body=None):
    """Envia un correo de control a `COTIZAR_AM_MULTIPLE_DEBUG_EMAIL` cuando
    la función `cotizar_am_multiple` termina el flujo en error.

    Sirve como traza de "no llegó al webhook" / "el webhook respondió X"
    sin tener que abrir los logs de Daphne. Falla en silencio (loguea pero
    no propaga) para no interferir con la rama de error del flujo.
    """
    import json as _json
    try:
        from django.core.mail import EmailMessage
        partes = [
            f'Conversación: {conv_id}',
            f'Etapa: {etapa}',
            f'Error: {error_msg}',
        ]
        if status is not None:
            partes.append(f'Status HTTP: {status}')
        if request_body is not None:
            try:
                partes.append('Request body:\n' + _json.dumps(
                    request_body, indent=2, ensure_ascii=False, default=str,
                ))
            except (TypeError, ValueError):
                partes.append(f'Request body (repr): {request_body!r}')
        if response_body is not None:
            try:
                partes.append('Response body:\n' + _json.dumps(
                    response_body, indent=2, ensure_ascii=False, default=str,
                ))
            except (TypeError, ValueError):
                partes.append(f'Response body (repr): {response_body!r}')
        cuerpo = '\n\n'.join(partes)
        EmailMessage(
            subject=f'[Vida Buena] Error cotizar_am_multiple conv#{conv_id} — {etapa}',
            body=cuerpo,
            to=[COTIZAR_AM_MULTIPLE_DEBUG_EMAIL],
        ).send(fail_silently=True)
    except Exception:
        logger.exception(
            'No se pudo enviar correo de control de error a %s (conv#%s, etapa=%s)',
            COTIZAR_AM_MULTIPLE_DEBUG_EMAIL, conv_id, etapa,
        )


def cotizar_am_multiple(conversacion, variables, config, endpoint=None) -> dict:
    """Llama al webhook Vida Buena con `cliente` + `members[]` + `budget_intent`.

    El bot pidió primero los datos del titular, luego cuántos dependientes
    incluye y por cada uno (uno por uno) capturó cédula → lookup → si la API
    no encontró al miembro pidió edad + sexo manualmente. Esta función
    materializa `members[]` desde esas variables (`edad_titular`,
    `sexo_titular`, `edad_m1..m5`, `sexo_m1..m5`) y deja que el decision
    engine del webhook recomiende el plan para el titular según la
    composición del grupo + el `budget_intent`.

    Inyecta `cliente.telefono` con el número de WhatsApp del contacto y
    `id_conversacion` para que el webhook mande el resumen al chat.

    Control de error: cualquier salida con `etiqueta='error'` dispara un
    correo a `hllerenaa1h@gmail.com` con el detalle de la falla (request
    body, status, response). Esto facilita diagnosticar por qué un flujo
    cayó al mensaje "no pudimos procesar" sin tener que abrir los logs.
    """
    from .motor_flujo_chatbot import resolver_expresion

    conv_id = getattr(conversacion, 'id', '?')

    if not endpoint:
        _notificar_error_cotizar_am_multiple(
            conv_id, 'sin_endpoint',
            'Nodo cotizar_am_multiple sin endpoint configurado.',
        )
        return {
            'etiqueta': 'error',
            'body': {},
            'status': 0,
            'error': 'Nodo `funcion=cotizar_am_multiple` sin endpoint configurado. '
                     'Asignale un EndpointApiChatbot en el editor.',
        }

    if conversacion is None:
        _notificar_error_cotizar_am_multiple(
            '?', 'sin_conversacion', 'Función invocada sin conversación contextual.',
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 0,
            'error': 'Sin conversación contextual.',
        }
    if getattr(conversacion, 'conversacion_finalizada', False):
        _notificar_error_cotizar_am_multiple(
            conv_id, 'conversacion_finalizada',
            'La conversación ya estaba finalizada al llegar al nodo función.',
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 409,
            'error': 'La conversación ya está finalizada.',
        }

    contexto = {'variables': variables or {}, 'conversacion': conversacion}

    body_raw = config.get('body') or {}
    body = _resolver_dict(body_raw, contexto, resolver_expresion)

    vars_ = variables or {}

    def _to_int(value):
        if value in ('', None):
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    sexo_titular = (str(vars_.get('sexo_titular') or '').strip().upper() or 'unknown')
    edad_titular = _to_int(vars_.get('edad_titular'))

    members = []
    if edad_titular is not None:
        members.append({
            'age': edad_titular,
            'gender': sexo_titular,
            'relationship': 'titular',
        })

    num_dep = _to_int(vars_.get('num_dependientes')) or 0
    if num_dep < 0:
        num_dep = 0
    if num_dep > 5:
        num_dep = 5
    for i in range(1, num_dep + 1):
        edad = _to_int(vars_.get(f'edad_m{i}'))
        if edad is None:
            continue
        sexo = (str(vars_.get(f'sexo_m{i}') or '').strip().upper() or 'unknown')
        members.append({
            'age': edad,
            'gender': sexo,
            'relationship': 'otro',
        })

    if not members:
        _notificar_error_cotizar_am_multiple(
            conv_id, 'sin_members',
            'No se pudo construir members[]: falta edad del titular.',
            request_body={'variables_relevantes': {
                k: vars_.get(k) for k in (
                    'edad_titular', 'sexo_titular', 'num_dependientes',
                    'edad_m1', 'sexo_m1', 'edad_m2', 'sexo_m2',
                    'edad_m3', 'sexo_m3', 'edad_m4', 'sexo_m4',
                    'edad_m5', 'sexo_m5',
                )
            }},
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 400,
            'error': 'No se pudo construir members[]: falta edad del titular.',
        }

    body['members'] = members
    body['id_conversacion'] = conversacion.id
    body.setdefault('network_preference', 'desconocido')
    body.setdefault('wants_max_protection', False)
    body.pop('selecciones', None)

    contacto = getattr(conversacion, 'contacto', None)
    wa_telefono = ''
    if contacto is not None:
        wa_telefono = (
            getattr(contacto, 'numero_telefono', '')
            or getattr(contacto, 'contacto_numero', '')
            or ''
        )
    if wa_telefono:
        if not isinstance(body.get('cliente'), dict):
            body['cliente'] = {}
        body['cliente']['telefono'] = wa_telefono

    base_url = (endpoint.base_url or '').strip()
    if not base_url:
        _notificar_error_cotizar_am_multiple(
            conv_id, 'endpoint_sin_url',
            f'Endpoint "{endpoint.nombre}" no tiene base_url configurada.',
            request_body=body,
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 0,
            'error': f'Endpoint "{endpoint.nombre}" no tiene base_url.',
        }

    timeout = int(config.get('timeout_seg') or endpoint.timeout_seg or 30)
    headers = dict(endpoint.headers_default or {})
    headers.setdefault('Content-Type', 'application/json')
    headers.setdefault('Accept', 'application/json')

    try:
        r = requests.post(base_url, json=body, timeout=timeout, headers=headers)
    except requests.RequestException as ex:
        logger.exception('cotizar_am_multiple conv#%s falló: %s', conversacion.id, ex)
        _notificar_error_cotizar_am_multiple(
            conv_id, 'request_exception',
            f'No pudimos contactar el cotizador ({base_url}): {ex}',
            status=502, request_body=body,
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 502,
            'error': f'No pudimos contactar el cotizador: {str(ex)[:200]}',
        }

    try:
        resp_json = r.json()
    except ValueError:
        resp_json = {'_raw': r.text[:1000]}

    es_exito = (200 <= r.status_code < 300) and bool(resp_json.get('ok'))
    if not es_exito:
        logger.warning(
            'cotizar_am_multiple conv#%s rechazado: status=%s body=%s',
            conversacion.id, r.status_code, resp_json,
        )
        _notificar_error_cotizar_am_multiple(
            conv_id, 'webhook_rechazo',
            resp_json.get('error') or f'Cotizador respondió {r.status_code}.',
            status=r.status_code, request_body=body, response_body=resp_json,
        )
        return {
            'etiqueta': 'error', 'body': resp_json, 'status': r.status_code,
            'error': resp_json.get('error') or f'Cotizador respondió {r.status_code}.',
        }

    return {
        'etiqueta': 'ok',
        'body': {
            'success': True,
            'message': resp_json.get('mensaje') or 'Cotización en proceso.',
            'status': resp_json.get('status') or 'encolado',
            'total_members': len(members),
            'raw': resp_json,
        },
        'status': r.status_code,
        'error': '',
    }


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _resolver_dict(d, contexto, resolver):
    """Recorre un dict (recursivo) y resuelve `{{variables.x}}` en strings."""
    if isinstance(d, dict):
        return {k: _resolver_dict(v, contexto, resolver) for k, v in d.items()}
    if isinstance(d, list):
        return [_resolver_dict(x, contexto, resolver) for x in d]
    if isinstance(d, str):
        try:
            return resolver(d, contexto)
        except Exception:
            return d
    return d
