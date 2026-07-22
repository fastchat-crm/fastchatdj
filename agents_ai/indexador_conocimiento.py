"""
Indexador de conocimiento del panel de agentes → Weaviate multi-tenant.

Puente transversal (cualquier agente/empresa): toma las fuentes cargadas en el
panel de un agente (DetalleAgentesAI: enlaces, archivos, textos) y las indexa en
el tenant Weaviate de su empresa (PerfilNegocioIA). Reindexado NO destructivo por
source: solo reemplaza las fuentes del panel, conservando sources ajenos
('cuestionario', 'centros_medicos', etc.) cargados por otras vías (p.ej. SSH).

Embeddings: Gemini (proveedor 2 de ApiKeyIA), igual que el consultor RAG.
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

# tipo de DetalleAgentesAI → etiqueta estable en Weaviate
_TIPO_ETIQUETA = {1: "enlace", 2: "archivo", 3: "texto"}


# ---------------------------------------------------------------------------
# Helpers de resolución / extracción
# ---------------------------------------------------------------------------

def _resolver_gemini_key(empresa_id: int) -> str:
    """API key Gemini (proveedor 2) activa del perfil para embeddings del RAG.
    Replica _resolver_embed_key de agente_consultor.py."""
    try:
        from crm.models import ApiKeyIA
        ak = (ApiKeyIA.objects
              .filter(perfil_id=empresa_id, proveedor=2, estado=True, status=True)
              .order_by('-id').first())
        return ak.descripcion if ak else ''
    except Exception as exc:
        logger.debug("No se pudo resolver Gemini embed key: %s", exc)
        return ''


def _json_a_texto(obj, nivel: int = 0) -> str:
    """Aplana recursivamente un JSON a texto legible (para enlaces tipo JSON)."""
    indent = "  " * nivel
    if isinstance(obj, list):
        return "\n\n".join(
            f"{indent}[{i + 1}]\n{_json_a_texto(v, nivel + 1)}"
            for i, v in enumerate(obj)
        )
    if isinstance(obj, dict):
        lineas = []
        for k, v in obj.items():
            if v is None or str(v).strip() == "":
                continue
            if isinstance(v, (dict, list)):
                sub = _json_a_texto(v, nivel + 1)
                if sub.strip():
                    lineas.append(f"{indent}{k}:\n{sub}")
            else:
                lineas.append(f"{indent}{k}: {v}")
        return "\n".join(lineas)
    return f"{indent}{obj}"


def _texto_de_enlace(detalle) -> str:
    """Descarga el enlace del detalle y lo devuelve como texto plano.
    tipo_dato_enlace: 1=TEXT, 2=HTML, 3=JSON, 4=EXCEL, 5=CSV. Puede lanzar."""
    import requests

    headers = {}
    if detalle.requiere_token and detalle.token_autorizacion:
        headers['Authorization'] = f'Bearer {detalle.token_autorizacion}'
    resp = requests.get(detalle.enlace, headers=headers, timeout=30)
    resp.raise_for_status()

    tipo_dato = detalle.tipo_dato_enlace
    if tipo_dato == 2:  # HTML
        try:
            from bs4 import BeautifulSoup
            return BeautifulSoup(resp.text, 'html.parser').get_text(separator='\n', strip=True)
        except Exception:
            return resp.text
    if tipo_dato == 3:  # JSON
        try:
            return _json_a_texto(resp.json())
        except Exception:
            return resp.text
    return resp.text  # TEXT / CSV / EXCEL crudo


def _extraer_archivo(path: str) -> str:
    """Extrae texto de un archivo por extensión: txt y docx nativos, el resto
    (pdf/csv/xlsx/json) vía VectorStoreManager._extract_raw_text."""
    ext = os.path.splitext(path or '')[1].lower()
    if ext == '.txt':
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                return fh.read()
        except Exception:
            return ''
    if ext == '.docx':
        try:
            import zipfile
            with zipfile.ZipFile(path) as z:
                xml = z.read('word/document.xml').decode('utf-8', 'ignore')
            xml = re.sub(r'</w:p>', '\n', xml)
            return re.sub(r'<[^>]+>', ' ', xml)
        except Exception:
            return ''
    from agents_ai.vectorstore_manager import VectorStoreManager
    try:
        return VectorStoreManager._extract_raw_text(path) or ''
    except Exception:
        return ''


def _extraer_detalle(detalle):
    """(texto, categoria) según el tipo del detalle. Puede lanzar (el llamador lo captura)."""
    if detalle.tipo == 2 and detalle.archivo:  # ARCHIVO
        texto = _extraer_archivo(detalle.archivo.path)
        return texto, os.path.basename(detalle.archivo.name or '')
    if detalle.tipo == 1 and detalle.enlace:  # ENLACE
        return _texto_de_enlace(detalle), detalle.enlace
    if detalle.tipo == 3:  # TEXTO
        return (detalle.descripcion or ''), ''
    return '', ''


def _trocear(texto: str, objetivo: int = 1000, maximo: int = 1200) -> list:
    """Trocea respetando párrafos: acumula hasta ~objetivo chars; un párrafo
    más largo que `maximo` se parte en duro."""
    texto = (texto or "").strip()
    if not texto:
        return []
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    if not parrafos:
        parrafos = [texto]

    chunks = []
    actual = ""
    for p in parrafos:
        if len(p) > maximo:
            if actual:
                chunks.append(actual)
                actual = ""
            for i in range(0, len(p), objetivo):
                chunks.append(p[i:i + objetivo])
            continue
        if actual and len(actual) + len(p) + 2 > maximo:
            chunks.append(actual)
            actual = p
        else:
            actual = f"{actual}\n\n{p}" if actual else p
    if actual:
        chunks.append(actual)
    return [c.strip() for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def provisionar_tenant(empresa_id: int) -> bool:
    """Asegura schema + tenant de la empresa en Weaviate. Nunca lanza. True si ok."""
    try:
        from agents_ai import weaviate_rag
        client = weaviate_rag.get_client()
        try:
            weaviate_rag.ensure_schema(client)
            weaviate_rag.ensure_tenant(client, empresa_id)
        finally:
            client.close()
        return True
    except Exception as exc:
        logger.warning("provisionar_tenant(empresa=%s) falló: %s", empresa_id, exc)
        return False


def reindexar_agente(agente) -> dict:
    """Reindexa a Weaviate las fuentes del panel de un agente (DetalleAgentesAI).

    No destructivo: por cada fuente borra solo su `source` y reinserta, dejando
    intactos los sources cargados por otras vías. Una fuente que falle no aborta
    las demás (se acumula en 'errores').
    """
    # El tenant Weaviate es POR AGENTE (agente_<id>); la key de embeddings Gemini
    # se resuelve por PERFIL (la credencial es a nivel empresa).
    perfil_id = getattr(agente, 'perfil_id', None)
    agente_id = getattr(agente, 'id', None)
    if not perfil_id or not agente_id:
        return {"ok": False, "error": "agente sin perfil/id"}

    gemini_api_key = _resolver_gemini_key(perfil_id)
    if not gemini_api_key:
        return {"ok": False, "error": "no Gemini embed key", "necesita_gemini": True}

    from agents_ai import weaviate_rag

    tenant = weaviate_rag.tenant_de_empresa(agente_id)
    provisionar_tenant(agente_id)

    indexados = 0
    fuentes = []
    errores = []
    for detalle in agente.detalleagentesai_set.filter(status=True):
        source = f"panel_detalle_{detalle.id}"
        etiqueta = _TIPO_ETIQUETA.get(detalle.tipo, "texto")
        try:
            texto, categoria = _extraer_detalle(detalle)
            trozos = _trocear(texto)
            # Idempotente NO destructivo: elimina solo el contenido previo de
            # esta fuente (aunque quede vacía, para limpiar restos obsoletos).
            weaviate_rag.borrar_por_source(agente_id, source)
            if not trozos:
                fuentes.append({"source": source, "tipo": etiqueta, "chunks": 0, "vacio": True})
                continue
            docs = [
                {"content": t, "source": source, "tipo": etiqueta, "categoria": categoria}
                for t in trozos
            ]
            n = weaviate_rag.indexar_documentos(agente_id, gemini_api_key, docs)
            indexados += n
            fuentes.append({"source": source, "tipo": etiqueta, "chunks": n})
        except Exception as exc:
            logger.warning("Fuente %s (agente %s) falló al indexar: %s",
                           source, getattr(agente, 'id', '?'), exc)
            errores.append({"source": source, "tipo": etiqueta, "error": str(exc)})

    # Limpieza de huérfanos: fuentes de detalles soft-deleted (status=False)
    # dejarían vectores recuperables en runtime; se borran sus vectores.
    for detalle in agente.detalleagentesai_set.filter(status=False):
        try:
            weaviate_rag.borrar_por_source(agente_id, f"panel_detalle_{detalle.id}")
        except Exception as exc:
            logger.debug("No se pudo limpiar fuente huérfana %s: %s", detalle.id, exc)

    # contexto_estatico del negocio: si el conocimiento del agente vive SOLO en
    # este campo (sin fuentes de panel), se indexa como fuente RAG para no perderlo
    # cuando Weaviate se activa (agentes creados por wizard/departamento). Si ya
    # hay fuentes de panel se omite, para no duplicar (ej. Vida Buena).
    weaviate_rag.borrar_por_source(agente_id, 'contexto_estatico')
    _est = (getattr(agente, 'contexto_estatico', '') or '').strip()
    _tiene_panel = agente.detalleagentesai_set.filter(status=True).exists()
    if _est and not _tiene_panel:
        try:
            _docs_est = [
                {"content": t, "source": "contexto_estatico", "tipo": "texto", "categoria": "negocio"}
                for t in _trocear(_est)
            ]
            if _docs_est:
                _n_est = weaviate_rag.indexar_documentos(agente_id, gemini_api_key, _docs_est)
                indexados += _n_est
                fuentes.append({"source": "contexto_estatico", "tipo": "texto", "chunks": _n_est})
        except Exception as exc:
            errores.append({"source": "contexto_estatico", "error": str(exc)})

    resultado = {
        "ok": True,
        "indexados": indexados,
        "total_tenant": weaviate_rag.contar(agente_id),
        "tenant": tenant,
        "fuentes": fuentes,
    }
    if errores:
        resultado["errores"] = errores
        resultado["aviso"] = f"{len(errores)} fuente(s) fallaron; el resto sí se indexó."
    return resultado


def provisionar_e_indexar_inicial(agente) -> dict:
    """Flujo post-creación de un agente: provisiona su tenant Weaviate e indexa
    el conocimiento con el que nace.

    Se apoya en reindexar_agente, que indexa TANTO las fuentes del panel
    (DetalleAgentesAI) COMO el `contexto_estatico` del negocio cuando el agente
    nace solo con ese campo (caso wizard/departamento). provisionar_tenant se
    llama aparte porque reindexar_agente cortocircuita si falta la key Gemini.

    Nunca lanza; degrada suave si faltan Gemini/Weaviate.
    """
    resultado = {"tenant_ok": False}
    try:
        agente_id = getattr(agente, 'id', None)
        if not agente_id:
            return resultado
        resultado["tenant_ok"] = provisionar_tenant(agente_id)

        tiene_contexto = bool((getattr(agente, 'contexto_estatico', '') or '').strip())
        tiene_panel = agente.detalleagentesai_set.filter(status=True).exists()
        if tiene_contexto or tiene_panel:
            resultado["reindex"] = reindexar_agente(agente)
    except Exception as exc:
        logger.warning("provisionar_e_indexar_inicial(agente=%s) falló: %s",
                       getattr(agente, 'id', '?'), exc)
    return resultado
