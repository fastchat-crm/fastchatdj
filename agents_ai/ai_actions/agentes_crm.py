"""Acciones IA sobre AgentesIA (crear agente).

Puntos de entrada:
  - `generar(descripcion, tono, idioma, apikey_obj, perfil, request)` →
    crea un agente desde una descripción libre, **con LLM**.
  - `crear_desde_depto(request)` → crea un agente snapshot de un
    `DepartamentoChatBot`, **sin LLM**: vuelca el árbol + perfil de empresa
    al `contexto_estatico` y migra nodos `pregunta`/`http` a herramientas
    tipadas (`HerramientaAgente`).

La logica HTTP / extraccion de POST se queda en la view; aca solo vive la
construccion del prompt, llamada al LLM, validacion de placeholders criticos,
y persistencia del AgentesIA + asignacion de la apikey.
"""
import logging

from django.http import JsonResponse

from .base import IAActionError, invocar_json
from .prompts import get_prompt

logger = logging.getLogger(__name__)


# Placeholders criticos que el `prompt_template` generado DEBE incluir,
# si no, se cae al template default.
PLACEHOLDERS_REQUERIDOS = ('{descripcion_agente}', '{question}', '{context}')

# Fallback ultra-conservador si no hay PROMPT_TEMPLATES disponibles.
PROMPT_TEMPLATE_FALLBACK = (
    "Eres un asistente para: {descripcion_agente}\n"
    "{contexto_extra}Cliente: {question}\n====\n{context}\n====\nRespuesta:"
)


def _coerce_str(v, default: str = '') -> str:
    """Coerciona cualquier valor a str (sin lanzar). Util cuando el LLM
    devuelve numeros/null en campos que esperabamos string."""
    if v is None:
        return default
    if isinstance(v, str):
        return v
    try:
        return str(v)
    except Exception:
        return default


def _resolver_template_default() -> str:
    """Plantilla por defecto del sistema (espanol). Se importa lazy para no
    crear ciclos al cargar este modulo."""
    try:
        from core.constantes import PROMPT_TEMPLATES
        return PROMPT_TEMPLATES.get('es') or ''
    except Exception:
        return ''


def generar(*, descripcion: str, tono: str, idioma: str,
            apikey_obj, perfil, request) -> dict:
    """Genera un AgentesIA completo via LLM y lo persiste en DB.

    Args:
        descripcion: descripcion del rol/alcance (>=15 chars).
        tono: 'amigable', 'formal', 'cercano', etc. Default 'amigable'.
        idioma: codigo corto, 'es' por defecto.
        apikey_obj: ApiKeyIA validada (se asigna al agente creado).
        perfil: PerfilNegocioIA padre del agente.
        request: HttpRequest (necesario para `agente.save(request)` que
                 ejecuta el audit del ModeloBase).

    Returns:
        dict con keys: agente_id, nombre, descripcion, prompt_template,
        contexto_estatico, anotar_listas, tokens, modelo.

    Raises:
        IAActionError — input invalido, JSON malformado, LLM error.
    """
    from crm.models import AgentesIA

    descripcion = (descripcion or '').strip()
    tono = (tono or 'amigable').strip()[:60] or 'amigable'
    idioma = (idioma or 'es').strip()[:8] or 'es'

    if len(descripcion) < 15:
        raise IAActionError(
            "Describe con mas detalle que debe hacer el agente (minimo 15 caracteres)."
        )

    prompt = get_prompt(
        'agentes_crm',
        tono=tono,
        idioma=idioma,
        descripcion_usuario=descripcion,
    )

    payload, tokens, modelo = invocar_json(
        prompt,
        apikey_obj=apikey_obj,
        origen='otro',
        prompt_preview=descripcion[:300],
        max_tokens=4000,
        temperature=0.4,
    )

    default_tpl = _resolver_template_default()

    nombre = _coerce_str(payload.get('nombre'), 'Agente generado').strip()[:255] or 'Agente generado'
    descripcion_ag = _coerce_str(payload.get('descripcion'), descripcion).strip()[:4000] or descripcion
    prompt_tpl = _coerce_str(payload.get('prompt_template'), '').strip() or default_tpl
    contexto_est_raw = _coerce_str(payload.get('contexto_estatico'), '').strip()
    contexto_est = contexto_est_raw or None
    anotar = bool(payload.get('anotar_listas'))

    # Validar placeholders criticos — si faltan, usar plantilla default
    if not prompt_tpl or not all(p in prompt_tpl for p in PLACEHOLDERS_REQUERIDOS):
        prompt_tpl = default_tpl
    if not prompt_tpl:
        prompt_tpl = PROMPT_TEMPLATE_FALLBACK

    agente = AgentesIA(
        perfil=perfil,
        nombre=nombre,
        descripcion=descripcion_ag,
        prompt_template=prompt_tpl,
        contexto_estatico=contexto_est,
        anotar_listas=anotar,
    )
    agente.save(request)
    agente.apikey.add(apikey_obj)

    # Provisiona el tenant RAG e indexa el conocimiento inicial (contexto_estatico
    # generado por el LLM). No fatal — el agente queda creado igual.
    try:
        from agents_ai import indexador_conocimiento as _idx
        _idx.provisionar_e_indexar_inicial(agente)
    except Exception as exc:
        logger.warning('Provisión/indexado RAG del agente %s falló: %s', agente.id, exc)

    return {
        'agente_id': agente.id,
        'nombre': agente.nombre,
        'descripcion': agente.descripcion,
        'prompt_template': agente.prompt_template,
        'contexto_estatico': agente.contexto_estatico or '',
        'anotar_listas': agente.anotar_listas,
        'tokens': tokens,
        'modelo': modelo,
    }


