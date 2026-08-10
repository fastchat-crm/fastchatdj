"""Auditoría de consumo por agente — dónde se va la plata y qué bajar.

El gasto de un agente no está en lo que responde sino en lo que se le manda:
medido en producción, WhatsApp gastó 370.722 tokens de entrada contra 48.584 de
salida. Un factor de 7,6. Optimizar las respuestas es mirar el 12 % del
problema; el 88 % está en el prompt, y el prompt lo arma la configuración.

Este módulo cruza dos cosas que hasta ahora se miraban por separado:

    la configuración efectiva del agente  (crm.ia_config.parametros_efectivos)
    el consumo real medido               (crm.models.ConsumoTokenIA)

y devuelve hallazgos accionables. Cada hallazgo que toca un parámetro trae el
campo, el valor actual, el propuesto y el ahorro estimado, para que la vista
pueda ofrecer un botón de aplicar.

**Por qué el diagnóstico no lo hace un LLM.** Todo lo de acá es aritmética sobre
datos medidos: no hay nada que interpretar y sí mucho que equivocar — un modelo
inventando nombres de campo escribiría configuraciones inválidas, y gastar
tokens para ahorrar tokens es discutible. El LLM entra en un solo lugar donde
gana de verdad: `revisar_texto_prompt()`, que lee las instrucciones escritas a
mano y opina sobre su redacción. Eso sí es criterio, y es opcional.

**Sobre las estimaciones.** No medimos la composición interna del prompt, así
que el ahorro de recortar un tope es un techo, no una promesa. Cada hallazgo
dice de dónde sale su número. Un tope que nadie alcanza no ahorra nada al
bajarlo, y este módulo lo detecta comparando la entrada real contra el
presupuesto configurado en vez de asumir que el prompt siempre se llena.
"""
import logging
from datetime import timedelta

from django.db.models import Avg, Count, Max, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

# Un token ≈ 4 caracteres en español. Sirve para traducir los topes de la
# configuración (que están en caracteres) a tokens comparables con lo medido.
CHARS_POR_TOKEN = 4

# Ventana de análisis por defecto.
DIAS_ANALISIS = 30

# Por debajo de esto no hay muestra suficiente para recomendar nada: dos
# llamadas raras darían un promedio sin sentido.
MIN_LLAMADAS = 5

# Cuánto del presupuesto de prompt hay que estar usando para que recortarlo
# sirva. Con 40 % de saturación el tope no es el que manda el tamaño real y
# bajarlo no cambia la factura.
SATURACION_RELEVANTE = 0.6

# Un pico de entrada este múltiplo por encima de la mediana es una conversación
# que se fue de escala, no el uso normal.
FACTOR_PICO = 3.0

# Orígenes cuya respuesta es una clasificación o una extracción: ahí una salida
# larga es desperdicio, no contenido.
ORIGENES_TAREA_CORTA = ('sentimiento', 'resumidor', 'plantilla')
TOKENS_SALIDA_ESPERADOS_TAREA_CORTA = 400

# Piso del tope de salida propuesto: por debajo de esto cualquier respuesta
# medianamente larga se corta a la mitad, y una respuesta truncada al cliente
# cuesta más que los tokens que ahorra.
MINIMO_TOPE_SALIDA = 512

# Cuánto tiene que superar el tope a la respuesta más larga real para que valga
# la pena mencionarlo.
FACTOR_HOLGURA_SALIDA = 3

SEVERIDADES = ('alta', 'media', 'baja')


def _pct(parte, total):
    return (parte / total * 100) if total else 0.0


def _hallazgo(codigo, severidad, titulo, detalle, **extra):
    base = {
        'codigo': codigo,
        'severidad': severidad,
        'titulo': titulo,
        'detalle': detalle,
        'campo': None,
        'actual': None,
        'propuesto': None,
        'ahorro_mes_usd': 0.0,
        'aplicable': False,
    }
    base.update(extra)
    base['aplicable'] = bool(base['campo'] and base['propuesto'] is not None)
    return base


