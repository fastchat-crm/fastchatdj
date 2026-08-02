"""Banco de pruebas de agentes IA — corre conversaciones reales y mide.

Por cada agente activo levanta una conversación de varios turnos contra su
proveedor real y mide, turno a turno: latencia, tokens, costo, si recuperó
conocimiento del RAG y si la respuesta parece una alucinación. Al final verifica
que el agente **recuerde** lo dicho al principio.

    python manage.py shell < scripts/probar_agentes.py

**Gasta tokens reales.** Los turnos por agente y el filtro están al principio
para poder acotarlo.

Qué mide y por qué:

- **latencia** — un agente por encima de ~8 s en WhatsApp se siente roto, y en
  Gemini es el preludio del `504 DEADLINE_EXCEEDED`.
- **tokens y costo** — se agrega por modelo, no sobre el total: cada modelo
  tiene su tarifa.
- **usó RAG** — si el agente tiene conocimiento vectorizado pero no lo recupera,
  está respondiendo de memoria general: el entrenamiento no le sirve de nada.
- **alucinación** — se reusa el detector del auditor (`_detectar_respuestas_problema`),
  que marca rechazos, respuestas vacías y estilo enciclopedia.
- **memoria** — última pregunta referida a algo dicho en el primer turno. Es el
  chequeo que más falla cuando `cfg_history_turns` quedó bajo.
"""
import time
import unicodedata

from django.utils import timezone

from agents_ai.agente_consultor import AgenteConsultor
from agents_ai.agentes.auditor import _detectar_respuestas_problema
from agents_ai.consumo import costo_usd
from agents_ai.memoria_django import DjangoChatMessageHistory
from agents_ai.rag import weaviate as wv
from core.constantes import PROMPT_TEMPLATES
from crm.models import AgentesIA

# ── Configuración ──────────────────────────────────────────────────────────
SOLO_AGENTE = None      # nombre parcial para acotar a uno; None = todos
LIMITE_AGENTES = None   # tope de agentes; None = sin tope

# El guion es genérico a propósito: sirve para cualquier rubro y no le regala
# al agente el vocabulario de su propio dominio.
GUION = [
    ('saludo',        'Hola, me llamo Rodrigo'),
    ('que_ofrecen',   '¿Qué ofrecen ustedes exactamente?'),
    ('precio',        '¿Cuánto cuesta?'),
    ('fuera_dominio', '¿Cuál es la capital de Mongolia?'),
    ('memoria',       '¿Cómo me llamo?'),
]

# El dato que se planta en el saludo y se pide de vuelta al final. Preguntar
# «¿cuál fue mi primera pregunta?» no sirve: es una meta-pregunta y un bot con
# prompt restrictivo la rechaza por diseño, así que medía la rigidez del prompt
# y no la memoria. Un dato del propio cliente sí es algo que debe recordar.
DATO_MEMORIA = 'rodrigo'


def _norm(t):
    t = unicodedata.normalize('NFD', (t or '').lower())
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn')


