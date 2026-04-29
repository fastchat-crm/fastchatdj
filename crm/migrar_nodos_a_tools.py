"""Conversor: nodos del flujo tradicional → HerramientaAgente del agente IA.

El gap que resuelve: el chatbot tradicional pide datos con nodos `pregunta`
(variable_destino + validacion_tipo) y consulta APIs con nodos `http`. El
agente IA ya tiene infraestructura de function-calling vía `HerramientaAgente`,
pero antes no había forma automática de migrarlas. Este módulo cierra esa
brecha: cuando se genera un agente IA desde un departamento, los nodos
relevantes se vuelven tools del agente con schema Pydantic.

Mapping:
- `pregunta` con `variable_destino` → tool de captura (POST a stub que
  echo del valor; la real función es darle al LLM un schema Pydantic
  para que pida el dato naturalmente).
- `http` con `endpoint` → tool tipado de llamada HTTP (URL completa,
  parámetros desde `config.body` o `config.query`, plantilla de respuesta
  desde `config.extraer`).

Idempotente: dos corridas seguidas no duplican tools (UniqueConstraint
`(agente, nombre)` lo respeta).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from django.conf import settings

from crm.models import (
    AgentesIA,
    DepartamentoChatBot,
    HerramientaAgente,
    OpcionDepartamentoChatBot,
)


logger = logging.getLogger(__name__)


# Mapping de validacion_tipo del flujo tradicional → descripción legible
# que el LLM usa para entender qué dato pedir y cómo validarlo.
VALIDACION_TIPO_DESC = {
    'cedula':   'Cédula EC: 10 dígitos numéricos.',
    'ruc':      'RUC EC: 13 dígitos numéricos terminados en 001.',
    'email':    'Email válido (formato user@host.tld).',
    'telefono': 'Teléfono EC: 10 dígitos, empieza con 0.',
    'numero':   'Solo números (puede incluir ceros a la izquierda).',
    'fecha':    'Fecha en formato YYYY-MM-DD.',
    'regex':    'Debe matchear una expresión regular específica.',
    'none':     'Texto libre.',
    '':         'Texto libre.',
}

# Validaciones que conviene mantener como string (vs integer/number) por temas
# de leading zeros, formato, etc. Cualquier validacion_tipo no listado acá
# se mantiene como 'string' por defecto.
TIPO_PARAM_DESDE_VALIDACION = {
    'cedula':   'string',
    'ruc':      'string',
    'email':    'string',
    'telefono': 'string',
    'numero':   'string',  # leading zeros importan en placas/números EC
    'fecha':    'string',
    'regex':    'string',
    'none':     'string',
    '':         'string',
}


def _slug_safe(s: str, fallback: str = 'tool') -> str:
    """Convierte un texto en un slug compatible con `HerramientaAgente.nombre`
    (SlugField, max_length=64). Usado tanto para nombre del tool como para
    derivar identificadores limpios desde nombres de nodos."""
    s = (s or '').strip().lower()
    s = re.sub(r'[^a-z0-9_]+', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    return (s or fallback)[:64]


def _resolver_url_captura() -> str:
    """URL del endpoint stub que captura datos del LLM.
    Apunta al propio Django via URL_GENERAL."""
    base = getattr(settings, 'URL_GENERAL', '').rstrip('/')
    return f'{base}/crm/api/captura_local/'


# ────────────────────────────────────────────────────────────────────────
# Conversor: nodo `pregunta` → tool de captura
# ────────────────────────────────────────────────────────────────────────
def nodo_pregunta_a_tool_data(nodo: OpcionDepartamentoChatBot) -> Optional[dict]:
    """Devuelve un dict listo para `HerramientaAgente(...)` o None si el
    nodo no aplica (no es pregunta o no tiene variable_destino)."""
    if nodo.tipo_nodo != 'pregunta':
        return None
    var = (nodo.variable_destino or '').strip()
    if not var:
        return None

    val_tipo = (nodo.validacion_tipo or 'none').strip()
    val_expr = (nodo.validacion_expresion or '').strip()
    desc_validacion = VALIDACION_TIPO_DESC.get(val_tipo, 'Texto libre.')
    if val_tipo == 'regex' and val_expr:
        desc_validacion = f'Debe matchear la expresión regular: `{val_expr}`'

    cfg = nodo.config or {}
    pregunta_sug = (cfg.get('pregunta') or nodo.respuesta or f'¿Me das el {var}?').strip()

    return {
        'nombre': _slug_safe(f'capturar_{var}'),
        'nombre_amigable': f'Capturar {var}'[:120],
        'descripcion': (
            f'Capturá el dato "{var}" del usuario. {desc_validacion} '
            f'Usá esta herramienta SOLO cuando el usuario aún no haya proporcionado '
            f'este dato y necesites pedírselo de forma natural. La pregunta sugerida '
            f'es: "{pregunta_sug}".'
        ),
        'metodo': 'POST',
        'url': _resolver_url_captura(),
        'headers': {'Content-Type': 'application/json', 'Accept': 'application/json'},
        'parametros': [{
            'nombre': var,
            'tipo': TIPO_PARAM_DESDE_VALIDACION.get(val_tipo, 'string'),
            'requerido': True,
            'descripcion': desc_validacion,
            'pregunta_sugerida': pregunta_sug,
        }],
        'ubicacion_params': 'json',
        'plantilla_respuesta': f'✅ Registrado {var}: {{{{ {var} }}}}',
        'timeout': 5,
        'activo': True,
    }


# ────────────────────────────────────────────────────────────────────────
# Conversor: nodo `http` → tool tipado de llamada HTTP
# ────────────────────────────────────────────────────────────────────────
def _params_desde_dict(d: dict) -> list:
    """Convierte un dict {clave: valor} (donde valor puede ser
    `{{variables.x}}`) en una lista de parámetros para HerramientaAgente.
    Cada clave se vuelve un parámetro string requerido."""
    if not isinstance(d, dict):
        return []
    parametros = []
    for k, v in d.items():
        if not k:
            continue
        # Si el valor es template `{{variables.x}}` extraemos el nombre
        # de la variable como pregunta sugerida implícita.
        ejemplo = ''
        if isinstance(v, str) and not v.startswith('{{'):
            ejemplo = str(v)[:80]
        parametros.append({
            'nombre': _slug_safe(k),
            'tipo': 'string',
            'requerido': True,
            'descripcion': f'Valor para "{k}".' + (f' Ejemplo: {ejemplo}' if ejemplo else ''),
            'pregunta_sugerida': f'¿Cuál es el valor de {k}?',
        })
    return parametros


def nodo_http_a_tool_data(nodo: OpcionDepartamentoChatBot) -> Optional[dict]:
    """Devuelve un dict listo para `HerramientaAgente(...)` desde un nodo
    `http` con endpoint configurado."""
    if nodo.tipo_nodo != 'http' or not nodo.endpoint:
        return None

    cfg = nodo.config or {}
    metodo = (cfg.get('metodo') or 'GET').upper()
    if metodo not in ('GET', 'POST'):
        return None  # HerramientaAgente solo acepta GET/POST

    base = (nodo.endpoint.base_url or '').rstrip('/')
    path = (cfg.get('path') or '').lstrip('/')
    url = f'{base}/{path}' if path else base

    # Parámetros: si POST → desde body; si GET → desde query.
    if metodo == 'POST':
        ubicacion = 'json'
        parametros = _params_desde_dict(cfg.get('body') or {})
    else:
        ubicacion = 'query'
        parametros = _params_desde_dict(cfg.get('query') or {})

    # Plantilla de respuesta: si el nodo extrae variables, se las mostramos
    # al LLM via un texto que enumera lo extraído.
    plantilla = ''
    extraer = cfg.get('extraer') or []
    if extraer:
        lineas = [f'• {ex.get("variable")}: {{{{ {ex.get("variable")} }}}}'
                  for ex in extraer if ex.get('variable')]
        plantilla = 'Resultado:\n' + '\n'.join(lineas)

    nombre_slug = _slug_safe(nodo.nombre or f'http_{nodo.id}')
    return {
        'nombre': nombre_slug,
        'nombre_amigable': (nodo.nombre or 'Llamada HTTP')[:120],
        'descripcion': (
            f'Consulta a la API "{nodo.endpoint.nombre}". '
            f'Endpoint: {metodo} {url}. '
            f'Usá esta herramienta cuando necesités la información que devuelve.'
        ),
        'metodo': metodo,
        'url': url,
        'headers': dict(nodo.endpoint.headers_default or {}),
        'parametros': parametros,
        'ubicacion_params': ubicacion,
        'plantilla_respuesta': plantilla,
        'timeout': min(int(cfg.get('timeout_seg') or nodo.endpoint.timeout_seg or 10), 30),
        'activo': True,
    }


# ────────────────────────────────────────────────────────────────────────
# Orquestador: depto → tools del agente
# ────────────────────────────────────────────────────────────────────────
def migrar_depto_a_tools(agente: AgentesIA, depto: DepartamentoChatBot) -> dict:
    """Recorre los nodos del depto y crea/actualiza HerramientaAgente.
    Idempotente: si ya existe una tool con el mismo nombre para el agente,
    se actualiza en lugar de duplicar.

    Returns: dict {creadas: int, actualizadas: int, omitidas: int, total: int}.
    """
    nodos = OpcionDepartamentoChatBot.objects.filter(
        departamento=depto, status=True,
    ).select_related('endpoint').order_by('orden', 'id')

    tools_data = []
    for nodo in nodos:
        data = nodo_pregunta_a_tool_data(nodo) or nodo_http_a_tool_data(nodo)
        if data:
            tools_data.append(data)

    # Deduplicar por nombre dentro del mismo depto (si dos nodos generan
    # mismo slug, el segundo gana y machaca al primero).
    by_name = {}
    for td in tools_data:
        by_name[td['nombre']] = td

    creadas = 0
    actualizadas = 0
    for nombre, data in by_name.items():
        existente = HerramientaAgente.objects.filter(agente=agente, nombre=nombre).first()
        if existente:
            for k, v in data.items():
                setattr(existente, k, v)
            existente.status = True
            existente.save()
            actualizadas += 1
        else:
            HerramientaAgente.objects.create(agente=agente, **data)
            creadas += 1

    omitidas = nodos.count() - len(tools_data)
    total = creadas + actualizadas
    logger.info(
        'Migración nodos→tools: agente=%s depto=%s creadas=%s actualizadas=%s omitidas=%s',
        agente.id, depto.id, creadas, actualizadas, omitidas,
    )
    return {
        'creadas': creadas,
        'actualizadas': actualizadas,
        'omitidas': omitidas,
        'total': total,
    }
