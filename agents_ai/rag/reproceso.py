"""Reproceso del RAG de un agente — pipeline por etapas con verificación.

Grafo de etapas (estilo LangGraph, implementado como pipeline de estado para
no depender del paquete):

    extracción → chunking+embeddings → verificación de calidad → resumen precomputado

Cada etapa registra su resultado en `estado['etapas']` — la UI muestra la traza
completa, incluidos los errores por fuente (nada de `except: print`).

El resumen precomputado sigue el patrón de optimización de tokens: cuando el
conocimiento va a FAISS (>40k chars), `contexto_estatico` deja de ser un
truncado crudo y pasa a ser un resumen estructurado del negocio generado con
UNA sola llamada LLM — cada mensaje posterior viaja con ese resumen compacto
en vez de texto crudo.
"""
import logging
import os

logger = logging.getLogger(__name__)

_UMBRAL_ESTATICO = 40_000
_MAX_CHARS_MUESTRA_RESUMEN = 6_000
_MAX_TOKENS_RESUMEN = 800
_MAX_CHARS_RESUMEN = 4_000

_PROMPT_RESUMEN = (
    "Eres un analista de negocios. A partir del siguiente material de un negocio "
    "(catálogos, menús, políticas, información institucional), genera un RESUMEN "
    "ESTRUCTURADO de máximo 20 líneas que un asistente de WhatsApp pueda usar como "
    "contexto base: qué es el negocio, qué vende/ofrece (categorías con rangos de "
    "precio si existen), horarios, ubicación/contacto y políticas clave. "
    "Sin relleno, sin introducciones ni cierres, solo datos.\n\n"
    "MATERIAL:\n{muestra}\n\nRESUMEN:"
)


def _etapa(estado, nombre, ok, detalle):
    estado['etapas'].append({'etapa': nombre, 'ok': bool(ok), 'detalle': str(detalle)[:500]})