# ============================================================================
# Crear agente desde un DepartamentoChatBot existente (operación determinista)
# ============================================================================
def crear_desde_depto(request):
    """Action: `crear_agente_desde_dpto`. Crea un AgentesIA snapshot del
    departamento elegido. SIN llamadas al LLM — vuelca al `contexto_estatico`
    el resumen del depto + perfil de empresa, y migra los nodos del flujo
    (`pregunta`, `http`) a `HerramientaAgente` tipadas via el conversor
    `crm.migrar_nodos_a_tools`.

    Esta función vive aquí (no en `crm/`) por convención del proyecto:
    toda creación de agentes IA pasa por `agents_ai/ai_actions/agentes_crm.py`,
    aunque sea determinista. Los helpers de serialización del depto y el
    conversor de nodos siguen viviendo en `crm/` porque son específicos de
    la app crm y operan sobre sus modelos.
    """
    # Imports perezosos para evitar ciclos crm ↔ agents_ai.
    from crm.models import AgentesIA, ApiKeyIA, DepartamentoChatBot, PerfilNegocioIA
    from crm.funciones_departamento_chatbot import _serializar_dpto_para_agente
    from crm.migrar_nodos_a_tools import migrar_depto_a_tools
    from core.funciones import log

    perfil = PerfilNegocioIA.objects.filter(usuario=request.user).first()
    if not perfil:
        return JsonResponse({
            'error': True,
            'message': 'Configurá tu Perfil de Empresa antes de generar un agente IA.',
        })

    try:
        dpto_id = int(request.POST.get('departamento_id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': True, 'message': 'Departamento inválido.'})

    dpto = DepartamentoChatBot.objects.filter(pk=dpto_id, status=True).first()
    if not dpto:
        return JsonResponse({'error': True, 'message': 'Departamento no encontrado.'})

    apikey_id = request.POST.get('apikey_id') or ''
    apikey_obj = ApiKeyIA.objects.filter(
        pk=apikey_id, perfil=perfil, status=True,
    ).first() if apikey_id else None
    if not apikey_obj:
        return JsonResponse({
            'error': True,
            'message': 'Seleccioná una API Key IA válida (podés crearla en Entrenamiento IA).',
        })

    nombre = (request.POST.get('nombre') or '').strip() or f"Agente · {dpto.nombre}"
    preset = (request.POST.get('personalidad_preset') or 'amable').strip()

    contexto_dpto = _serializar_dpto_para_agente(dpto)
    perfil_txt = perfil.resumen_contexto_ia()
    contexto_full = f"## Empresa\n{perfil_txt}\n\n{contexto_dpto}"

    agente = AgentesIA(
        perfil=perfil,
        nombre=nombre,
        personalidad_preset=preset,
        contexto_estatico=contexto_full,
    )
    agente.save()
    agente.apikey.add(apikey_obj)

    # Provisiona el tenant RAG e indexa el conocimiento inicial: el
    # contexto_estatico volcado desde el departamento + perfil. No fatal.
    try:
        from agents_ai import indexador_conocimiento as _idx
        _idx.provisionar_e_indexar_inicial(agente)
    except Exception as ex:
        logger.warning('Provisión/indexado RAG del agente %s falló: %s', agente.id, ex)

    # Migrar nodos del flujo → HerramientaAgente. Si falla, no rompemos la
    # creación del agente — solo logueamos y devolvemos stats vacíos.
    try:
        stats_tools = migrar_depto_a_tools(agente, dpto)
    except Exception as ex:
        logger.exception(
            'Migración nodos→tools falló para agente=%s dpto=%s: %s',
            agente.id, dpto.id, ex,
        )
        stats_tools = {'creadas': 0, 'actualizadas': 0, 'omitidas': 0, 'total': 0,
                       'error': str(ex)[:200]}

    log(
        f"Generó Agente IA '{agente.nombre}' desde departamento '{dpto.nombre}' "
        f"({stats_tools.get('total', 0)} tools migradas)",
        request, "add", obj=agente.id,
    )
    return JsonResponse({
        'error': False,
        'agente_id': agente.id,
        'agente_nombre': agente.nombre,
        'departamento_nombre': dpto.nombre,
        'tools_migradas': stats_tools,
        'redirect': f'/crm/entrenamiento/?action=procedimiento&id={agente.id}',
        'mensaje': (
            f"Agente '{agente.nombre}' creado desde '{dpto.nombre}'. "
            f"Herramientas IA: {stats_tools.get('total', 0)} migradas "
            f"({stats_tools.get('creadas', 0)} nuevas, "
            f"{stats_tools.get('actualizadas', 0)} actualizadas, "
            f"{stats_tools.get('omitidas', 0)} nodos omitidos)."
        ),
    })
