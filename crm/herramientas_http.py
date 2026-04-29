"""
crm/herramientas_http.py

Wrapper que ejecuta una HerramientaAgente: valida SSRF, arma la request según
su configuración (GET/POST, query/json/form/path), ejecuta, trunca y registra.

Usado por agents_ai/tools_builder.py para conectar las tools dinámicas al LLM.
"""
import ipaddress
import json as _json
import logging
import socket
import time
from string import Formatter
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_TIMEOUT_MAX = 30           # segundos (hard cap, independiente de la config)
_RESPONSE_MAX_BYTES = 100_000  # 100KB de respuesta máxima al LLM
_REDIRECT_MAX = 3


class HerramientaHTTPError(Exception):
    """Error controlado de ejecución de herramienta (para feed back al LLM)."""


# ─── SSRF guard ──────────────────────────────────────────────────────────────

def _es_ip_interna(host: str) -> bool:
    """Devuelve True si el host resuelve a una IP privada / loopback / link-local."""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
        except ValueError:
            continue
    return False


def _validar_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise HerramientaHTTPError('Solo se permiten URLs http/https.')
    if not parsed.hostname:
        raise HerramientaHTTPError('URL sin hostname válido.')
    host = parsed.hostname.lower()
    if host in ('localhost', 'metadata.google.internal'):
        raise HerramientaHTTPError(f'Host bloqueado por seguridad: {host}')
    if _es_ip_interna(host):
        raise HerramientaHTTPError(f'Host bloqueado (IP privada/loopback): {host}')


# ─── Interpolación de params en la URL (path) ────────────────────────────────

def _sustituir_path(url: str, valores: dict) -> tuple[str, set]:
    """
    Reemplaza {param} en la URL con los valores provistos.
    Retorna (url_final, claves_usadas). Si falta un placeholder, lanza error.
    """
    placeholders = {name for _, name, _, _ in Formatter().parse(url) if name}
    faltantes = placeholders - set(valores.keys())
    if faltantes:
        raise HerramientaHTTPError(
            f'Faltan valores para los placeholders de la URL: {", ".join(sorted(faltantes))}'
        )
    try:
        return url.format(**{k: valores[k] for k in placeholders}), placeholders
    except Exception as exc:
        raise HerramientaHTTPError(f'Error interpolando URL: {exc}')


# ─── Ejecución principal ─────────────────────────────────────────────────────

def ejecutar_herramienta(herramienta, valores: dict, conversacion=None) -> str:
    """
    Ejecuta la HerramientaAgente con los valores provistos por el LLM.

    Retorna un string que se le entrega al LLM como resultado (cuerpo de
    respuesta truncado o mensaje de error legible). Siempre registra
    LogHerramientaAgente.
    """
    from crm.models import LogHerramientaAgente

    _start = time.monotonic()
    log_kwargs = {
        'herramienta': herramienta,
        'conversacion': conversacion,
        'request_params': dict(valores) if isinstance(valores, dict) else {},
    }
    try:
        # 1. Validaciones básicas
        _validar_url(herramienta.url)
        timeout = min(int(herramienta.timeout or 10), _TIMEOUT_MAX)

        # 2. Interpolar path y separar valores
        url_final = herramienta.url
        claves_en_path: set = set()
        if herramienta.ubicacion_params == 'path' or '{' in herramienta.url:
            url_final, claves_en_path = _sustituir_path(herramienta.url, valores)
        _validar_url(url_final)
        log_kwargs['request_url'] = url_final

        # Valores restantes (no usados en path) van a query/body/form
        restantes = {k: v for k, v in valores.items() if k not in claves_en_path}

        # 3. Armar request según ubicacion_params
        kwargs_req = {
            'timeout': timeout,
            'headers': {**(herramienta.headers or {}), 'User-Agent': 'FastChatDJ-Bot/1.0'},
            'allow_redirects': False,
        }
        if herramienta.metodo == 'GET':
            # GET siempre lleva params en query (independiente de ubicacion_params
            # si fue 'path', los restantes igual van como query)
            kwargs_req['params'] = restantes
        else:  # POST
            if herramienta.ubicacion_params == 'form':
                kwargs_req['data'] = restantes
            elif herramienta.ubicacion_params == 'query':
                kwargs_req['params'] = restantes
            else:  # json (default) o path con restantes → body json
                kwargs_req['json'] = restantes

        # 4. Ejecutar con follow-redirects manual (para revalidar SSRF en cada salto)
        url_actual = url_final
        metodo_actual = herramienta.metodo
        response = None
        for salto in range(_REDIRECT_MAX + 1):
            response = requests.request(metodo_actual, url_actual, **kwargs_req)
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            siguiente = response.headers.get('Location')
            if not siguiente:
                break
            _validar_url(siguiente)
            url_actual = siguiente
            # En 303 se cambia a GET; en 307/308 se mantiene método
            if response.status_code == 303:
                metodo_actual = 'GET'
                kwargs_req.pop('json', None)
                kwargs_req.pop('data', None)
        else:
            raise HerramientaHTTPError(f'Demasiados redirects (>{_REDIRECT_MAX}).')

        # 5. Truncar respuesta
        body = response.text or ''
        if len(body) > _RESPONSE_MAX_BYTES:
            body = body[:_RESPONSE_MAX_BYTES] + '\n...[RESPUESTA TRUNCADA]'

        log_kwargs['response_status'] = response.status_code
        log_kwargs['response_body'] = body
        log_kwargs['exito'] = 200 <= response.status_code < 400

        # 6. Formatear con plantilla Jinja si existe y response es JSON
        salida = body
        if herramienta.plantilla_respuesta and log_kwargs['exito']:
            try:
                data_json = _json.loads(body) if body.strip() else {}
                from django.template import Context, Template
                salida = Template(herramienta.plantilla_respuesta).render(Context(data_json if isinstance(data_json, dict) else {'data': data_json}))
            except Exception as exc:
                logger.warning('Error aplicando plantilla_respuesta en %s: %s', herramienta.nombre, exc)
                # Caer a body crudo — el LLM igual puede interpretarlo

        if not log_kwargs['exito']:
            return f'ERROR_HTTP {response.status_code}: {body[:500]}'
        return salida

    except HerramientaHTTPError as exc:
        log_kwargs['error_mensaje'] = str(exc)
        log_kwargs['exito'] = False
        return f'ERROR: {exc}. Indica al usuario que intente más tarde o contacte soporte.'

    except requests.Timeout:
        log_kwargs['error_mensaje'] = 'timeout'
        log_kwargs['exito'] = False
        return 'ERROR: La consulta externa demoró demasiado (timeout). Indica al usuario que intente más tarde.'

    except requests.RequestException as exc:
        log_kwargs['error_mensaje'] = str(exc)[:500]
        log_kwargs['exito'] = False
        return f'ERROR: No se pudo consultar la API externa ({type(exc).__name__}). Indica al usuario que intente más tarde.'

    except Exception as exc:
        logger.exception('Error inesperado ejecutando herramienta %s', herramienta.nombre)
        log_kwargs['error_mensaje'] = f'{type(exc).__name__}: {exc}'[:500]
        log_kwargs['exito'] = False
        return f'ERROR interno ejecutando la herramienta. Indica al usuario que intente más tarde.'

    finally:
        log_kwargs['duracion_ms'] = int((time.monotonic() - _start) * 1000)
        try:
            LogHerramientaAgente.objects.create(**log_kwargs)
        except Exception as exc:
            logger.error('No se pudo grabar LogHerramientaAgente: %s', exc)