# ---------------------------------------------------------------------------
# Presupuesto de prompt: cuántos tokens PUEDE llegar a pesar la configuración
# ---------------------------------------------------------------------------

def presupuesto_prompt(agente):
    """Desglose del techo de tokens de entrada que permite la configuración.

    Es lo que el prompt pesaría si todas las piezas se llenaran hasta el tope.
    Comparado contra la entrada real dice dos cosas distintas y las dos
    importan: cuánto del presupuesto se usa (si es poco, recortar no ahorra) y
    qué pieza es la más gorda (dónde conviene recortar si sí se usa).
    """
    from crm.ia_config import parametros_efectivos

    p = parametros_efectivos(agente, getattr(agente, 'perfil_id', None))

    def val(campo, default=0):
        v = p.get(campo)
        return default if v is None else v

    turnos = val('cfg_history_turns')
    historial_chars = turnos * (val('cfg_user_snippet') + val('cfg_ai_snippet'))

    # Las instrucciones y el contexto estático viajan enteros en cada llamada:
    # no dependen de la pregunta ni de lo que recupere el RAG.
    instrucciones_chars = len(agente.prompt_template or '')
    estatico_chars = min(
        len(agente.contexto_estatico or ''),
        val('cfg_max_static_chars') or len(agente.contexto_estatico or ''),
    )

    piezas = [
        {'clave': 'instrucciones', 'etiqueta': 'Instrucciones del agente',
         'chars': instrucciones_chars, 'campo': None,
         'nota': 'Texto fijo escrito a mano. Viaja completo en cada llamada.'},
        {'clave': 'contexto_estatico', 'etiqueta': 'Contexto estático',
         'chars': estatico_chars, 'campo': 'cfg_max_static_chars',
         'nota': 'Recortado por cfg_max_static_chars. También viaja siempre.'},
        {'clave': 'rag', 'etiqueta': 'Conocimiento recuperado (RAG)',
         'chars': val('cfg_max_context_chars'), 'campo': 'cfg_max_context_chars',
         'nota': 'Fragmentos que trae la búsqueda semántica.'},
        {'clave': 'historial', 'etiqueta': 'Historial de la conversación',
         'chars': historial_chars, 'campo': 'cfg_history_turns',
         'nota': f'{turnos} turnos × (usuario {val("cfg_user_snippet")} + '
                 f'IA {val("cfg_ai_snippet")}) caracteres.'},
    ]

    total_chars = sum(x['chars'] for x in piezas)
    for x in piezas:
        x['tokens'] = round(x['chars'] / CHARS_POR_TOKEN)
        x['porcentaje'] = round(_pct(x['chars'], total_chars), 1)
    piezas.sort(key=lambda x: -x['chars'])

    return {
        'piezas': piezas,
        'total_chars': total_chars,
        'total_tokens': round(total_chars / CHARS_POR_TOKEN),
        'parametros': p,
    }


# ---------------------------------------------------------------------------
# Consumo real medido
# ---------------------------------------------------------------------------