def _probar_agente(agente):
    key = agente.apikey.filter(estado=True, status=True).first()
    if not key:
        return {'agente': agente.nombre, 'error': 'sin API key activa'}

    try:
        fragmentos_rag = wv.contar(agente.id)
    except Exception:
        fragmentos_rag = 0

    # Historial limpio: si arrastra turnos viejos, el chequeo de memoria mide
    # una conversación anterior en vez de esta.
    session_id = f'prueba_{agente.id}_{int(time.time())}'
    DjangoChatMessageHistory(session_id=session_id).clear()

    class _Conv:
        id = session_id
        contacto = None
        contacto_id = None

    turnos, tok_in, tok_out, costo = [], 0, 0, 0.0
    modelo = key.modelo or ''

    for etiqueta, pregunta in GUION:
        t0 = time.time()
        try:
            consultor = AgenteConsultor(
                vectorstore_path=None,
                vectorstore_enlaces_path=None,
                provider=key.proveedor,
                apikey=key.descripcion,
                model_name=(key.modelo or None),
                conversacion=_Conv(),
                prompt_template_text=(agente.prompt_template or '').strip() or PROMPT_TEMPLATES.get('es', ''),
                contexto_estatico=agente.contexto_estatico or None,
                perfil=agente.perfil,
                agente=agente,
            )
            res = consultor.consultar(pregunta)
            ms = int((time.time() - t0) * 1000)
            respuesta = (res.respuesta or '').strip()
            modelo = consultor.model_name or modelo

            tok_in += res.tokens_entrada or 0
            tok_out += res.tokens_salida or 0
            costo += costo_usd(modelo, res.tokens_entrada or 0, res.tokens_salida or 0)

            problemas = _detectar_respuestas_problema(respuesta)
            turnos.append({
                'etiqueta': etiqueta,
                'ms': ms,
                'tokens': res.tokens_total or 0,
                'chars': len(respuesta),
                'sin_datos': bool(res.sin_datos),
                'problemas': [k for k, v in problemas.items() if v],
                'respuesta': respuesta,
            })
        except Exception as ex:
            turnos.append({
                'etiqueta': etiqueta,
                'ms': int((time.time() - t0) * 1000),
                'error': str(ex)[:160],
            })

    ok_turnos = [t for t in turnos if 'error' not in t]
    latencias = [t['ms'] for t in ok_turnos]

    # ── Veredictos ─────────────────────────────────────────────────────────
    # Recuperó conocimiento: al menos un turno de dominio no marcó `sin_datos`.
    dominio = [t for t in ok_turnos if t['etiqueta'] in ('que_ofrecen', 'precio')]
    uso_rag = any(not t['sin_datos'] for t in dominio) if dominio else None

    # Se fue de tema: ante la pregunta fuera de dominio debería no saber. Si
    # responde con la capital, está usando conocimiento general del modelo y no
    # el del negocio — que es justo lo que produce alucinaciones.
    fuera = next((t for t in ok_turnos if t['etiqueta'] == 'fuera_dominio'), None)
    delira = bool(fuera and 'ulan' in _norm(fuera['respuesta']))

    # Recordó: la respuesta al último turno repite el dato dado en el saludo.
    mem = next((t for t in ok_turnos if t['etiqueta'] == 'memoria'), None)
    recordo = bool(mem and DATO_MEMORIA in _norm(mem['respuesta']))

    return {
        'agente': agente.nombre,
        'modelo': modelo,
        'fragmentos_rag': fragmentos_rag,
        'turnos': turnos,
        'fallidos': len(turnos) - len(ok_turnos),
        'lat_media': int(sum(latencias) / len(latencias)) if latencias else 0,
        'lat_max': max(latencias) if latencias else 0,
        'tokens': tok_in + tok_out,
        'costo': round(costo, 6),
        'uso_rag': uso_rag,
        'delira': delira,
        'recordo': recordo,
        'con_problemas': sum(1 for t in ok_turnos if t['problemas']),
    }


def main():
    qs = AgentesIA.objects.filter(status=True).order_by('nombre')
    if SOLO_AGENTE:
        qs = qs.filter(nombre__icontains=SOLO_AGENTE)
    agentes = list(qs[:LIMITE_AGENTES] if LIMITE_AGENTES else qs)

    print('Banco de pruebas · %s · %d agente(s) · %d turnos c/u'
          % (timezone.now().strftime('%Y-%m-%d %H:%M'), len(agentes), len(GUION)))
    print('=' * 100)

    resultados = []
    for a in agentes:
        r = _probar_agente(a)
        resultados.append(r)
        if r.get('error'):
            print('%-24s  %s' % (a.nombre[:24], r['error']))
            continue
        print('%-24s  lat %5d ms (max %5d)  %6d tok  USD %.4f  RAG %-3s  memoria %-3s  delira %-3s  fallos %d'
              % (r['agente'][:24], r['lat_media'], r['lat_max'], r['tokens'], r['costo'],
                 'si' if r['uso_rag'] else 'NO',
                 'si' if r['recordo'] else 'NO',
                 'SI' if r['delira'] else 'no',
                 r['fallidos']))
        for t in r['turnos']:
            if 'error' in t:
                print('      %-14s ERROR %s' % (t['etiqueta'], t['error'][:80]))
            elif t['problemas']:
                print('      %-14s %s' % (t['etiqueta'], ', '.join(t['problemas'])))

    validos = [r for r in resultados if not r.get('error')]
    print('=' * 100)
    if validos:
        print('TOTAL  %d agentes · %d tokens · USD %.4f · latencia media %d ms'
              % (len(validos), sum(r['tokens'] for r in validos),
                 sum(r['costo'] for r in validos),
                 int(sum(r['lat_media'] for r in validos) / len(validos))))
        print('  sin recuperar RAG: %s' % ([r['agente'] for r in validos if not r['uso_rag']] or 'ninguno'))
        print('  sin memoria      : %s' % ([r['agente'] for r in validos if not r['recordo']] or 'ninguno'))
        print('  delirando        : %s' % ([r['agente'] for r in validos if r['delira']] or 'ninguno'))
        print('  con fallos       : %s' % ([r['agente'] for r in validos if r['fallidos']] or 'ninguno'))
    return resultados


RESULTADOS = main()
