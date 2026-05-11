"""
agents_ai/tools_builder.py

Convierte objetos HerramientaAgente en StructuredTool de LangChain, para que
el LLM los pueda invocar vía function-calling.

El schema de parámetros se construye dinámicamente con pydantic — así el LLM
ve tipos y descripciones correctos para cada campo que debe recolectar del
usuario antes de llamar la API.
"""
import logging
import re
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from crm.herramientas_http import ejecutar_herramienta

logger = logging.getLogger(__name__)


_BODY_TEMPLATES_FUNCION = {
    'cotizar_am': {
        'cliente': {
            'cedula':           '{{variables.cedula}}',
            'nombres':          '{{variables.nombres}}',
            'apellidos':        '{{variables.apellidos}}',
            'fecha_nacimiento': '{{variables.fecha_nacimiento}}',
            'sexo':             '{{variables.sexo_titular}}',
            'email':            '{{variables.email}}',
        },
        'budget_intent':         '{{variables.budget_intent}}',
        'network_preference':    'desconocido',
        'wants_max_protection':  False,
        'plan_preferido':        '{{variables.plan_preferido}}',
    },
    'cotizar_aria': {},
}


def _mapear_kwargs_a_variables(funcion_codigo: str, kwargs: dict) -> dict:
    if funcion_codigo == 'cotizar_am':
        sexo_raw = (kwargs.get('sexo') or '').strip().upper() or 'unknown'
        return {
            'cedula':           (kwargs.get('cedula') or '').strip(),
            'nombres':          (kwargs.get('nombres') or '').strip(),
            'apellidos':        (kwargs.get('apellidos') or '').strip(),
            'fecha_nacimiento': (kwargs.get('fecha_nacimiento') or '').strip(),
            'sexo_titular':     sexo_raw if sexo_raw in ('M', 'F') else 'unknown',
            'email':            (kwargs.get('email') or '').strip(),
            'edad_titular':     kwargs.get('edad_titular'),
            'edades_miembros':  (kwargs.get('edades_dependientes') or '').strip(),
            'budget_intent':    (kwargs.get('budget_intent') or 'equilibrio').strip().lower(),
            'plan_preferido':   (kwargs.get('plan_preferido') or '').strip(),
        }
    return dict(kwargs)


def _ejecutar_funcion_interna(herramienta, kwargs: dict, conversacion=None) -> str:
    from crm.funciones_chatbot import FUNCIONES_REGISTRADAS
    from crm.models import EndpointApiChatbot, LogHerramientaAgente

    codigo = (herramienta.funcion_codigo or '').strip()
    log_kwargs = {
        'herramienta': herramienta,
        'conversacion': conversacion,
        'request_params': dict(kwargs),
        'request_url': f'funcion://{codigo}',
    }
    item = FUNCIONES_REGISTRADAS.get(codigo)
    if not item:
        msg = f'Función "{codigo}" no está registrada en FUNCIONES_REGISTRADAS.'
        logger.error('tools_builder: %s', msg)
        log_kwargs['error_mensaje'] = msg
        log_kwargs['exito'] = False
        log_kwargs['response_status'] = 0
        log_kwargs['response_body'] = msg
        try:
            LogHerramientaAgente.objects.create(**log_kwargs)
        except Exception:
            pass
        return f'ERROR codigo_error=funcion_no_registrada · message={msg}'

    if conversacion is None:
        msg = 'Sin conversación contextual — la función no se puede ejecutar.'
        logger.error('tools_builder funcion=%s: %s', codigo, msg)
        log_kwargs['error_mensaje'] = msg
        log_kwargs['exito'] = False
        try:
            LogHerramientaAgente.objects.create(**log_kwargs)
        except Exception:
            pass
        return f'ERROR codigo_error=conversacion_no_resuelta · message={msg}'

    variables = _mapear_kwargs_a_variables(codigo, kwargs)
    config = {'body': _BODY_TEMPLATES_FUNCION.get(codigo, {})}

    endpoint = None
    if item.get('requiere_endpoint', False):
        nombre_ep = (herramienta.url or '').strip()
        if nombre_ep:
            endpoint = EndpointApiChatbot.objects.filter(nombre=nombre_ep, status=True).first()
        if endpoint is None:
            endpoint = EndpointApiChatbot.objects.filter(
                base_url__icontains='cotimedica/webhook', status=True,
            ).first()
        if endpoint is None:
            msg = (
                f'Función {codigo} requiere endpoint pero no encontré ninguno. '
                f'Configurá uno en /crm/endpoints_api/ y poné su nombre en HerramientaAgente.url.'
            )
            logger.error('tools_builder funcion=%s: %s', codigo, msg)
            log_kwargs['error_mensaje'] = msg
            log_kwargs['exito'] = False
            try:
                LogHerramientaAgente.objects.create(**log_kwargs)
            except Exception:
                pass
            return f'ERROR codigo_error=endpoint_no_configurado · message={msg}'

    fn = item['callable']
    try:
        resultado = fn(conversacion, variables, config, endpoint=endpoint)
    except Exception as exc:
        logger.exception('tools_builder funcion=%s excepcion: %s', codigo, exc)
        log_kwargs['error_mensaje'] = f'{type(exc).__name__}: {exc}'
        log_kwargs['exito'] = False
        try:
            LogHerramientaAgente.objects.create(**log_kwargs)
        except Exception:
            pass
        return f'ERROR codigo_error=excepcion_python · message={type(exc).__name__}: {str(exc)[:200]}'

    etiqueta = (resultado or {}).get('etiqueta', 'error')
    status_code = (resultado or {}).get('status', 0)
    body_resp = (resultado or {}).get('body') or {}
    err = (resultado or {}).get('error') or ''

    log_kwargs['response_status'] = status_code or 0
    log_kwargs['response_body'] = str(body_resp)[:5000]
    log_kwargs['exito'] = (etiqueta == 'ok')
    if err:
        log_kwargs['error_mensaje'] = err[:500]
    try:
        LogHerramientaAgente.objects.create(**log_kwargs)
    except Exception:
        pass

    if etiqueta == 'ok':
        msg_ok = (
            body_resp.get('message') if isinstance(body_resp, dict) else None
        ) or 'Cotización en proceso. Llega por correo en minutos.'
        return f'OK status=ok · message={msg_ok}'

    if status_code == 502 or status_code == 0:
        codigo_err = 'webhook_red'
    elif 400 <= status_code < 500:
        codigo_err = f'webhook_4xx_{status_code}'
    elif 500 <= status_code < 600:
        codigo_err = f'webhook_5xx_{status_code}'
    else:
        codigo_err = 'webhook_otro'
    diag = err or 'Error desconocido del webhook.'
    body_preview = str(body_resp)[:300]
    return (
        f'ERROR codigo_error={codigo_err} · http_status={status_code} '
        f'· message={diag} · webhook_preview={body_preview}'
    )


