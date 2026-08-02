"""Centro de IA — administración centralizada de keys y parámetros.

Reemplaza el ir y venir por el panel de cada agente: acá se define, una sola
vez y para todo el perfil, qué API key vectoriza, cuál es la key por defecto de
cada proveedor y qué valores toman los parámetros de comportamiento que antes
había que repetir agente por agente.

La resolución de la cascada (agente → perfil → plataforma → default de código)
vive en `crm/ia_config.py`; esta vista solo la muestra y la edita.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, secure_module
from crm.ia_config import (
    CAMPOS_HEREDABLES,
    CAMPOS_SOLO_CENTRO,
    configuracion_de_perfil,
    origen_parametros,
    parametros_efectivos,
    resolver_key_embeddings,
)
from crm.models import (
    PROVEEDORES_CON_EMBEDDINGS,
    AgentesIA,
    ApiKeyIA,
    ConfiguracionIA,
    PerfilNegocioIA,
)

logger = logging.getLogger(__name__)

# Rangos aceptados al guardar los parámetros generales. Mismos límites que el
# form del agente (`crm/forms.py:_CFG_RANGES`) para que no se contradigan.
RANGOS = {
    'faqs_en_prompt':         (0, 50),
    'cfg_faiss_k':            (1, 20),
    'cfg_faiss_fetch_k':      (5, 80),
    'cfg_max_context_chars':  (500, 16000),
    'cfg_max_static_chars':   (500, 10000),
    'cfg_history_turns':      (1, 30),
    'cfg_user_snippet':       (50, 1500),
    'cfg_ai_snippet':         (50, 4000),
    'cfg_max_output_tokens':  (200, 8000),
    'cfg_topic_anchor_chars': (50, 800),
    'cfg_max_static_amplia':  (4000, 20000),
}
RANGOS_FLOAT = {
    'cfg_umbral_distancia': (0.5, 3.0),
}
CAMPOS_BOOL = ('memoria_rag_activa',)


def _etiquetas_parametros():
    """Label + help_text de cada parámetro, leídos del propio modelo para no
    duplicar los textos en el template."""
    etiquetas = {}
    for campo in CAMPOS_HEREDABLES:
        try:
            f = ConfiguracionIA._meta.get_field(campo)
            etiquetas[campo] = {'label': f.verbose_name, 'ayuda': f.help_text}
        except Exception:
            etiquetas[campo] = {'label': campo, 'ayuda': ''}
    return etiquetas


def _config_editable(perfil):
    """ConfiguracionIA propia del perfil, creándola si hace falta.

    `configuracion_de_perfil` puede devolver la fila global de plataforma, que
    NO hay que editar desde acá: tocarla cambiaría los defaults de todos los
    perfiles. Para guardar siempre se usa la del perfil.
    """
    config, _ = ConfiguracionIA.objects.get_or_create(perfil=perfil)
    return config


def _resumen_keys(perfil):
    keys = list(ApiKeyIA.objects.filter(perfil=perfil, status=True).order_by('proveedor', '-id'))
    embed = resolver_key_embeddings(perfil.id)
    for k in keys:
        k.puede_embeddings = k.proveedor in PROVEEDORES_CON_EMBEDDINGS
        k.es_la_de_embeddings = bool(embed and embed.id == k.id)
    return keys, embed


def _resumen_agentes(perfil):
    agentes = list(AgentesIA.objects.filter(perfil=perfil, status=True).order_by('nombre'))
    for a in agentes:
        origen = origen_parametros(a)
        propios = [c for c, o in origen.items() if o == 'propio']
        a.params_propios = propios
        a.num_propios = len(propios)
        a.hereda_todo = not propios
    return agentes


@login_required
@secure_module
def centro_ia_view(request):
    data = {
        'titulo': 'Centro de IA',
        'descripcion': 'Keys, parámetros generales y vectorización de los agentes',
        'ruta': request.path,
    }
    addData(request, data)

    perfil, _ = PerfilNegocioIA.objects.get_or_create(usuario=request.user)

    if request.method == 'POST':
        return _procesar_accion(request, perfil)

    config_efectiva = configuracion_de_perfil(perfil.id)
    keys, embed = _resumen_keys(perfil)

    data['perfil'] = perfil
    data['config'] = _config_editable(perfil)
    data['hereda_de_plataforma'] = bool(config_efectiva and not config_efectiva.perfil_id)
    data['parametros'] = parametros_efectivos(perfil_id=perfil.id)
    data['etiquetas'] = _etiquetas_parametros()
    data['campos_bool'] = CAMPOS_BOOL
    data['campos_solo_centro'] = CAMPOS_SOLO_CENTRO
    data['keys'] = keys
    data['key_embeddings'] = embed
    data['agentes'] = _resumen_agentes(perfil)
    data['proveedores_con_embeddings'] = PROVEEDORES_CON_EMBEDDINGS
    return render(request, 'crm/centro_ia/index.html', data)


def _procesar_accion(request, perfil):
    action = request.POST.get('action')
    try:
        if action == 'guardar_parametros':
            return _guardar_parametros(request, perfil)
        if action == 'marcar_embeddings':
            return _marcar_flag(request, perfil, 'usar_para_embeddings')
        if action == 'marcar_default':
            return _marcar_flag(request, perfil, 'es_default')
        if action == 'revectorizar':
            return _revectorizar(request, perfil)
    except Exception as ex:
        logger.exception('Centro de IA: la acción "%s" falló', action)
        return JsonResponse({'error': True, 'message': f'Error al procesar la solicitud: {ex}'})

    return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})


def _guardar_parametros(request, perfil):
    config = _config_editable(perfil)
    errores = {}
    cambios = []

    for campo in CAMPOS_HEREDABLES:
        if campo in CAMPOS_BOOL:
            setattr(config, campo, request.POST.get(campo) in ('on', 'true', '1', 'True'))
            cambios.append(campo)
            continue

        crudo = (request.POST.get(campo) or '').strip()
        if crudo == '':
            continue

        if campo in RANGOS_FLOAT:
            lo, hi = RANGOS_FLOAT[campo]
            try:
                valor = float(crudo.replace(',', '.'))
            except ValueError:
                errores[campo] = 'Debe ser un número.'
                continue
            if not (lo <= valor <= hi):
                errores[campo] = f'Rango permitido: {lo} a {hi}.'
                continue
        else:
            lo, hi = RANGOS.get(campo, (0, 10 ** 9))
            try:
                valor = int(crudo)
            except ValueError:
                errores[campo] = 'Debe ser un número entero.'
                continue
            if not (lo <= valor <= hi):
                errores[campo] = f'Rango permitido: {lo} a {hi}.'
                continue

        setattr(config, campo, valor)
        cambios.append(campo)

    if errores:
        return JsonResponse({
            'error': True,
            'message': 'Revisa los valores marcados.',
            'form': [errores],
        })

    config.save(request)
    return JsonResponse({
        'error': False,
        'message': 'Parámetros generales guardados. Los agentes que heredan ya usan estos valores.',
        'reload': True,
    })


def _marcar_flag(request, perfil, campo):
    """Marca `usar_para_embeddings` o `es_default` en una key del perfil.

    El modelo desmarca sola a las hermanas del mismo ámbito, así que acá no hay
    que limpiar nada a mano.
    """
    try:
        pk = int(request.POST.get('pk') or 0)
    except (TypeError, ValueError):
        pk = 0
    key = ApiKeyIA.objects.filter(pk=pk, perfil=perfil, status=True).first()
    if not key:
        return JsonResponse({'error': True, 'message': 'No se encontró la API key.'})

    if campo == 'usar_para_embeddings' and key.proveedor not in PROVEEDORES_CON_EMBEDDINGS:
        return JsonResponse({
            'error': True,
            'message': f'{key.get_proveedor_display()} no ofrece un modelo de embeddings. '
                       f'Elegí una key de Gemini u OpenAI para vectorizar.',
        })

    setattr(key, campo, True)
    key.save(request)

    if campo == 'usar_para_embeddings':
        mensaje = f'Ahora se vectoriza con {key.get_proveedor_display()}.'
    else:
        mensaje = f'{key.get_proveedor_display()} quedó como key por defecto.'
    return JsonResponse({'error': False, 'message': mensaje, 'reload': True})


def _revectorizar(request, perfil):
    """Reindexa el conocimiento de los agentes elegidos con una key concreta.

    Cada agente se reporta por separado: uno que falle no cancela los demás.
    """
    from agents_ai.indexador_conocimiento import reindexar_agente

    ids = [int(x) for x in request.POST.getlist('agentes[]') if str(x).isdigit()]
    if not ids:
        return JsonResponse({'error': True, 'message': 'Elegí al menos un agente para vectorizar.'})

    api_key = ''
    key_id = (request.POST.get('apikey_id') or '').strip()
    if key_id.isdigit():
        key = ApiKeyIA.objects.filter(pk=int(key_id), perfil=perfil, status=True).first()
        if not key:
            return JsonResponse({'error': True, 'message': 'No se encontró la API key elegida.'})
        if key.proveedor not in PROVEEDORES_CON_EMBEDDINGS:
            return JsonResponse({
                'error': True,
                'message': f'{key.get_proveedor_display()} no ofrece embeddings. Elegí una key de Gemini u OpenAI.',
            })
        api_key = key.descripcion
    elif not resolver_key_embeddings(perfil.id):
        return JsonResponse({
            'error': True,
            'message': 'Este perfil no tiene ninguna API key que pueda vectorizar. '
                       'Marcá una key de Gemini u OpenAI como "Usar para vectorizar".',
        })

    agentes = AgentesIA.objects.filter(id__in=ids, perfil=perfil, status=True).order_by('nombre')
    resultados = []
    for agente in agentes:
        try:
            res = reindexar_agente(agente, api_key=api_key)
        except Exception as ex:
            logger.exception('Centro de IA: falló la revectorización del agente %s', agente.id)
            res = {'ok': False, 'error': str(ex)}
        resultados.append({
            'agente': agente.nombre,
            'ok': bool(res.get('ok')),
            'indexados': res.get('indexados', 0),
            'total': res.get('total_tenant', 0),
            'mensaje': res.get('aviso') or res.get('error') or '',
        })

    exitosos = sum(1 for r in resultados if r['ok'])
    fallidos = len(resultados) - exitosos
    if fallidos:
        mensaje = f'{exitosos} agente(s) vectorizado(s), {fallidos} con problemas.'
    else:
        mensaje = f'{exitosos} agente(s) vectorizado(s) correctamente.'

    return JsonResponse({'error': False, 'message': mensaje, 'resultados': resultados})
