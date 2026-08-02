"""Alimenta el RAG de Weaviate con lo aprendido en las conversaciones reales.

Cadencia sugerida: 1 vez por noche (después de `aprender_conversaciones.py`,
que es el que genera los resúmenes que este cron indexa).

Qué hace: por cada agente, toma las conversaciones cerradas con resumen del día
y las indexa en su tenant de Weaviate bajo el source `conversaciones`. A partir
de ahí el agente recupera casos reales al responder, no solo el material que
alguien cargó a mano en el panel.

Por qué un source aparte: `reindexar_agente()` borra y reinserta **solo los
sources del panel**, así que lo que deja este cron sobrevive a un reindexado del
conocimiento manual. Y al revés: este cron no toca el material del panel.

Idempotencia: cada conversación se indexa una sola vez. El id de la conversación
va en el `source` (`conversaciones:<id>`), y antes de insertar se descartan las
que ya están en el tenant.
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from datetime import timedelta

from django.utils import timezone

from agents_ai.rag import weaviate as weaviate_rag
from core.funciones import logCron
from crm.ia_config import resolver_key_embeddings_str
from crm.models import AgentesIA
from whatsapp.models import ConversacionWhatsApp

# Ventana hacia atrás. Se mira más de un día a propósito: si el cron no corrió
# una noche, la siguiente recupera lo que quedó sin indexar.
DIAS_ATRAS = 3
# Tope por agente y corrida, para que una acumulación vieja no dispare miles de
# embeddings de golpe.
MAX_POR_AGENTE = 200
# Resúmenes más cortos que esto no aportan nada al RAG.
MIN_CHARS_RESUMEN = 80

# Textos que el resumidor deja cuando no pudo resumir. Indexarlos ensuciaría el
# conocimiento con ruido que después el agente recupera como si fuera un caso.
RESUMENES_VACIOS = ('sin resumen', 'sin datos', 'no disponible', 'n/a')


def _sources_ya_indexados(agente_id):
    """`source` de lo que ya está en el tenant, para no duplicar."""
    try:
        return {f.get('source') for f in weaviate_rag.resumen_fuentes(agente_id)}
    except Exception:
        return set()


def _documentos_de(agente, desde, ya_indexados):
    """Conversaciones del agente listas para indexar."""
    convs = (
        ConversacionWhatsApp.objects
        .filter(status=True,
                conversacion_finalizada=True,
                fecha_fin_conversacion__gte=desde,
                contacto__sesion__agente_ia=agente)
        .exclude(resumen_conversacion__isnull=True)
        .exclude(resumen_conversacion='')
        .select_related('contacto')
        .order_by('-fecha_fin_conversacion')[:MAX_POR_AGENTE * 3]
    )

    docs = []
    for conv in convs:
        source = f'conversaciones:{conv.id}'
        if source in ya_indexados:
            continue
        resumen = (conv.resumen_conversacion or '').strip()
        if len(resumen) < MIN_CHARS_RESUMEN:
            continue
        if resumen.lower() in RESUMENES_VACIOS:
            continue
        docs.append({
            'content': resumen,
            'source': source,
            'tipo': 'conversacion',
            'categoria': 'aprendizaje',
        })
        if len(docs) >= MAX_POR_AGENTE:
            break
    return docs


def procesar():
    desde = timezone.now() - timedelta(days=DIAS_ATRAS)
    agentes = AgentesIA.objects.filter(status=True)

    total_docs = 0
    agentes_tocados = 0
    saltados = []

    for agente in agentes:
        api_key = resolver_key_embeddings_str(agente.perfil_id)
        if not api_key:
            saltados.append(f'{agente.nombre} (sin key de embeddings)')
            continue

        docs = _documentos_de(agente, desde, _sources_ya_indexados(agente.id))
        if not docs:
            continue

        try:
            # `reemplazar=False`: se agrega al tenant sin tocar el conocimiento
            # que cargó el usuario en el panel.
            insertados = weaviate_rag.indexar_documentos(
                agente.id, api_key, docs, reemplazar=False
            )
            total_docs += insertados
            agentes_tocados += 1
        except Exception as ex:
            saltados.append(f'{agente.nombre} ({str(ex)[:60]})')

    return total_docs, agentes_tocados, saltados


try:
    docs, agentes, saltados = procesar()
    detalle = f'{docs} conversación(es) indexada(s) en {agentes} agente(s)'
    if saltados:
        detalle += f' · salteados: {"; ".join(saltados[:5])}'
    if docs or saltados:
        logCron('aprender_weaviate', detalle, exito=True)
except Exception as ex:
    logCron('aprender_weaviate', f'Error: {ex}', exito=False)
    raise
