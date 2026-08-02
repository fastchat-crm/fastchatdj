"""Centro de IA — resolución de keys y parámetros.

Punto único de verdad para dos preguntas que antes se respondían con código
duplicado en cinco archivos:

    1. ¿Con qué API key se vectoriza el conocimiento de este perfil?
    2. ¿Qué valor tiene realmente el parámetro X para este agente?

Ambas siguen la misma cascada de tres niveles:

    agente (valor propio)  →  perfil (ConfiguracionIA)  →  plataforma

Nadie debe leer `agente.cfg_*` ni filtrar `ApiKeyIA` por `proveedor=2` a mano:
usar `parametros_efectivos()` y `resolver_key_embeddings()`.
"""
import logging

logger = logging.getLogger(__name__)

# Campos que participan de la cascada de herencia agente → perfil → plataforma.
CAMPOS_HEREDABLES = (
    'faqs_en_prompt',
    'cfg_faiss_k',
    'cfg_faiss_fetch_k',
    'cfg_max_context_chars',
    'cfg_max_static_chars',
    'cfg_history_turns',
    'cfg_user_snippet',
    'cfg_ai_snippet',
    'cfg_max_output_tokens',
    'cfg_topic_anchor_chars',
    'cfg_umbral_distancia',
    'cfg_max_static_amplia',
    'memoria_rag_activa',
)

# Campos que el agente no tiene como columna propia: sólo existen en el centro.
CAMPOS_SOLO_CENTRO = ('cfg_umbral_distancia', 'cfg_max_static_amplia')


# ---------------------------------------------------------------------------
# Configuración (parámetros generales)
# ---------------------------------------------------------------------------

def configuracion_de_perfil(perfil_id):
    """`ConfiguracionIA` del perfil, o la fila global de plataforma si no tiene.

    Devuelve None si no existe ninguna de las dos — en ese caso la cascada cae
    a `PARAMETROS_IA_DEFAULT`.
    """
    from crm.models import ConfiguracionIA
    try:
        if perfil_id:
            propia = ConfiguracionIA.objects.filter(perfil_id=perfil_id, status=True).first()
            if propia:
                return propia
        return ConfiguracionIA.objects.filter(perfil__isnull=True, status=True).first()
    except Exception as exc:
        logger.debug('No se pudo leer ConfiguracionIA: %s', exc)
        return None


def parametros_efectivos(agente=None, perfil_id=None):
    """Valores reales de los parámetros IA aplicando la cascada completa.

    `agente` es un `AgentesIA` (o None para obtener sólo los del perfil).
    Un campo del agente en NULL significa "heredar", no "cero".
    """
    from crm.models import PARAMETROS_IA_DEFAULT

    if perfil_id is None and agente is not None:
        perfil_id = getattr(agente, 'perfil_id', None)

    config = configuracion_de_perfil(perfil_id)

    valores = {}
    for campo in CAMPOS_HEREDABLES:
        valor = None

        # Nivel 1 — valor propio del agente (los CAMPOS_SOLO_CENTRO no existen ahí)
        if agente is not None and campo not in CAMPOS_SOLO_CENTRO:
            valor = getattr(agente, campo, None)

        # Nivel 2 — configuración del perfil o de la plataforma
        if valor is None and config is not None:
            valor = getattr(config, campo, None)

        # Nivel 3 — parámetro global editable en /crm/parametros-ia/
        # (ParametroSistema), con el default de código como último recurso.
        if valor is None:
            valor = _valor_plataforma(campo)

        valores[campo] = valor

    return valores


def _valor_plataforma(campo):
    """Valor a nivel plataforma de un parámetro IA.

    Primero la tabla editable en runtime `ParametroSistema` (página
    `/crm/parametros-ia/`, cacheada 60 s); como último recurso, el default de
    código en `PARAMETROS_IA_DEFAULT`. Así un agente que no sobreescribe un
    campo — y cuyo perfil tampoco — toma el valor de los Parámetros IA.
    """
    from crm.models import PARAMETROS_IA_DEFAULT
    default_codigo = PARAMETROS_IA_DEFAULT.get(campo)
    try:
        from seguridad.models import ParametroSistema
        return ParametroSistema.valor_de(campo, default_codigo)
    except Exception as exc:
        logger.debug('ParametroSistema no disponible para %s: %s', campo, exc)
        return default_codigo