def consumo_real(agente, dias=DIAS_ANALISIS):
    """Lo que este agente gastó de verdad en la ventana."""
    from crm.models import ConsumoTokenIA
    from agents_ai.consumo import costo_usd

    desde = timezone.now() - timedelta(days=dias)
    qs = ConsumoTokenIA.objects.filter(agente=agente, fecha__gte=desde)

    agg = qs.aggregate(
        n=Count('id'), ent=Sum('tokens_entrada'), sal=Sum('tokens_salida'),
        ent_prom=Avg('tokens_entrada'), sal_prom=Avg('tokens_salida'),
        ent_max=Max('tokens_entrada'), sal_max=Max('tokens_salida'),
    )
    n = agg['n'] or 0

    # El costo se suma por modelo: un agente puede haber cambiado de modelo en
    # la ventana y cada uno tiene su tarifa.
    costo = 0.0
    por_modelo = []
    for f in qs.values('modelo').annotate(
            n=Count('id'), e=Sum('tokens_entrada'), s=Sum('tokens_salida')).order_by('-e'):
        c = costo_usd(f['modelo'] or '', f['e'] or 0, f['s'] or 0)
        costo += c
        por_modelo.append({'modelo': f['modelo'] or '(sin modelo)', 'llamadas': f['n'],
                           'entrada': f['e'] or 0, 'salida': f['s'] or 0, 'costo': c})

    por_origen = [
        {'origen': f['origen'] or '(sin instrumentar)', 'llamadas': f['n'],
         'entrada': f['e'] or 0, 'salida': f['s'] or 0,
         'sal_prom': round(f['sp'] or 0)}
        for f in qs.values('origen').annotate(
            n=Count('id'), e=Sum('tokens_entrada'), s=Sum('tokens_salida'),
            sp=Avg('tokens_salida')).order_by('-e')
    ]

    return {
        'dias': dias,
        'llamadas': n,
        'entrada': agg['ent'] or 0,
        'salida': agg['sal'] or 0,
        'entrada_promedio': round(agg['ent_prom'] or 0),
        'salida_promedio': round(agg['sal_prom'] or 0),
        'entrada_maxima': agg['ent_max'] or 0,
        'salida_maxima': agg['sal_max'] or 0,
        'costo_usd': costo,
        'costo_mes_usd': costo * (30.0 / dias) if dias else 0.0,
        'por_modelo': por_modelo,
        'por_origen': por_origen,
        'modelo_principal': por_modelo[0]['modelo'] if por_modelo else '',
    }


def _ahorro_por_recorte(modelo, tokens_ahorrados_por_llamada, llamadas_mes):
    """USD/mes que deja de costar quitar N tokens de entrada de cada llamada."""
    from agents_ai.consumo import costo_usd
    if tokens_ahorrados_por_llamada <= 0 or llamadas_mes <= 0:
        return 0.0
    return costo_usd(modelo, int(tokens_ahorrados_por_llamada * llamadas_mes), 0)


# ---------------------------------------------------------------------------
# Reglas
# ---------------------------------------------------------------------------

def auditar_agente(agente, dias=DIAS_ANALISIS):
    """Hallazgos de consumo de un agente, ordenados por ahorro estimado."""
    uso = consumo_real(agente, dias)
    presu = presupuesto_prompt(agente)
    hallazgos = []

    if uso['llamadas'] < MIN_LLAMADAS:
        hallazgos.append(_hallazgo(
            'sin_muestra', 'baja',
            'Sin datos suficientes para recomendar',
            f'Solo {uso["llamadas"]} llamada(s) en {dias} días. Con esa muestra cualquier '
            f'promedio es ruido. El presupuesto de prompt configurado es de '
            f'{presu["total_tokens"]} tokens; se puede revisar igual, pero no hay consumo '
            f'medido contra el cual contrastarlo.'))
        return {'agente': agente, 'uso': uso, 'presupuesto': presu, 'hallazgos': hallazgos}

    llamadas_mes = uso['llamadas'] * (30.0 / dias)
    modelo = uso['modelo_principal']
    saturacion = (uso['entrada_promedio'] * CHARS_POR_TOKEN / presu['total_chars']
                  if presu['total_chars'] else 0)

    _regla_presupuesto_incompleto(hallazgos, uso, presu, saturacion)
    _regla_prompt_inflado(hallazgos, agente, uso, presu, saturacion, modelo, llamadas_mes)
    _regla_pico_de_prompt(hallazgos, uso)
    _regla_salida_larga_en_tarea_corta(hallazgos, uso, modelo, dias)
    _regla_sin_instrumentar(hallazgos, uso)
    _regla_faqs_sin_vectorizar(hallazgos, agente, presu, modelo, llamadas_mes)
    _regla_tope_salida(hallazgos, uso, presu)

    hallazgos.sort(key=lambda h: (-h['ahorro_mes_usd'], SEVERIDADES.index(h['severidad'])))
    return {'agente': agente, 'uso': uso, 'presupuesto': presu,
            'saturacion': round(saturacion * 100, 1), 'hallazgos': hallazgos}


