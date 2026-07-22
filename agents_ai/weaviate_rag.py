"""
RAG transversal con Weaviate multi-tenant + embeddings Gemini.

Capacidad GENÉRICA de la plataforma (todos los clientes/agentes), no exclusiva de
un cliente. Una única colección `Conocimiento` con multi-tenancy: **1 tenant por
empresa** (`PerfilNegocioIA`), aislando la base de conocimiento de cada cliente.

- Vectores externos (vectorizer=none): los embeddings los genera Gemini
  (`text-embedding-004`) y se insertan junto al objeto. Esto mantiene Weaviate
  ligero y evita carga de CPU/RAM en el servidor.
- Conexión local (127.0.0.1), autenticada por API key.

Config (en orden de preferencia): variables de entorno, luego /home/weaviate/.env.
"""
import logging
import os
import time

logger = logging.getLogger(__name__)

COLECCION = "Conocimiento"
EMBED_MODEL = "models/gemini-embedding-001"


# ---------------------------------------------------------------------------
# Config / conexión
# ---------------------------------------------------------------------------

def _cfg(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val:
        return val
    for path in ("/home/weaviate/.env",):
        try:
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith(f"{key}=") and not line.startswith("#"):
                        return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return default


def get_client():
    """Devuelve un cliente Weaviate v4 conectado al servidor local autenticado.

    El llamador es responsable de cerrarlo (client.close()) o usar `conectar()`.
    """
    import weaviate
    from weaviate.classes.init import Auth

    host = _cfg("WEAVIATE_HOST", "127.0.0.1")
    http_port = int(_cfg("WEAVIATE_HTTP_PORT", "8080"))
    grpc_port = int(_cfg("WEAVIATE_GRPC_PORT", "50051"))
    api_key = _cfg("WEAVIATE_API_KEY", "")

    return weaviate.connect_to_local(
        host=host, port=http_port, grpc_port=grpc_port,
        auth_credentials=Auth.api_key(api_key) if api_key else None,
        skip_init_checks=True,
    )


def tenant_de_empresa(empresa_id) -> str:
    """Nombre de tenant determinista. NOTA: cada AGENTE tiene su propio nodo, así
    que el id que se pasa es el id del AGENTE (no el de la empresa). Se conserva el
    nombre de la función y del parámetro por compatibilidad con los callers."""
    return f"agente_{empresa_id}"


# ---------------------------------------------------------------------------
# Embeddings (Gemini)
# ---------------------------------------------------------------------------

def _embeddings(gemini_api_key: str):
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    return GoogleGenerativeAIEmbeddings(model=EMBED_MODEL, google_api_key=gemini_api_key)


def _embed_en_lotes(emb, textos: list[str], lote: int = 20, pausa: float = 1.2,
                    reintentos: int = 5) -> list:
    """Embebe en lotes pequeños con pausa y backoff ante 429 (rate limit de Gemini)."""
    vectores = []
    for i in range(0, len(textos), lote):
        chunk = textos[i:i + lote]
        for intento in range(reintentos):
            try:
                vectores.extend(emb.embed_documents(chunk))
                break
            except Exception as exc:
                msg = str(exc).lower()
                if ('429' in msg or 'exhausted' in msg or 'rate' in msg) and intento < reintentos - 1:
                    espera = pausa * (2 ** intento)
                    logger.warning("Rate limit embeddings, reintento en %.1fs", espera)
                    time.sleep(espera)
                else:
                    raise
        time.sleep(pausa)
    return vectores


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def ensure_schema(client) -> None:
    """Crea la colección multi-tenant `Conocimiento` si no existe."""
    import weaviate.classes.config as wvcc

    if client.collections.exists(COLECCION):
        return
    client.collections.create(
        name=COLECCION,
        multi_tenancy_config=wvcc.Configure.multi_tenancy(
            enabled=True, auto_tenant_creation=True
        ),
        vectorizer_config=wvcc.Configure.Vectorizer.none(),
        properties=[
            wvcc.Property(name="content", data_type=wvcc.DataType.TEXT),
            wvcc.Property(name="source", data_type=wvcc.DataType.TEXT),
            wvcc.Property(name="tipo", data_type=wvcc.DataType.TEXT),
            wvcc.Property(name="categoria", data_type=wvcc.DataType.TEXT),
        ],
    )
    logger.info("Colección Weaviate '%s' creada (multi-tenant).", COLECCION)


def ensure_tenant(client, empresa_id) -> str:
    """Asegura que exista el tenant de la empresa. Devuelve el nombre del tenant."""
    from weaviate.classes.tenants import Tenant

    tenant = tenant_de_empresa(empresa_id)
    col = client.collections.get(COLECCION)
    try:
        existentes = {t for t in col.tenants.get().keys()}
        if tenant not in existentes:
            col.tenants.create([Tenant(name=tenant)])
    except Exception as exc:
        logger.debug("ensure_tenant (auto_tenant_creation cubrirá): %s", exc)
    return tenant


# ---------------------------------------------------------------------------
# Indexado
# ---------------------------------------------------------------------------

def indexar_documentos(empresa_id, gemini_api_key: str, docs: list[dict],
                       reemplazar: bool = False) -> int:
    """Indexa documentos en el tenant de la empresa.

    docs: [{'content': str, 'source': str, 'tipo': str, 'categoria': str}, ...]
    reemplazar: si True, borra el contenido previo del tenant antes de insertar.
    Devuelve la cantidad de objetos insertados.
    """
    from weaviate.classes.data import DataObject

    docs = [d for d in docs if (d.get("content") or "").strip()]
    if not docs:
        return 0

    client = get_client()
    try:
        ensure_schema(client)
        tenant = ensure_tenant(client, empresa_id)
        col = client.collections.get(COLECCION).with_tenant(tenant)

        if reemplazar:
            try:
                col.data.delete_many(where=None)  # type: ignore
            except Exception:
                # Fallback: borrar el tenant entero y recrearlo
                from weaviate.classes.tenants import Tenant
                base = client.collections.get(COLECCION)
                base.tenants.remove([tenant])
                base.tenants.create([Tenant(name=tenant)])
                col = client.collections.get(COLECCION).with_tenant(tenant)

        emb = _embeddings(gemini_api_key)
        textos = [d["content"] for d in docs]
        vectores = _embed_en_lotes(emb, textos)

        objetos = [
            DataObject(
                properties={
                    "content": d.get("content", ""),
                    "source": d.get("source", ""),
                    "tipo": d.get("tipo", ""),
                    "categoria": d.get("categoria", ""),
                },
                vector=vec,
            )
            for d, vec in zip(docs, vectores)
        ]
        col.data.insert_many(objetos)
        return len(objetos)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------

def buscar(empresa_id, gemini_api_key: str, query: str, k: int = 5) -> list[dict]:
    """Búsqueda semántica en el tenant de la empresa. Devuelve lista de dicts
    {content, source, tipo, categoria, distancia}."""
    from weaviate.classes.query import MetadataQuery

    client = get_client()
    try:
        if not client.collections.exists(COLECCION):
            return []
        tenant = tenant_de_empresa(empresa_id)
        col = client.collections.get(COLECCION).with_tenant(tenant)

        emb = _embeddings(gemini_api_key)
        qvec = emb.embed_query(query)

        res = col.query.near_vector(
            near_vector=qvec, limit=k,
            return_metadata=MetadataQuery(distance=True),
        )
        salida = []
        for obj in res.objects:
            p = obj.properties or {}
            salida.append({
                "content": p.get("content", ""),
                "source": p.get("source", ""),
                "tipo": p.get("tipo", ""),
                "categoria": p.get("categoria", ""),
                "distancia": getattr(obj.metadata, "distance", None),
            })
        return salida
    except Exception as exc:
        logger.error("Error en búsqueda Weaviate: %s", exc)
        return []
    finally:
        client.close()


def borrar_por_source(empresa_id, source: str) -> int:
    """Borra del tenant los objetos con un `source` dado (para reindexar idempotente)."""
    from weaviate.classes.query import Filter
    client = get_client()
    try:
        if not client.collections.exists(COLECCION):
            return 0
        tenant = tenant_de_empresa(empresa_id)
        col = client.collections.get(COLECCION).with_tenant(tenant)
        res = col.data.delete_many(where=Filter.by_property("source").equal(source))
        return getattr(res, "successful", 0) or 0
    except Exception as exc:
        logger.debug("borrar_por_source: %s", exc)
        return 0
    finally:
        client.close()


def contar(empresa_id) -> int:
    """Cantidad de objetos indexados en el tenant de la empresa."""
    client = get_client()
    try:
        if not client.collections.exists(COLECCION):
            return 0
        tenant = tenant_de_empresa(empresa_id)
        col = client.collections.get(COLECCION).with_tenant(tenant)
        return col.aggregate.over_all(total_count=True).total_count
    except Exception as exc:
        logger.debug("contar: %s", exc)
        return 0
    finally:
        client.close()


def resumen_fuentes(empresa_id) -> list:
    """Lista las fuentes (documentos) indexadas en el tenant, agrupadas por `source`:
    [{'source', 'tipo', 'categoria', 'count'}, ...] ordenado por cantidad desc.
    Para mostrar en la UI qué conocimiento tiene el agente."""
    client = get_client()
    try:
        if not client.collections.exists(COLECCION):
            return []
        tenant = tenant_de_empresa(empresa_id)
        col = client.collections.get(COLECCION).with_tenant(tenant)
        agrup = {}
        for obj in col.iterator(return_properties=["source", "tipo", "categoria"]):
            p = obj.properties or {}
            src = (p.get("source") or "").strip() or "(sin fuente)"
            if src not in agrup:
                agrup[src] = {
                    "source": src,
                    "tipo": p.get("tipo", "") or "",
                    "categoria": p.get("categoria", "") or "",
                    "count": 0,
                }
            agrup[src]["count"] += 1
        return sorted(agrup.values(), key=lambda d: d["count"], reverse=True)
    except Exception as exc:
        logger.debug("resumen_fuentes: %s", exc)
        return []
    finally:
        client.close()