def parametro(nombre, agente=None, perfil_id=None):
    """Un solo parámetro resuelto. Atajo de `parametros_efectivos()`."""
    return parametros_efectivos(agente=agente, perfil_id=perfil_id).get(nombre)


def origen_parametros(agente):
    """Para la UI: por cada campo, si el agente lo hereda o lo sobreescribe.

    Devuelve `{campo: 'propio'|'heredado'}`.
    """
    origenes = {}
    for campo in CAMPOS_HEREDABLES:
        if campo in CAMPOS_SOLO_CENTRO:
            origenes[campo] = 'heredado'
            continue
        origenes[campo] = 'propio' if getattr(agente, campo, None) is not None else 'heredado'
    return origenes


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def _keys_activas(perfil_id):
    from crm.models import ApiKeyIA
    return ApiKeyIA.objects.filter(perfil_id=perfil_id, estado=True, status=True)


def resolver_key_embeddings(perfil_id):
    """API key con la que se vectoriza el conocimiento del perfil.

    Orden de preferencia:
        1. Key del perfil marcada `usar_para_embeddings`.
        2. Key del perfil marcada `es_default` de un proveedor con embeddings.
        3. Cualquier key activa del perfil de un proveedor con embeddings
           (comportamiento histórico: la más reciente).
        4. Key global de la plataforma marcada `usar_para_embeddings`.

    Devuelve el objeto `ApiKeyIA` o None. Para el string suelto que esperan los
    módulos viejos, usar `resolver_key_embeddings_str()`.
    """
    from crm.models import ApiKeyIA, PROVEEDORES_CON_EMBEDDINGS
    try:
        activas = _keys_activas(perfil_id)

        elegida = activas.filter(usar_para_embeddings=True).first()
        if elegida:
            return elegida

        elegida = activas.filter(
            es_default=True, proveedor__in=PROVEEDORES_CON_EMBEDDINGS
        ).first()
        if elegida:
            return elegida

        elegida = activas.filter(
            proveedor__in=PROVEEDORES_CON_EMBEDDINGS
        ).order_by('-id').first()
        if elegida:
            return elegida

        return (ApiKeyIA.objects
                .filter(es_global=True, estado=True, status=True,
                        proveedor__in=PROVEEDORES_CON_EMBEDDINGS)
                .order_by('-usar_para_embeddings', '-id')
                .first())
    except Exception as exc:
        logger.debug('No se pudo resolver la key de embeddings: %s', exc)
        return None


def resolver_key_embeddings_str(perfil_id):
    """La API key de embeddings como string, o '' si no hay ninguna."""
    key = resolver_key_embeddings(perfil_id)
    return key.descripcion if key else ''


def resolver_key_default(perfil_id, proveedor=None):
    """Key por defecto del perfil, opcionalmente acotada a un proveedor.

    Cae a la key global de la plataforma si el perfil no tiene ninguna propia.
    """
    from crm.models import ApiKeyIA
    try:
        activas = _keys_activas(perfil_id)
        if proveedor is not None:
            activas = activas.filter(proveedor=proveedor)

        elegida = activas.filter(es_default=True).first()
        if elegida:
            return elegida

        elegida = activas.order_by('-id').first()
        if elegida:
            return elegida

        globales = ApiKeyIA.objects.filter(es_global=True, estado=True, status=True)
        if proveedor is not None:
            globales = globales.filter(proveedor=proveedor)
        return globales.order_by('-es_default', '-id').first()
    except Exception as exc:
        logger.debug('No se pudo resolver la key por defecto: %s', exc)
        return None