def _regla_prompt_inflado(hallazgos, agente, uso, presu, saturacion, modelo, llamadas_mes):
    """La pieza más gorda del prompt, cuando el presupuesto se está usando.

    La condición de saturación es lo que hace honesta a esta regla: si el prompt
    real pesa la mitad del techo configurado, bajar el techo no quita un solo
    token de la factura.
    """
    if saturacion < SATURACION_RELEVANTE:
        return

    recortables = [x for x in presu['piezas'] if x['campo']]
    if not recortables:
        return
    mayor = recortables[0]
    if mayor['porcentaje'] < 25:
        return

    p = presu['parametros']
    actual = p.get(mayor['campo'])
    if not actual:
        return

    # Se propone un 30 %: suficiente para notarse en la factura, chico para que
    # no cambie el comportamiento del agente de golpe. Que quede corto se ve en
    # la próxima auditoría; que se pase, en las respuestas del cliente.
    propuesto = max(1, int(actual * 0.7))
    if mayor['campo'] == 'cfg_history_turns':
        tokens_menos = ((actual - propuesto) *
                        (p.get('cfg_user_snippet', 0) + p.get('cfg_ai_snippet', 0))) / CHARS_POR_TOKEN
    else:
        tokens_menos = (actual - propuesto) / CHARS_POR_TOKEN

    tokens_menos = min(tokens_menos, uso['entrada_promedio'] * 0.4)
    ahorro = _ahorro_por_recorte(modelo, tokens_menos, llamadas_mes)

    hallazgos.append(_hallazgo(
        'prompt_inflado', 'alta' if ahorro > 1 else 'media',
        f'{mayor["etiqueta"]} es el {mayor["porcentaje"]:.0f}% del prompt',
        f'Cada llamada manda {uso["entrada_promedio"]} tokens de entrada y usa el '
        f'{saturacion * 100:.0f}% del presupuesto configurado ({presu["total_tokens"]} tokens), '
        f'así que el tope sí está mandando el tamaño real. La pieza más pesada es '
        f'"{mayor["etiqueta"]}" con {mayor["tokens"]} tokens. {mayor["nota"]} '
        f'Bajar {mayor["campo"]} de {actual} a {propuesto} quita hasta '
        f'{tokens_menos:.0f} tokens por llamada.',
        campo=mayor['campo'], actual=actual, propuesto=propuesto, ahorro_mes_usd=ahorro))


def _regla_pico_de_prompt(hallazgos, uso):
    """Una llamada muy por encima del promedio es un contexto que se desbocó."""
    prom = uso['entrada_promedio']
    pico = uso['entrada_maxima']
    if not prom or pico < prom * FACTOR_PICO:
        return
    hallazgos.append(_hallazgo(
        'pico_de_prompt', 'media',
        f'Una llamada llegó a {pico:,} tokens de entrada'.replace(',', '.'),
        f'El promedio es {prom} tokens y hubo un pico de {pico}: {pico / prom:.0f} veces más. '
        f'Un salto así no lo produce una pregunta larga sino un contexto que se acumuló sin '
        f'recortarse — típicamente una conversación muy larga o un documento entero entrando '
        f'por RAG. Vale revisar esa conversación antes de tocar ningún tope: si el recorte de '
        f'historial estuviera funcionando, el pico no existiría.'))


