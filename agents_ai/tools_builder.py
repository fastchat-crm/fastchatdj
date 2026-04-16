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
        # Filtrar el placeholder si se coló
        valores = {k: v for k, v in kwargs.items() if k != '_placeholder' and v is not None}
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
