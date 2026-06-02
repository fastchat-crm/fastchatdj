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

def _respuesta_webhook_es_exito(status_code, resp_json):
    """True si la respuesta del webhook se considera exitosa.

    Acepta `ok` o `success` como flag explícito. Si no viene flag y la
    respuesta no trae `error`, un 2xx es éxito (cubre el caso 202
    encolado donde algunos webhooks devuelven `success` en vez de `ok`).
    """
    if not (200 <= status_code < 300):
        return False
    if not isinstance(resp_json, dict):
        return True
    if 'ok' in resp_json:
        return bool(resp_json['ok'])
    if 'success' in resp_json:
        return bool(resp_json['success'])
    return not bool(resp_json.get('error'))


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
        _notificar_debug_envio_cotizador(
            'cotizar_aria', conversacion.id, base_url, variables or {},
            body, status=502, error=str(ex),
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 502,
            'error': f'No pudimos contactar el cotizador: {str(ex)[:200]}',
        }

    try:
        resp_json = r.json()
    except ValueError:
        resp_json = {'_raw': r.text[:1000]}

    _notificar_debug_envio_cotizador(
        'cotizar_aria', conversacion.id, base_url, variables or {},
        body, status=r.status_code, response_body=resp_json,
    )

    es_exito = _respuesta_webhook_es_exito(r.status_code, resp_json)
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
        _notificar_debug_envio_cotizador(
            'cotizar_am', conversacion.id, base_url, vars_,
            body, status=502, error=str(ex),
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 502,
            'error': f'No pudimos contactar el cotizador: {str(ex)[:200]}',
        }

    try:
        resp_json = r.json()
    except ValueError:
        resp_json = {'_raw': r.text[:1000]}

    _notificar_debug_envio_cotizador(
        'cotizar_am', conversacion.id, base_url, vars_,
        body, status=r.status_code, response_body=resp_json,
    )

    es_exito = _respuesta_webhook_es_exito(r.status_code, resp_json)
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


COTIZADOR_DEBUG_EMAIL = 'hllerenaa1h@gmail.com'