def _regla_salida_larga_en_tarea_corta(hallazgos, uso, modelo, dias):
    """Clasificar no debería costar más que el texto clasificado.

    Cuando pasa, casi siempre es pensamiento extendido: los modelos de
    razonamiento lo facturan como salida aunque no aparezca en la respuesta.
    """
    from agents_ai.consumo import costo_usd
    for o in uso['por_origen']:
        if o['origen'] not in ORIGENES_TAREA_CORTA:
            continue
        if o['sal_prom'] <= TOKENS_SALIDA_ESPERADOS_TAREA_CORTA:
            continue
        exceso = (o['sal_prom'] - TOKENS_SALIDA_ESPERADOS_TAREA_CORTA) * o['llamadas']
        ahorro = costo_usd(modelo, 0, int(exceso)) * (30.0 / dias)
        hallazgos.append(_hallazgo(
            'razonamiento_facturado', 'alta' if ahorro > 0.5 else 'media',
            f'"{o["origen"]}" devuelve {o["sal_prom"]} tokens para una tarea de clasificación',
            f'{o["llamadas"]} llamadas con {o["sal_prom"]} tokens de salida promedio, cuando la '
            f'respuesta esperada entra en {TOKENS_SALIDA_ESPERADOS_TAREA_CORTA}. La diferencia es '
            f'pensamiento extendido del modelo, que se factura como salida aunque el usuario no '
            f'lo vea. Se apaga con razonamiento=False al construir el LLM '
            f'(agents_ai/providers/): medido en Gemini 2.5 Flash, la misma clasificación pasó de '
            f'180 a 18 tokens de salida con idéntica respuesta.',
            ahorro_mes_usd=ahorro))


def _regla_sin_instrumentar(hallazgos, uso):
    """Consumo que no se puede atribuir es consumo que no se puede optimizar."""
    for o in uso['por_origen']:
        if o['origen'] != '(sin instrumentar)':
            continue
        parte = _pct(o['entrada'] + o['salida'], uso['entrada'] + uso['salida'])
        if parte < 10:
            continue
        hallazgos.append(_hallazgo(
            'sin_instrumentar', 'media',
            f'El {parte:.0f}% del consumo no dice de dónde salió',
            f'{o["llamadas"]} llamadas quedaron sin `origen`, así que no se sabe si fueron '
            f'mensajes de WhatsApp, pruebas del panel o un cron. Hasta que se instrumenten, '
            f'ese gasto no se puede atribuir ni recortar: el que registra el consumo tiene que '
            f'pasar `origen=` en `_registrar_consumo`.'))


def _regla_faqs_sin_vectorizar(hallazgos, agente, presu, modelo, llamadas_mes):
    """FAQs metidas a mano en cada prompt cuando debería recuperarlas el RAG."""
    faqs = presu['parametros'].get('faqs_en_prompt') or 0
    if faqs <= 0:
        return
    try:
        from agents_ai.rag import weaviate as wv
        fragmentos = wv.contar(agente.id)
    except Exception:
        return
    if fragmentos:
        return
    hallazgos.append(_hallazgo(
        'faqs_sin_vectorizar', 'media',
        f'Mete {faqs} FAQs en cada prompt y no tiene conocimiento vectorizado',
        f'Sin vectorizar, las FAQs viajan enteras en todas las llamadas en vez de recuperarse '
        f'solo las que hacen falta. Vectorizar el conocimiento del agente (pestaña '
        f'Vectorización) hace que el RAG traiga los fragmentos pertinentes y permite bajar '
        f'faqs_en_prompt. Es la única recomendación de esta lista que primero mejora la '
        f'respuesta y de paso abarata.'))


