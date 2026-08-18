"""Indexación y consulta de RagColeccion (RAG por sesión).

Fase 1 — almacenamiento: `indexar_coleccion` toma las fuentes de una
`crm.RagColeccion` (enlace / archivo / texto), extrae texto con la tubería
única (`extraccion.extraer_texto_archivo`, Tika/OCR incluido), chunkea +
embebe con `VectorStoreManager` y guarda un FAISS propio en
`media/vectorstores/rag_col_<id>/`.

`consultar_coleccion` es el retrieve básico (top-k con umbral) que consumirá
la fase 2 (grafo router → retrieve → respond).
"""
import logging
import os

from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_CHARS_ENLACE = 120_000


def _texto_de_fuente(fuente):
    """Extrae el texto crudo de una fuente según su tipo. Levanta ValueError
    con mensaje en español si la fuente no tiene contenido usable."""
    if fuente.tipo == 3:
        texto = (fuente.texto or '').strip()
        if not texto:
            raise ValueError('La fuente de texto está vacía.')
        return texto

    if fuente.tipo == 2:
        if not fuente.archivo:
            raise ValueError('La fuente no tiene archivo adjunto.')
        from .extraccion import extraer_texto_archivo
        texto = (extraer_texto_archivo(fuente.archivo.path) or '').strip()
        if not texto:
            raise ValueError('No se pudo extraer texto legible del archivo.')
        return texto

    if fuente.tipo == 1:
        if not fuente.enlace:
            raise ValueError('La fuente no tiene enlace.')
        import requests
        resp = requests.get(fuente.enlace, timeout=20)
        resp.raise_for_status()
        contenido = resp.text or ''
        if 'html' in (resp.headers.get('Content-Type') or ''):
            try:
                from bs4 import BeautifulSoup
                contenido = BeautifulSoup(contenido, 'html.parser').get_text(separator='\n')
            except Exception:
                pass
        contenido = contenido.strip()[:MAX_CHARS_ENLACE]
        if not contenido:
            raise ValueError('El enlace no devolvió contenido de texto.')
        return contenido

    raise ValueError(f'Tipo de fuente desconocido: {fuente.tipo}')


def indexar_coleccion(coleccion, solo_pendientes=True):
    """Indexa las fuentes de la colección a su FAISS.

    Args:
        coleccion: crm.RagColeccion.
        solo_pendientes: True = incremental (agrega solo fuentes en estado
            'pendiente' o 'error' al índice existente). False = rebuild total.

    Returns:
        dict {'error': bool, 'message': str, 'indexadas': int, 'fallidas': int,
              'total_chunks': int}
    """
    from langchain_community.vectorstores import FAISS
    from .vectorstore import VectorStoreManager

    apikey = coleccion.apikey_efectiva()
    if not apikey:
        return {'error': True, 'message': 'No hay API Key IA activa para generar embeddings.',
                'indexadas': 0, 'fallidas': 0, 'total_chunks': coleccion.total_chunks}

    ruta = coleccion.ruta_indice()
    manager = VectorStoreManager(
        storage_dir=os.path.dirname(ruta),
        provider=apikey.proveedor,
        apikey=apikey.descripcion,
        base_url=getattr(apikey, 'base_url', None),
    )

    if solo_pendientes:
        fuentes = coleccion.fuentes.filter(status=True, estado__in=['pendiente', 'error'])
    else:
        fuentes = coleccion.fuentes.filter(status=True)

    if not fuentes.exists():
        return {'error': False, 'message': 'No hay fuentes pendientes por indexar.',
                'indexadas': 0, 'fallidas': 0, 'total_chunks': coleccion.total_chunks}

    docs_totales = []
    indexadas, fallidas = 0, 0
    for fuente in fuentes:
        try:
            texto = _texto_de_fuente(fuente)
            docs = manager.build_from_string(texto, metadata={
                'coleccion_id': coleccion.id,
                'fuente_id': fuente.id,
                'fuente': fuente.nombre_visible(),
                'tipo': fuente.get_tipo_display(),
            })
            docs_totales.append((fuente, docs))
            indexadas += 1
        except Exception as ex:
            logger.exception('Fuente RAG %s falló en extracción', fuente.id)
            fuente.estado = 'error'
            fuente.error_detalle = str(ex)[:1000]
            fuente.save(update_fields=['estado', 'error_detalle'])
            fallidas += 1

    if not docs_totales:
        return {'error': True, 'message': 'Ninguna fuente produjo texto indexable.',
                'indexadas': 0, 'fallidas': fallidas, 'total_chunks': coleccion.total_chunks}

    try:
        docs_planos = [d for _f, docs in docs_totales for d in docs]
        index_file = os.path.join(ruta, 'index.faiss')
        if solo_pendientes and os.path.exists(index_file):
            vs = FAISS.load_local(ruta, manager.embeddings, allow_dangerous_deserialization=True)
            vs.add_documents(docs_planos)
        else:
            vs = FAISS.from_documents(docs_planos, manager.embeddings)
        os.makedirs(ruta, exist_ok=True)
        vs.save_local(ruta)
    except Exception as ex:
        logger.exception('Fallo construyendo FAISS de la colección %s', coleccion.id)
        return {'error': True, 'message': f'Error generando embeddings: {str(ex)[:300]}',
                'indexadas': 0, 'fallidas': fallidas + indexadas,
                'total_chunks': coleccion.total_chunks}

    total_chunks = coleccion.total_chunks if solo_pendientes else 0
    for fuente, docs in docs_totales:
        fuente.estado = 'indexado'
        fuente.error_detalle = ''
        fuente.chunks = len(docs)
        fuente.save(update_fields=['estado', 'error_detalle', 'chunks'])
        total_chunks += len(docs)

    coleccion.vectorstore_path = ruta
    coleccion.total_chunks = total_chunks
    coleccion.ultima_indexacion = timezone.now()
    coleccion.save(update_fields=['vectorstore_path', 'total_chunks', 'ultima_indexacion'])

    return {'error': False,
            'message': f'{indexadas} fuente(s) indexada(s), {fallidas} con error.',
            'indexadas': indexadas, 'fallidas': fallidas, 'total_chunks': total_chunks}


def consultar_coleccion(coleccion, pregunta, k=4, umbral=0.45):
    """Retrieve básico sobre el FAISS de la colección.

    Devuelve lista de dicts {'texto', 'fuente', 'score'} con score de similitud
    (menor = más cercano en FAISS L2; se filtra por umbral relativo). Base de
    la fase 2 — el grafo de consulta decidirá cuándo llamarla.
    """
    from langchain_community.vectorstores import FAISS
    from .vectorstore import VectorStoreManager

    ruta = coleccion.vectorstore_path or coleccion.ruta_indice()
    if not os.path.exists(os.path.join(ruta, 'index.faiss')):
        return []
    apikey = coleccion.apikey_efectiva()
    if not apikey:
        return []
    manager = VectorStoreManager(
        storage_dir=os.path.dirname(ruta),
        provider=apikey.proveedor,
        apikey=apikey.descripcion,
        base_url=getattr(apikey, 'base_url', None),
    )
    vs = FAISS.load_local(ruta, manager.embeddings, allow_dangerous_deserialization=True)
    resultados = vs.similarity_search_with_score(pregunta, k=k)
    if not resultados:
        return []
    mejor = min(score for _d, score in resultados)
    corte = mejor + umbral
    return [
        {
            'texto': doc.page_content,
            'fuente': doc.metadata.get('fuente', ''),
            'score': float(score),
        }
        for doc, score in resultados if score <= corte
    ]