def _notificar_error_cotizar_am_multiple(conv_id, etapa, error_msg,
                                          status=None, request_body=None,
                                          response_body=None, variables=None):
    """Envia un correo de control a `COTIZADOR_DEBUG_EMAIL` cuando
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
        if variables is not None:
            try:
                partes.append('Variables del chatbot:\n' + _json.dumps(
                    variables, indent=2, ensure_ascii=False, default=str,
                ))
            except (TypeError, ValueError):
                partes.append(f'Variables del chatbot (repr): {variables!r}')
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
            to=[COTIZADOR_DEBUG_EMAIL],
        ).send(fail_silently=True)
    except Exception:
        logger.exception(
            'No se pudo enviar correo de control de error a %s (conv#%s, etapa=%s)',
            COTIZADOR_DEBUG_EMAIL, conv_id, etapa,
        )


def _notificar_debug_envio_cotizador(funcion, conv_id, base_url, variables,
                                      request_body, status=None,
                                      response_body=None, error=None):
    """Envia un correo de traza a `COTIZADOR_DEBUG_EMAIL` cada vez que una
    función `cotizar_*` realiza (o intenta realizar) un POST al webhook.

    Pensado como herramienta de depuración temporal: deja ver exactamente qué
    se está enviando al webhook y qué responde, sin tener que abrir los logs
    de Daphne. Falla en silencio para no interferir con el flujo.
    """
    import json as _json
    try:
        from django.core.mail import EmailMessage
        if error:
            estado = 'ERROR'
        elif status is not None and 200 <= int(status) < 300:
            estado = 'OK'
        elif status is not None:
            estado = f'HTTP {status}'
        else:
            estado = 'enviado'
        partes = [
            f'Función: {funcion}',
            f'Conversación: {conv_id}',
            f'URL webhook: {base_url}',
            f'Estado: {estado}',
        ]
        if status is not None:
            partes.append(f'Status HTTP: {status}')
        if error:
            partes.append(f'Error: {error}')
        if variables is not None:
            try:
                partes.append('Variables del chatbot:\n' + _json.dumps(
                    variables, indent=2, ensure_ascii=False, default=str,
                ))
            except (TypeError, ValueError):
                partes.append(f'Variables del chatbot (repr): {variables!r}')
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
            subject=f'[Debug cotizador] {funcion} conv#{conv_id} — {estado}',
            body=cuerpo,
            to=[COTIZADOR_DEBUG_EMAIL],
        ).send(fail_silently=True)
    except Exception:
        logger.exception(
            'No se pudo enviar correo de debug cotizador a %s (funcion=%s, conv#%s)',
            COTIZADOR_DEBUG_EMAIL, funcion, conv_id,
        )


_ECONOMICO_TOKENS = {
    'economico', 'economy', 'barato', 'low', 'lowcost', 'minimo',
}
_EQUILIBRIO_TOKENS = {
    'equilibrio', 'equilibrado', 'medio', 'medium', 'balanced',
}
_ALTA_PROTECCION_TOKENS = {
    'altaproteccion', 'mayorproteccion', 'maximaproteccion',
    'alta', 'high', 'premium', 'top',
}
_PARENTESCOS_VALIDOS = {'CONYUGE', 'HIJO', 'PADRE', 'MADRE', 'OTRO'}


def _normalizar_budget(token: str) -> str:
    norm = (token or '').strip().lower().replace(' ', '').replace('-', '').replace('_', '')
    if norm in _ECONOMICO_TOKENS:
        return 'economico'
    if norm in _EQUILIBRIO_TOKENS:
        return 'equilibrio'
    if norm in _ALTA_PROTECCION_TOKENS:
        return 'alta_proteccion'
    return ''


@registrar_funcion(
    codigo='cotizar_am_multiple',
    descripcion='Envía cliente + tipo_grupo + budget_intent + dependientes[] al webhook Vida Buena. El engine recomienda 1 plan que se aplica a todos los miembros (precio cambia por edad/sexo).',
    parametros={
        'cliente.cedula':              'string · cédula del titular (10/13 dígitos)',
        'cliente.nombres':             'string · nombres del titular',
        'cliente.apellidos':           'string · apellidos del titular',
        'cliente.fecha_nacimiento':    'string · YYYY-MM-DD | DD/MM/YYYY | DD-MM-YYYY',
        'cliente.sexo':                'string · M | F',
        'cliente.email':               'string · correo de contacto',
        'budget_intent':               'economico | equilibrio | alta_proteccion (requerido)',
        'variables.edad_titular':      'number · edad del titular (no se envía, se infiere)',
        'variables.sexo_titular':      'M | F · sexo del titular',
        'variables.num_dependientes':  'number 0-5 · cuántos dependientes incluir',
        'variables.edad_m1..m5':       'number · edad de cada dependiente',
        'variables.sexo_m1..m5':       'M | F · sexo de cada dependiente',
        'variables.parentesco_m1..m5': 'CONYUGE | HIJO | PADRE | MADRE | OTRO',
        'variables.cedula_m1..m5':     'string · cédula del dependiente (opcional, "0" = no aplica)',
        'variables.nombres_m1..m5':    'string · nombres del dependiente (opcional, viene del SRI)',
        'variables.apellidos_m1..m5':  'string · apellidos del dependiente (opcional, viene del SRI)',
        '(auto) cliente.telefono':     'string · número de WhatsApp del contacto (inyectado, mín 7 dígitos)',
        '(auto) tipo_grupo':           'INDIVIDUAL | TITULAR_MAS_UNO | FAMILIA (derivado de num_dependientes)',
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
    },
)
def cotizar_am_multiple(conversacion, variables, config, endpoint=None) -> dict:
    """Cotiza Vida Buena para titular + N dependientes.

    Body que arma esta función para el webhook:

        {
          "cliente": {cedula, nombres, apellidos, fecha_nacimiento, sexo,
                      email, telefono},
          "tipo_grupo": "INDIVIDUAL" | "TITULAR_MAS_UNO" | "FAMILIA",
          "budget_intent": "economico" | "equilibrio" | "alta_proteccion",
          "dependientes": [
            {"parentesco", "edad", "sexo", (opcional) "cedula", "nombres",
             "apellidos"},
            ...
          ],
          "id_conversacion": <int opcional>
        }

    El titular vive en `cliente`, NO en `dependientes[]`. `tipo_grupo` se
    deriva del conteo: 0 → INDIVIDUAL, 1 → TITULAR_MAS_UNO, 2+ → FAMILIA.
    El engine del webhook elige UN plan según `budget_intent` y lo aplica
    a todos los miembros del grupo (cambia solo el precio por edad/sexo).

    Inyecta `cliente.telefono` con el número de WhatsApp del contacto y
    `id_conversacion` para que el webhook mande el resumen al chat.

    Control de error: cualquier salida con `etiqueta='error'` dispara un
    correo a `hllerenaa1h@gmail.com` con el detalle de la falla (request
    body, status, response). Cada invocación además dispara un correo de
    debug con el body real enviado al webhook + variables del chatbot.
    """
    from .motor_flujo_chatbot import resolver_expresion

    conv_id = getattr(conversacion, 'id', '?')

    if not endpoint:
        _notificar_error_cotizar_am_multiple(
            conv_id, 'sin_endpoint',
            'Nodo cotizar_am_multiple sin endpoint configurado.',
            variables=variables,
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
            variables=variables,
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 0,
            'error': 'Sin conversación contextual.',
        }
    if getattr(conversacion, 'conversacion_finalizada', False):
        _notificar_error_cotizar_am_multiple(
            conv_id, 'conversacion_finalizada',
            'La conversación ya estaba finalizada al llegar al nodo función.',
            variables=variables,
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

    sexo_titular = (str(vars_.get('sexo_titular') or '').strip().upper() or '')
    edad_titular = _to_int(vars_.get('edad_titular'))

    if edad_titular is None or sexo_titular not in ('M', 'F'):
        _notificar_error_cotizar_am_multiple(
            conv_id, 'titular_incompleto',
            'Falta edad o sexo del titular para armar el body.',
            request_body={'variables_relevantes': {
                k: vars_.get(k) for k in ('edad_titular', 'sexo_titular')
            }},
            variables=vars_,
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 400,
            'error': 'Datos del titular incompletos (edad/sexo).',
        }

    num_dep = _to_int(vars_.get('num_dependientes')) or 0
    if num_dep < 0:
        num_dep = 0
    if num_dep > 5:
        num_dep = 5

    dependientes = []
    for i in range(1, num_dep + 1):
        edad_i = _to_int(vars_.get(f'edad_m{i}'))
        if edad_i is None:
            continue
        sexo_i = (str(vars_.get(f'sexo_m{i}') or '').strip().upper() or 'M')
        if sexo_i not in ('M', 'F'):
            sexo_i = 'M'
        paren_i = (str(vars_.get(f'parentesco_m{i}') or '').strip().upper() or 'OTRO')
        if paren_i not in _PARENTESCOS_VALIDOS:
            paren_i = 'OTRO'
        dep = {
            'parentesco': paren_i,
            'edad': edad_i,
            'sexo': sexo_i,
        }
        ced_i = (str(vars_.get(f'cedula_m{i}') or '').strip())
        if ced_i and ced_i != '0':
            dep['cedula'] = ced_i
        nom_i = (str(vars_.get(f'nombres_m{i}') or '').strip())
        if nom_i:
            dep['nombres'] = nom_i
        ap_i = (str(vars_.get(f'apellidos_m{i}') or '').strip())
        if ap_i:
            dep['apellidos'] = ap_i
        dependientes.append(dep)

    if len(dependientes) == 0:
        tipo_grupo = 'INDIVIDUAL'
    elif len(dependientes) == 1:
        tipo_grupo = 'TITULAR_MAS_UNO'
    else:
        tipo_grupo = 'FAMILIA'

    budget_norm = _normalizar_budget(body.get('budget_intent'))
    if not budget_norm:
        _notificar_error_cotizar_am_multiple(
            conv_id, 'budget_invalido',
            f'budget_intent inválido: {body.get("budget_intent")!r}. '
            'Valores aceptados: economico | equilibrio | alta_proteccion.',
            request_body=body, variables=vars_,
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 400,
            'error': 'budget_intent inválido. Esperado: economico | equilibrio | alta_proteccion.',
        }

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
            request_body=body, variables=vars_,
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 0,
            'error': f'Endpoint "{endpoint.nombre}" no tiene base_url.',
        }

    timeout = int(config.get('timeout_seg') or endpoint.timeout_seg or 30)
    headers = dict(endpoint.headers_default or {})
    headers.setdefault('Content-Type', 'application/json')
    headers.setdefault('Accept', 'application/json')

    cliente_dict = body.get('cliente') if isinstance(body.get('cliente'), dict) else {}
    body = {
        'cliente': cliente_dict,
        'tipo_grupo': tipo_grupo,
        'budget_intent': budget_norm,
        'id_conversacion': conversacion.id,
    }
    if dependientes:
        body['dependientes'] = dependientes

    try:
        r = requests.post(base_url, json=body, timeout=timeout, headers=headers)
    except requests.RequestException as ex:
        logger.exception('cotizar_am_multiple conv#%s falló: %s', conversacion.id, ex)
        _notificar_error_cotizar_am_multiple(
            conv_id, 'request_exception',
            f'No pudimos contactar el cotizador ({base_url}): {ex}',
            status=502, request_body=body, variables=vars_,
        )
        _notificar_debug_envio_cotizador(
            'cotizar_am_multiple', conv_id, base_url, vars_,
            body, status=502, error=str(ex),
        )
        return {
            'etiqueta': 'error', 'body': {}, 'status': 502,
            'error': f'No pudimos contactar el cotizador: {str(ex)[:200]}',
        }

    try:
        resp_json = r.json()
    except ValueError:
        resp_json = {'_raw': r.text[:1000]}

    _notificar_debug_envio_cotizador(
        'cotizar_am_multiple', conv_id, base_url, vars_,
        body, status=r.status_code, response_body=resp_json,
    )

    es_exito = _respuesta_webhook_es_exito(r.status_code, resp_json)
    if not es_exito:
        logger.warning(
            'cotizar_am_multiple conv#%s rechazado: status=%s body=%s',
            conversacion.id, r.status_code, resp_json,
        )
        _notificar_error_cotizar_am_multiple(
            conv_id, 'webhook_rechazo',
            resp_json.get('error') or f'Cotizador respondió {r.status_code}.',
            status=r.status_code, request_body=body, response_body=resp_json,
            variables=vars_,
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
            'total_miembros': 1 + len(dependientes),
            'tipo_grupo': tipo_grupo,
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
