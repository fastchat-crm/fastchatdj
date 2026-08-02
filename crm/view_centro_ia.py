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

from core.funciones import addData, log, secure_module
from crm.ia_config import (
    CAMPOS_HEREDABLES,
    CAMPOS_SOLO_CENTRO,
    configuracion_de_perfil,
    origen_parametros,
    parametros_efectivos,
    resolver_key_embeddings,
    resolver_key_embeddings_str,
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


def _parametros_para_form(perfil_id):
    """Lista lista para el template: campo, valor efectivo, label y ayuda.

    Los textos salen del propio modelo (`verbose_name` / `help_text`) para no
    duplicarlos en el HTML y que no se desincronicen con el form del agente.
    """
    valores = parametros_efectivos(perfil_id=perfil_id)
    filas = []
    for campo in CAMPOS_HEREDABLES:
        try:
            f = ConfiguracionIA._meta.get_field(campo)
            label, ayuda = f.verbose_name, f.help_text
        except Exception:
            label, ayuda = campo, ''
        filas.append({
            'campo': campo,
            'valor': valores.get(campo),
            'label': label,
            'ayuda': ayuda,
            'es_bool': campo in CAMPOS_BOOL,
            'solo_centro': campo in CAMPOS_SOLO_CENTRO,
        })
    return filas


def _config_editable(perfil):
    """ConfiguracionIA propia del perfil, creándola si hace falta.

    Se crea con todos los campos en NULL: así el perfil hereda de los Parámetros
    IA de la plataforma hasta que el usuario sobreescriba algo. Crearla con
    valores concretos taparía el nivel de plataforma para siempre.
    """
    config, _ = ConfiguracionIA.objects.get_or_create(perfil=perfil)
    return config


def _resumen_keys(perfil):
    """Keys del perfil con las marcas que necesita la UI.

    `puede_embeddings` mira solo el proveedor —sirve para explicar por qué una
    key de Ollama nunca podrá vectorizar—, pero **no alcanza para ofrecerla**:
    una key desactivada por error de cuota o credencial inválida tampoco puede.
    Para eso está `usable_para_vectorizar`, que es lo que filtra el selector.
    """
    keys = list(ApiKeyIA.objects.filter(perfil=perfil, status=True).order_by('proveedor', '-id'))
    embed = resolver_key_embeddings(perfil.id)
    for k in keys:
        k.puede_embeddings = k.proveedor in PROVEEDORES_CON_EMBEDDINGS
        k.usable_para_vectorizar = k.puede_embeddings and k.estado
        k.es_la_de_embeddings = bool(embed and embed.id == k.id)
    return keys, embed


def _resumen_agentes(perfil, solo_activos=False):
    """Agentes del perfil con el detalle de qué parámetros heredan.

    `solo_activos` deja fuera a los que no tienen ninguna API key activa: no
    pueden responder ni vectorizar, así que ofrecerlos en el selector de
    vectorización solo genera un error garantizado. Es el mismo criterio con el
    que el panel de entrenamiento los marca en rojo.
    """
    agentes = list(AgentesIA.objects.filter(perfil=perfil, status=True).order_by('nombre'))
    salida = []
    for a in agentes:
        a.keys_activas = a.apikey.filter(estado=True, status=True).count()
        if solo_activos and not a.keys_activas:
            continue
        origen = origen_parametros(a)
        propios = [c for c, o in origen.items() if o == 'propio']
        a.params_propios = propios
        a.num_propios = len(propios)
        a.hereda_todo = not propios
        salida.append(a)
    return salida


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

    config = _config_editable(perfil)
    keys, embed = _resumen_keys(perfil)

    # El perfil hereda de la plataforma mientras no tenga ningún campo propio.
    hereda_todo = all(
        getattr(config, campo, None) is None
        for campo in CAMPOS_HEREDABLES if campo not in CAMPOS_SOLO_CENTRO or hasattr(config, campo)
    )

    data['perfil'] = perfil
    data['config'] = config
    data['hereda_de_plataforma'] = hereda_todo
    data['parametros'] = _parametros_para_form(perfil.id)
    data['keys'] = keys
    data['key_embeddings'] = embed
    data['agentes'] = _resumen_agentes(perfil)
    # En vectorización solo los que pueden trabajar: sin key activa, reindexar
    # falla siempre.
    data['agentes_vectorizables'] = _resumen_agentes(perfil, solo_activos=True)
    data['agentes_sin_key'] = len(data['agentes']) - len(data['agentes_vectorizables'])
    data['proveedores_con_embeddings'] = PROVEEDORES_CON_EMBEDDINGS

    # Parámetros de plataforma (ParametroSistema): el nivel que aplica cuando ni
    # el agente ni el perfil definen un valor propio. Se muestran junto a los del
    # perfil para que la cascada se vea de un vistazo en vez de en dos pantallas.
    from seguridad.models import ParametroSistema
    data['plataforma_comportamiento'] = list(
        ParametroSistema.objects.filter(status=True, grupo='comportamiento_ia').order_by('orden', 'clave')
    )
    data['plataforma_limites'] = list(
        ParametroSistema.objects.filter(status=True, grupo='limites').order_by('orden', 'clave')
    )
    data['tab'] = request.GET.get('tab') or 'claves'
    return render(request, 'crm/centro_ia/index.html', data)


def _procesar_accion(request, perfil):
    action = request.POST.get('action')
    try:
        if action == 'guardar_parametros':
            return _guardar_parametros(request, perfil)
        if action == 'guardar_plataforma':
            return _guardar_plataforma(request, ('comportamiento_ia',))
        if action == 'guardar_limites':
            return _guardar_plataforma(request, ('limites',))
        if action == 'marcar_embeddings':
            return _marcar_flag(request, perfil, 'usar_para_embeddings')
        if action == 'marcar_default':
            return _marcar_flag(request, perfil, 'es_default')
        if action == 'revectorizar':
            return _revectorizar(request, perfil)
        if action == 'estado_conocimiento':
            return _estado_conocimiento(request, perfil)
        if action == 'explorar_agente':
            return _explorar_agente(request, perfil)
        if action == 'consultar_agente':
            return _consultar_agente(request, perfil)
        if action == 'guardar_key':
            return _guardar_key(request, perfil)
        if action == 'eliminar_key':
            return _eliminar_key(request, perfil)
        if action == 'probar_key':
            return _probar_key(request, perfil)
        if action == 'probar_todas':
            return _probar_todas(request, perfil)
        if action == 'form_key':
            return _form_key(request, perfil)
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


def _guardar_plataforma(request, grupos):
    """Guarda los `ParametroSistema` de los grupos indicados.

    Filtrar por grupo es lo que impide que un POST de la pestaña de parámetros
    toque los topes de gasto, que viven en otra pestaña.
    """
    from .parametros_base import _guardar as guardar_parametros_sistema
    try:
        guardar_parametros_sistema(request, grupos)
    except ValueError as ex:
        return JsonResponse({'error': True, 'message': str(ex)})
    etiqueta = 'Límites de gasto' if 'limites' in grupos else 'Parámetros de la plataforma'
    log(f'Editó {etiqueta} desde el Centro de IA', request, 'change')
    return JsonResponse({'error': False, 'message': f'{etiqueta} guardados.', 'reload': True})


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def _key_del_perfil(request, perfil):
    try:
        pk = int(request.POST.get('pk') or 0)
    except (TypeError, ValueError):
        return None
    return ApiKeyIA.objects.filter(pk=pk, perfil=perfil, status=True).first()


def _form_key(request, perfil):
    """HTML del formulario de alta o edición, renderizado bajo demanda."""
    from django.template.loader import get_template
    from .forms import ApiKeyIAForm

    key = _key_del_perfil(request, perfil) if request.POST.get('pk') else None
    form = ApiKeyIAForm(instance=key, request=request) if key else ApiKeyIAForm(request=request)
    html = get_template('crm/centro_ia/_form_key.html').render(
        {'form': form, 'key': key, 'request': request}, request
    )
    return JsonResponse({'error': False, 'html': html, 'pk': key.id if key else ''})


def _guardar_key(request, perfil):
    from .forms import ApiKeyIAForm

    key = _key_del_perfil(request, perfil) if request.POST.get('pk') else None
    form = ApiKeyIAForm(request.POST, instance=key, request=request) if key \
        else ApiKeyIAForm(request.POST, request=request)

    # El perfil se asigna ANTES de validar: `ApiKeyIA.clean()` lo mira, y el form
    # no expone ese campo. Asignarlo después dejaría la validación mirando una
    # instancia sin dueño.
    form.instance.perfil = perfil

    if not form.is_valid():
        errores = {campo: ' '.join(str(e) for e in lista) for campo, lista in form.errors.items()}
        return JsonResponse({
            'error': True,
            'message': 'Revisá los campos marcados.',
            'form': [errores],
        })

    guardada = form.save()
    log(f'{"Editó" if key else "Registró"} una API key IA: {guardada}',
        request, 'change' if key else 'add', obj=guardada.id)
    return JsonResponse({
        'error': False,
        'message': f'API key {"actualizada" if key else "registrada"}.',
        'reload': True,
    })


def _eliminar_key(request, perfil):
    key = _key_del_perfil(request, perfil)
    if not key:
        return JsonResponse({'error': True, 'message': 'No se encontró la API key.'})
    # Soft-delete: los registros de consumo la siguen referenciando.
    key.status = False
    key.save(request)
    log(f'Eliminó una API key IA: {key}', request, 'delete', obj=key.id)
    return JsonResponse({'error': False, 'message': 'API key eliminada.', 'reload': True})


def _probar_key(request, perfil):
    """Llama de verdad al proveedor con un prompt mínimo.

    Reutiliza `_probar_apikey_simple` del panel de entrenamiento, que ya
    clasifica el fallo (cuota, autenticación, modelo inexistente) y desactiva la
    key con el motivo en vez de dejar un error opaco.
    """
    key = _key_del_perfil(request, perfil)
    if not key:
        return JsonResponse({'error': True, 'message': 'No se encontró la API key.'})

    from .view_mientrenamiento import _probar_apikey_simple
    res = _probar_apikey_simple(key)
    return JsonResponse({
        'error': not res.get('ok'),
        'message': res.get('message') or '',
        'estado': res.get('status'),
        'reload': True,
    })


def _agente_del_perfil(request, perfil):
    try:
        pk = int(request.POST.get('agente_id') or 0)
    except (TypeError, ValueError):
        return None
    return AgentesIA.objects.filter(pk=pk, perfil=perfil, status=True).first()


def _estado_conocimiento(request, perfil):
    """Cuánto conocimiento vectorizado tiene cada agente en Weaviate.

    El tenant es **por agente** (`agente_<id>`), no por perfil, así que hay que
    consultar uno por uno. Cada consulta abre y cierra su cliente, por eso esto
    va bajo demanda y no al pintar la página.
    """
    from agents_ai.rag import weaviate as weaviate_rag

    filas = []
    for agente in AgentesIA.objects.filter(perfil=perfil, status=True).order_by('nombre'):
        try:
            total = weaviate_rag.contar(agente.id)
        except Exception as ex:
            logger.debug('No se pudo contar el tenant del agente %s: %s', agente.id, ex)
            total = None
        filas.append({
            'id': agente.id,
            'nombre': agente.nombre,
            'total': total,
            # None = no se pudo consultar (Weaviate caído); 0 = consultado y vacío.
            'sin_memoria': total == 0,
            'error': total is None,
            'tiene_key': agente.apikey.filter(estado=True, status=True).exists(),
        })

    sin_memoria = [f for f in filas if f['sin_memoria']]
    return JsonResponse({
        'error': False,
        'filas': filas,
        'sin_memoria_ids': [f['id'] for f in sin_memoria],
        'message': (f'{len(sin_memoria)} de {len(filas)} agentes no tienen conocimiento vectorizado.'
                    if sin_memoria else
                    f'Los {len(filas)} agentes tienen conocimiento vectorizado.'),
    })


def _explorar_agente(request, perfil):
    """Qué hay dentro del tenant de un agente, agrupado por fuente."""
    from agents_ai.rag import weaviate as weaviate_rag

    agente = _agente_del_perfil(request, perfil)
    if not agente:
        return JsonResponse({'error': True, 'message': 'No se encontró el agente.'})

    try:
        total = weaviate_rag.contar(agente.id)
        fuentes = weaviate_rag.resumen_fuentes(agente.id)
    except Exception as ex:
        logger.exception('No se pudo explorar el tenant del agente %s', agente.id)
        return JsonResponse({'error': True, 'message': f'No se pudo consultar Weaviate: {ex}'})

    return JsonResponse({
        'error': False,
        'agente': agente.nombre,
        'total': total,
        'fuentes': fuentes,
        'message': (f'{total} fragmento(s) en {len(fuentes)} fuente(s).' if total else
                    'Este agente todavía no tiene conocimiento vectorizado.'),
    })


def _consultar_agente(request, perfil):
    """Corre una búsqueda real contra el conocimiento del agente.

    Sirve para ver **qué recupera** el agente ante una pregunta concreta, que es
    lo que después termina en su prompt: si acá no aparece, el agente tampoco lo
    va a saber.
    """
    from agents_ai.rag import weaviate as weaviate_rag

    agente = _agente_del_perfil(request, perfil)
    if not agente:
        return JsonResponse({'error': True, 'message': 'No se encontró el agente.'})

    pregunta = (request.POST.get('pregunta') or '').strip()
    if not pregunta:
        return JsonResponse({'error': True, 'message': 'Escribí una pregunta para consultar.'})

    api_key = resolver_key_embeddings_str(perfil.id)
    if not api_key:
        return JsonResponse({
            'error': True,
            'message': 'No hay ninguna API key que pueda generar embeddings. '
                       'Marcá una de Gemini u OpenAI en «Claves y tokens».',
        })

    try:
        k = max(1, min(int(request.POST.get('k') or 5), 20))
    except (TypeError, ValueError):
        k = 5

    # Un agente sin tenant devuelve lista vacía igual que uno que sí tiene
    # contenido pero no matchea. Son cosas distintas y la respuesta tiene que
    # decir cuál es: en el primer caso hay que vectorizar, en el segundo no.
    try:
        total = weaviate_rag.contar(agente.id)
    except Exception:
        total = None
    if total == 0:
        return JsonResponse({
            'error': False,
            'agente': agente.nombre,
            'pregunta': pregunta,
            'fragmentos': [],
            'sin_conocimiento': True,
            'message': 'Este agente no tiene nada vectorizado todavía. '
                       'Seleccionalo arriba y pulsá «Vectorizar seleccionados».',
        })

    try:
        resultados = weaviate_rag.buscar(agente.id, api_key, pregunta, k=k)
    except Exception as ex:
        logger.exception('Consulta a Weaviate falló para el agente %s', agente.id)
        return JsonResponse({'error': True, 'message': f'La consulta falló: {ex}'})

    fragmentos = []
    for r in (resultados or []):
        fragmentos.append({
            'texto': (r.get('content') or '')[:1200],
            'source': r.get('source') or '',
            'categoria': r.get('categoria') or '',
            'distancia': r.get('distancia') if r.get('distancia') is not None else r.get('distance'),
        })

    return JsonResponse({
        'error': False,
        'agente': agente.nombre,
        'pregunta': pregunta,
        'fragmentos': fragmentos,
        'message': (f'{len(fragmentos)} fragmento(s) recuperados.' if fragmentos else
                    f'El agente tiene {total} fragmento(s) indexados, pero ninguno responde a esa '
                    f'pregunta. Le falta ese contenido en el entrenamiento.'),
    })


def _probar_todas(request, perfil):
    """Prueba todas las keys del perfil, una por una.

    Cada una se reporta por separado: una que falle no interrumpe al resto, que
    es justo el caso de uso —saber de un vistazo cuáles están caídas—.
    """
    from .view_mientrenamiento import _probar_apikey_simple

    keys = (ApiKeyIA.objects
            .filter(perfil=perfil, status=True)
            .exclude(descripcion='')
            .order_by('proveedor', 'id'))
    if not keys:
        return JsonResponse({'error': True, 'message': 'No hay API keys para probar.'})

    resultados = []
    for key in keys:
        try:
            resultados.append(_probar_apikey_simple(key))
        except Exception as ex:
            logger.exception('Centro de IA: falló la prueba de la key %s', key.id)
            resultados.append({
                'id': key.id,
                'alias': key.alias or key.get_proveedor_display(),
                'proveedor': key.get_proveedor_display(),
                'modelo': key.modelo or '(default)',
                'ok': False, 'status': 'error', 'message': str(ex)[:200],
            })

    ok_count = sum(1 for r in resultados if r.get('ok'))
    fallidas = len(resultados) - ok_count
    return JsonResponse({
        'error': False,
        'message': (f'{ok_count} de {len(resultados)} responden correctamente.'
                    if not fallidas else
                    f'{ok_count} responden, {fallidas} con problemas.'),
        'resultados': resultados,
        'ok_count': ok_count,
        'fail_count': fallidas,
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
        # Una key desactivada (cuota agotada, credencial invalida) falla seguro:
        # mejor cortar acá con el motivo que dejar que reviente por cada agente.
        if not key.estado:
            motivo = (key.msgerror or '').strip()
            return JsonResponse({
                'error': True,
                'message': (f'La key de {key.get_proveedor_display()} está desactivada'
                            + (f': {motivo[:200]}' if motivo else '.')
                            + ' Probala desde «Claves y tokens» antes de vectorizar.'),
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