def _regla_tope_salida(hallazgos, uso, presu):
    """Un tope de salida muy por encima de lo real es un freno, no un ahorro.

    El propuesto se calcula sobre la respuesta MÁS LARGA observada, nunca sobre
    el promedio: un agente que responde 34 tokens de media pero 900 en su caso
    más largo quedaría con el tope en 102 y truncaría la respuesta larga. El
    promedio no dice nada sobre el peor caso legítimo.
    """
    tope = presu['parametros'].get('cfg_max_output_tokens') or 0
    prom = uso['salida_promedio']
    techo_real = uso['salida_maxima']
    if not tope or not prom or not techo_real:
        return

    # Solo vale avisar cuando la holgura es grande. Proponer 3500 → 3223 es
    # ruido: no acota nada y entrena al usuario a ignorar la lista.
    if tope < techo_real * FACTOR_HOLGURA_SALIDA:
        return
    propuesto = max(int(techo_real * 1.5), MINIMO_TOPE_SALIDA)
    if propuesto >= tope:
        return

    hallazgos.append(_hallazgo(
        'tope_salida_holgado', 'baja',
        f'El tope de salida ({tope}) es {tope / techo_real:.0f} veces la respuesta más larga ({techo_real})',
        f'Bajarlo no ahorra por sí solo — se paga lo que el modelo genera, no el tope. Lo que '
        f'sí hace es acotar el peor caso: hoy una sola llamada puede generar {tope} tokens. '
        f'La respuesta más larga que dio este agente fue de {techo_real} tokens (promedio '
        f'{prom}), así que {propuesto} deja 50% de margen sobre el máximo real sin truncar nada '
        f'de lo que hoy responde.',
        campo='cfg_max_output_tokens', actual=tope, propuesto=propuesto))


def _regla_presupuesto_incompleto(hallazgos, uso, presu, saturacion):
    """El prompt real pesa más que todos los topes configurados sumados.

    No es un error de medición: significa que algo entra al prompt sin pasar por
    ningún tope de la cascada — herramientas, FAQs, la pregunta del usuario, un
    bloque agregado en código. Mientras eso siga afuera del presupuesto, ajustar
    los topes toca solo una parte del gasto.
    """
    if saturacion <= 1.05:
        return
    exceso = uso['entrada_promedio'] - presu['total_tokens']
    hallazgos.append(_hallazgo(
        'presupuesto_incompleto', 'media',
        f'{exceso} tokens por llamada no los explica ningún tope',
        f'El prompt real pesa {uso["entrada_promedio"]} tokens y la suma de todo lo que la '
        f'configuración limita da {presu["total_tokens"]}. Los {exceso} de diferencia entran '
        f'por fuera de la cascada: herramientas declaradas, FAQs, la pregunta del usuario o '
        f'algún bloque agregado en código. Es la porción del gasto que hoy no se puede recortar '
        f'desde el panel, y conviene identificarla antes de apretar los topes que sí existen '
        f'— apretarlos de más degradaría al agente sin tocar esta parte.'))


# ---------------------------------------------------------------------------
# Auditoría de todos los agentes de un perfil
# ---------------------------------------------------------------------------

def auditar_perfil(perfil, dias=DIAS_ANALISIS):
    """Auditoría de cada agente activo del perfil, del que más gasta al que menos."""
    from crm.models import AgentesIA

    informes = []
    for agente in AgentesIA.objects.filter(status=True, perfil=perfil).order_by('nombre'):
        try:
            informes.append(auditar_agente(agente, dias))
        except Exception:
            logger.exception('No se pudo auditar el agente %s', agente.id)
    informes.sort(key=lambda i: -i['uso']['costo_usd'])

    return {
        'dias': dias,
        'informes': informes,
        'costo_usd': sum(i['uso']['costo_usd'] for i in informes),
        'costo_mes_usd': sum(i['uso']['costo_mes_usd'] for i in informes),
        'ahorro_mes_usd': sum(h['ahorro_mes_usd']
                              for i in informes for h in i['hallazgos']),
        'hallazgos': sum(len(i['hallazgos']) for i in informes),
    }


# ---------------------------------------------------------------------------
# Aplicar una recomendación
# ---------------------------------------------------------------------------

