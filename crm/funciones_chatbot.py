"""Registry de funciones internas invocables por nodos `tipo_nodo='funcion'`.

Cuando el motor llega a un nodo de tipo `funcion`, busca el código
configurado en `config.funcion_codigo` y llama la función Python registrada.
Es la alternativa a un nodo HTTP cuando la lógica es interna a Django:
evita el roundtrip de HTTP a sí mismo y permite llamar código Python
directo (con DB, modelos, helpers, etc.) manteniendo el flujo configurable.

Contrato de las funciones registradas:

    @registrar_funcion('mi_codigo')
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
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import requests


logger = logging.getLogger(__name__)


# Registry global. Llave: código (string corto), valor: callable.
# Se popula con el decorator `registrar_funcion`.
FUNCIONES_REGISTRADAS: dict[str, Callable] = {}


def registrar_funcion(codigo: str):
    """Decorator que registra una función para uso desde nodos `funcion`.

    Uso:
        @registrar_funcion('cotizar_aria')
        def cotizar_aria(conversacion, variables, config, endpoint=None):
            ...
    """
    def deco(fn: Callable) -> Callable:
        if codigo in FUNCIONES_REGISTRADAS:
            logger.warning('Sobrescribiendo función registrada con código "%s".', codigo)
        FUNCIONES_REGISTRADAS[codigo] = fn
        return fn
    return deco


def obtener_funcion(codigo: str) -> Optional[Callable]:
    """Devuelve la función registrada o None si no existe."""
    return FUNCIONES_REGISTRADAS.get(codigo)


def listar_codigos() -> list[str]:
    """Códigos disponibles para autocompletar en la UI del editor."""
    return sorted(FUNCIONES_REGISTRADAS.keys())


# ────────────────────────────────────────────────────────────────────
# Funciones registradas
# ────────────────────────────────────────────────────────────────────

@registrar_funcion('cotizar_aria')
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