_TIPO_PYDANTIC = {
    'string':  str,
    'integer': int,
    'number':  float,
    'boolean': bool,
}


_SLUG_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _nombre_valido(nombre: str) -> bool:
    """El nombre de la tool debe ser un identificador válido para el LLM."""
    return bool(nombre and _SLUG_RE.match(nombre))


def _construir_args_schema(herramienta) -> type[BaseModel]:
    """Genera dinámicamente un modelo pydantic desde herramienta.parametros."""
    campos: dict[str, tuple[Any, Any]] = {}
    for p in herramienta.parametros or []:
        nombre = p.get('nombre')
        if not nombre or not _nombre_valido(nombre):
            continue
        py_type = _TIPO_PYDANTIC.get(p.get('tipo'), str)
        descripcion = p.get('descripcion', '') or p.get('pregunta_sugerida', '') or nombre
        default = ... if p.get('requerido', True) else None
        if not p.get('requerido', True):
            py_type = py_type | None  # type: ignore
        campos[nombre] = (py_type, Field(default=default, description=descripcion))

    if not campos:
        campos['_placeholder'] = (str, Field(default='', description='No usar'))

    nombre_modelo = f'Args_{herramienta.nombre}_{herramienta.id}'
    return create_model(nombre_modelo, __base__=BaseModel, **campos)


def build_tool_desde_herramienta(herramienta, conversacion=None) -> StructuredTool | None:
    """
    Convierte una HerramientaAgente activa en un StructuredTool listo para
    bind_tools(). Retorna None si la configuración es inválida.
    """
    if not _nombre_valido(herramienta.nombre):
        logger.warning(
            'HerramientaAgente #%s nombre inválido para LLM: %r — omitida',
            herramienta.id, herramienta.nombre,
        )
        return None

    args_schema = _construir_args_schema(herramienta)

    def _run(**kwargs) -> str:
        valores = {k: v for k, v in kwargs.items() if k != '_placeholder' and v is not None}
        if (getattr(herramienta, 'funcion_codigo', '') or '').strip():
            return _ejecutar_funcion_interna(herramienta, valores, conversacion=conversacion)
        return ejecutar_herramienta(herramienta, valores, conversacion=conversacion)

    # Descripción que ve el LLM: su descripción + qué datos necesita
    partes_desc = [herramienta.descripcion or '']
    requeridos = [p for p in (herramienta.parametros or []) if p.get('requerido', True)]
    if requeridos:
        campos = ', '.join(p['nombre'] for p in requeridos if p.get('nombre'))
        partes_desc.append(f'Requiere obtener del usuario: {campos}.')
    descripcion_llm = ' '.join(s for s in partes_desc if s).strip()

    try:
        return StructuredTool.from_function(
            name=herramienta.nombre,
            description=descripcion_llm,
            args_schema=args_schema,
            func=_run,
        )
    except Exception as exc:
        logger.error('Error construyendo StructuredTool para %s: %s', herramienta.nombre, exc)
        return None


def build_tools_de_agente(agente, conversacion=None) -> list[StructuredTool]:
    """Carga todas las herramientas activas del agente como StructuredTool."""
    if agente is None:
        return []
    try:
        qs = agente.herramientas.filter(activo=True, status=True)
    except Exception as exc:
        logger.warning('Error cargando herramientas del agente #%s: %s', agente.id, exc)
        return []
    tools = []
    for h in qs:
        tool = build_tool_desde_herramienta(h, conversacion=conversacion)
        if tool is not None:
            tools.append(tool)
    return tools