def aplicar_recomendacion(agente, campo, valor, request=None):
    """Escribe un parámetro recomendado en el agente.

    Solo acepta campos de la cascada y solo los que el agente tiene como columna
    propia: `cfg_umbral_distancia` y `cfg_max_static_amplia` viven únicamente en
    el Centro de IA (ver CAMPOS_SOLO_CENTRO) y escribirlos acá sería inventar un
    atributo que nadie lee.

    Escribir en el agente es deliberado: fija el valor para ESE agente sin tocar
    a los demás. Los que heredan siguen heredando.
    """
    from crm.ia_config import CAMPOS_HEREDABLES, CAMPOS_SOLO_CENTRO

    if campo not in CAMPOS_HEREDABLES or campo in CAMPOS_SOLO_CENTRO:
        raise ValueError(f'El parámetro "{campo}" no se puede ajustar desde la auditoría.')
    if not hasattr(agente, campo):
        raise ValueError(f'El agente no tiene el parámetro "{campo}".')

    anterior = getattr(agente, campo)
    if isinstance(anterior, bool) or campo == 'memoria_rag_activa':
        nuevo = str(valor).lower() in ('1', 'true', 'on', 'sí', 'si')
    else:
        nuevo = int(valor)
        if nuevo < 1:
            raise ValueError('El valor tiene que ser mayor que cero.')

    setattr(agente, campo, nuevo)
    agente.save(request) if request else agente.save()
    logger.info('Optimizador: agente=%s %s %s → %s', agente.id, campo, anterior, nuevo)
    return {'campo': campo, 'anterior': anterior, 'nuevo': nuevo}


# ---------------------------------------------------------------------------
# La parte donde un LLM sí aporta: leer las instrucciones escritas a mano
# ---------------------------------------------------------------------------

def revisar_texto_prompt(agente, apikey_obj=None):
    """Le pide a un LLM que señale bloque repetido o sobrante en las instrucciones.

    Esto no lo puede hacer una regla: requiere leer y entender un texto. Y a
    diferencia del resto del módulo, cuesta tokens — por eso es una acción
    aparte y no parte de la auditoría automática.

    Se pide una lista corta y concreta, no una reescritura: la reescritura
    automática de un prompt en producción cambia el comportamiento del agente
    frente a los clientes sin que nadie lo haya leído.
    """
    from crm.models import ApiKeyIA
    from agents_ai.providers import get_provider

    texto = (agente.prompt_template or '').strip()
    if len(texto) < 400:
        return {'ok': True, 'sugerencias': [],
                'mensaje': 'Las instrucciones son cortas: no hay nada que recortar.'}

    key = apikey_obj or agente.apikey.filter(estado=True, status=True).first()
    if not key:
        return {'ok': False, 'mensaje': 'El agente no tiene una API key activa para revisar el texto.'}

    prov = get_provider(key.proveedor)
    llm = prov.get_llm(
        apikey=key.descripcion,
        model_name=(key.modelo or '').strip() or prov.default_model(),
        max_output_tokens=800, temperature=0.1,
        base_url=(key.base_url or '').strip() or None,
        razonamiento=False,
    )

    prompt = (
        'Sos un revisor de prompts. Abajo están las instrucciones de un asistente de '
        'WhatsApp que se envían en CADA mensaje, así que cada palabra se paga.\n\n'
        'Listá como máximo 5 recortes concretos: instrucciones repetidas, ejemplos de más, '
        'reglas que el modelo ya cumple sin que se lo pidan, o texto decorativo. Citá el '
        'fragmento exacto. Si el prompt ya está ajustado, decilo y no inventes recortes.\n\n'
        'No reescribas el prompt. Respondé en español, una sugerencia por línea, sin numerar.\n\n'
        f'--- INSTRUCCIONES ({len(texto)} caracteres) ---\n{texto}'
    )

    resp = llm.invoke(prompt)
    entrada, salida = prov.extract_tokens(resp)
    sugerencias = [l.strip(' -•\t') for l in (resp.content or '').splitlines() if l.strip()]

    return {
        'ok': True,
        'sugerencias': sugerencias[:5],
        'chars_prompt': len(texto),
        'tokens_usados': entrada + salida,
    }