def reprocesar_agente(agente, apikey_obj) -> dict:
    """Reconstruye el conocimiento del agente de punta a punta.

    Devuelve {'ok', 'modo', 'etapas': [{etapa, ok, detalle}], 'chunks_total'}.
    No lanza — todo error queda en la traza de etapas.
    """
    from django.conf import settings
    from .extraccion import extraer_texto_archivo
    from .vectorstore import VectorStoreManager

    estado = {'ok': False, 'modo': '', 'etapas': [], 'chunks_total': 0}

    # ── Etapa 1: extracción ────────────────────────────────────────────
    textos, fuentes_error = [], []
    detalles_archivo = agente.detalleagentesai_set.filter(status=True, tipo=2, archivo__isnull=False)
    detalles_texto = (
        agente.detalleagentesai_set.filter(status=True, tipo=3)
        .exclude(descripcion__isnull=True).exclude(descripcion='')
    )
    for d in detalles_archivo:
        try:
            texto = extraer_texto_archivo(d.archivo.path)
            if texto:
                textos.append((os.path.basename(d.archivo.name), texto))
            else:
                fuentes_error.append(f"{os.path.basename(d.archivo.name)}: sin texto legible (¿escaneado sin OCR o formato sin soporte?)")
        except Exception as exc:
            fuentes_error.append(f"{os.path.basename(d.archivo.name)}: {exc}")
    for d in detalles_texto:
        textos.append((f"texto #{d.id}", d.descripcion.strip()))

    total_chars = sum(len(t) for _, t in textos)
    if fuentes_error:
        _etapa(estado, 'Extracción', False,
               f"{len(textos)} fuente(s) OK, {len(fuentes_error)} con error: " + ' | '.join(fuentes_error))
    else:
        _etapa(estado, 'Extracción', True, f"{len(textos)} fuente(s), {total_chars:,} caracteres extraídos")

    if not textos:
        _etapa(estado, 'Chunking y embeddings', False, 'Sin texto para indexar — revisa las fuentes de entrenamiento.')
        return estado

    texto_completo = "\n\n".join(t for _, t in textos)

    # ── Etapa 2: chunking + embeddings (o modo estático) ───────────────
    base_dir = os.path.join(settings.MEDIA_ROOT, 'vectorstores')
    vs_path_abs = ''
    if len(texto_completo) <= _UMBRAL_ESTATICO:
        agente.contexto_estatico = texto_completo
        agente.vectorstore_path = None
        agente.save()
        estado['modo'] = 'Contexto estático'
        _etapa(estado, 'Chunking y embeddings', True,
               f'Texto ≤ {_UMBRAL_ESTATICO:,} chars — inyección directa al prompt, cero embeddings por mensaje.')
    else:
        try:
            vsm = VectorStoreManager(
                storage_dir=base_dir,
                provider=apikey_obj.proveedor,
                apikey=apikey_obj.descripcion,
                base_url=(getattr(apikey_obj, 'base_url', '') or None),
            )
            documentos = []
            for d in detalles_archivo:
                try:
                    documentos.extend(vsm.load_and_split(d.archivo.path, metadata={'detalle_id': d.id}))
                except Exception as exc:
                    fuentes_error.append(f"{os.path.basename(d.archivo.name)} (chunking): {exc}")
            for d in detalles_texto:
                documentos.extend(vsm.build_from_string(d.descripcion, metadata={'detalle_id': d.id}))
            if not documentos:
                _etapa(estado, 'Chunking y embeddings', False, 'No se generó ningún fragmento.')
                return estado
            vs_path_abs = vsm.build_and_save(documentos, f'agente_{agente.id}')
            agente.vectorstore_path = os.path.relpath(vs_path_abs, settings.MEDIA_ROOT)
            agente.save()
            estado['modo'] = 'FAISS'
            estado['chunks_total'] = len(documentos)
            _etapa(estado, 'Chunking y embeddings', True,
                   f'{len(documentos)} fragmentos indexados en FAISS (chunk 2000/200).')
        except Exception as exc:
            _etapa(estado, 'Chunking y embeddings', False, f'Error construyendo FAISS: {exc}')
            return estado
        finally:
            try:
                from ..consultor.retrieval import invalidate_vectorstore_cache
                if vs_path_abs:
                    invalidate_vectorstore_cache(vs_path_abs)
            except Exception:
                pass

    # ── Etapa 3: verificación de calidad ───────────────────────────────
    try:
        if estado['modo'] == 'FAISS':
            from ..consultor.retrieval import _get_vectorstore_cached
            vs = _get_vectorstore_cached(vs_path_abs, vsm.embeddings)
            pruebas_ok = 0
            consultas = [nombre for nombre, _ in textos[:3]] or ['información del negocio']
            if vs is not None:
                for q in consultas:
                    if vs.similarity_search(q, k=1):
                        pruebas_ok += 1
            _etapa(estado, 'Verificación', pruebas_ok > 0,
                   f'{pruebas_ok}/{len(consultas)} búsquedas de prueba recuperaron fragmentos.')
        else:
            _etapa(estado, 'Verificación', True,
                   f'Contexto estático de {len(agente.contexto_estatico or ""):,} chars listo.')
    except Exception as exc:
        _etapa(estado, 'Verificación', False, f'No se pudo verificar el índice: {exc}')

    # ── Etapa 4: resumen precomputado del negocio (solo modo FAISS) ────
    if estado['modo'] == 'FAISS':
        try:
            from ..providers import get_provider
            proveedor = get_provider(apikey_obj.proveedor)
            llm = proveedor.get_llm(
                apikey=apikey_obj.descripcion,
                model_name=(apikey_obj.modelo or None) or proveedor.default_model(),
                max_output_tokens=_MAX_TOKENS_RESUMEN,
                temperature=0.2,
                base_url=(getattr(apikey_obj, 'base_url', '') or None),
            )
            muestra = texto_completo[:_MAX_CHARS_MUESTRA_RESUMEN]
            respuesta = llm.invoke(_PROMPT_RESUMEN.format(muestra=muestra))
            resumen = (getattr(respuesta, 'content', '') or '').strip()[:_MAX_CHARS_RESUMEN]
            if resumen:
                agente.contexto_estatico = resumen
                agente.save(update_fields=['contexto_estatico'])
                t_in, t_out = proveedor.extract_tokens(respuesta)
                _registrar_consumo_resumen(agente, apikey_obj, t_in, t_out)
                _etapa(estado, 'Resumen precomputado', True,
                       f'Resumen del negocio de {len(resumen):,} chars generado con 1 llamada LLM '
                       f'({t_in + t_out} tokens) — reemplaza al truncado crudo en cada mensaje.')
            else:
                _etapa(estado, 'Resumen precomputado', False, 'El LLM devolvió vacío — se mantiene el contexto anterior.')
        except Exception as exc:
            _etapa(estado, 'Resumen precomputado', False, f'No se pudo generar el resumen: {exc}')

    estado['ok'] = all(e['ok'] for e in estado['etapas'][1:]) if len(estado['etapas']) > 1 else False
    return estado


def _registrar_consumo_resumen(agente, apikey_obj, t_in, t_out):
    try:
        from crm.models import ConsumoTokenIA
        if t_in or t_out:
            ConsumoTokenIA.objects.create(
                apikey=apikey_obj, agente=agente,
                tokens_entrada=t_in, tokens_salida=t_out, tokens_total=t_in + t_out,
                modelo=(apikey_obj.modelo or ''), origen='resumidor',
                prompt_preview='Resumen precomputado del negocio (reproceso RAG)',
            )
    except Exception:
        logger.exception('No se pudo registrar el consumo del resumen precomputado')
