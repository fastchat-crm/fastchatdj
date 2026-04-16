import base64
import mimetypes
import os
import sys
import tempfile
import time
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.conf import settings

from agents_ai.agente_consultor import AgenteConsultor
from agents_ai.memoria_django import DjangoChatMessageHistory
from core.constantes import PROMPT_TEMPLATES
from core.funciones import addData, get_encrypt, get_decrypt, log
from crm.acciones_fin import ejecutar_acciones_fin
from crm.models import AgentesIA, PerfilNegocioIA, ConsumoTokenIA

from langchain_core.messages import HumanMessage, AIMessage


@login_required
def chat_agente_view(request, agente_enc_id):
    data = {
        'titulo': 'Probar Agente IA',
        'descripcion': 'Conversación de prueba con el agente entrenado',
        'ruta': request.path,
    }
    addData(request, data)

    # Desencriptar y verificar que el agente pertenezca al usuario
    try:
        agente_id = int(get_decrypt(agente_enc_id)[1])
        perfil = PerfilNegocioIA.objects.get(usuario=request.user)
        agente = AgentesIA.objects.get(pk=agente_id, perfil=perfil, status=True)
    except Exception:
        return redirect('/crm/entrenamiento/')

    session_id = f"webchat_{agente.id}_{request.user.id}"

    if request.method == 'POST':
        action = request.POST.get('action', 'send')

        # ── Limpiar historial ──────────────────────────────────────────
        if action == 'clear':
            DjangoChatMessageHistory(session_id=session_id).clear()
            log(f"Historial de chat de prueba limpiado para agente {agente}", request, "change", obj=agente.id)
            return JsonResponse({'error': False})

        # ── Enviar mensaje al agente ───────────────────────────────────
        if action == 'send':
            pregunta = request.POST.get('mensaje', '').strip()
            if not pregunta:
                return JsonResponse({'error': True, 'message': 'Escribe un mensaje antes de enviar.'})

            apikey_obj = agente.apikey.filter(estado=True).first()
            if not apikey_obj:
                return JsonResponse({
                    'error': True,
                    'message': 'Este agente no tiene una API Key activa. Configúrala en Entrenamiento IA.'
                })

            vs_path = (
                os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path)
                if agente.vectorstore_path else None
            )
            vectorstore_enlaces_path = None
            try:
                agente.build_enlaces_vectorstore()
                if agente.vectorstore_enlaces_path:
                    vectorstore_enlaces_path = os.path.join(
                        settings.MEDIA_ROOT, agente.vectorstore_enlaces_path
                    )
            except Exception:
                pass

            # ── Configuración de fin de conversación ──────────────────────
            regla_fin = getattr(agente, 'regla_fin', None)
            fin_por_frase = (
                regla_fin is not None
                and regla_fin.activo
                and regla_fin.detectar_por_frase(pregunta)
            )
            detectar_fin_llm = (
                regla_fin is not None
                and regla_fin.activo
                and regla_fin.usar_senal_llm
            )

            # SimpleNamespace provee el .id que AgenteConsultor usa para memoria
            fake_conv = SimpleNamespace(id=session_id, contacto=None)

            _t0 = time.time()
            traza_etapas = [{
                'etapa': 'inicio',
                'label': 'Pregunta recibida',
                'ok': True,
                'detalle': f'"{pregunta[:120]}"' + ('...' if len(pregunta) > 120 else ''),
                'ts_ms': 0,
            }]
            try:
                consultor = AgenteConsultor(
                    vectorstore_path=vs_path,
                    vectorstore_enlaces_path=vectorstore_enlaces_path,
                    provider=apikey_obj.proveedor,
                    apikey=apikey_obj.descripcion,
                    model_name=(agente.modelo or None),
                    conversacion=fake_conv,
                    prompt_template_text=(agente.prompt_template or '').strip() or PROMPT_TEMPLATES.get('es', ''),
                    contexto_estatico=agente.contexto_estatico or None,
                    detectar_fin=detectar_fin_llm,
                    perfil=agente.perfil,
                    agente=agente,
                )
                traza_etapas.append({
                    'etapa': 'consultor_listo',
                    'label': 'Consultor configurado',
                    'ok': True,
                    'detalle': f'Proveedor: {"Gemini" if apikey_obj.proveedor == 2 else "OpenAI"} | Modelo: {consultor.model_name}',
                    'ts_ms': int((time.time() - _t0) * 1000),
                })
                _t_llm = time.time()
                if agente.requiere_tools():
                    resultado = consultor.consultar_con_listas(pregunta, agente.descripcion)
                else:
                    resultado = consultor.consultar(pregunta, agente.descripcion)
                _lat_llm = int((time.time() - _t_llm) * 1000)
                traza_etapas.append({
                    'etapa': 'llm_respondio',
                    'label': 'LLM respondió',
                    'ok': True,
                    'detalle': f'Latencia: {_lat_llm} ms · Tokens: {resultado.tokens_total} (in={resultado.tokens_entrada}, out={resultado.tokens_salida})',
                    'ts_ms': int((time.time() - _t0) * 1000),
                })
            except Exception as ex:
                line = sys.exc_info()[-1].tb_lineno
                traza_etapas.append({
                    'etapa': 'error',
                    'label': 'Error en pipeline',
                    'ok': False,
                    'detalle': f'Linea {line}: {str(ex)[:400]}',
                    'ts_ms': int((time.time() - _t0) * 1000),
                })
                return JsonResponse({
                    'error': True,
                    'message': f'Error al consultar el agente (línea {line}): {ex}',
                    'traza': {'etapas': traza_etapas},
                })

            # Detectar problemas de calidad en la respuesta
            from agents_ai.auditor_agente import _detectar_respuestas_problema
            flags = _detectar_respuestas_problema(resultado.respuesta or '')
            problemas = []
            if flags.get('rechazo'):  problemas.append({'tipo': 'rechazo', 'label': 'Respuesta de rechazo ("no tengo esa info")'})
            if flags.get('muy_larga'): problemas.append({'tipo': 'muy_larga', 'label': f'Muy larga ({len(resultado.respuesta or "")} chars)'})
            if flags.get('wiki'):     problemas.append({'tipo': 'wiki', 'label': 'Estilo Wikipedia detectado'})
            if flags.get('vacia'):    problemas.append({'tipo': 'vacia', 'label': 'Respuesta vacía'})
            if resultado.sin_datos:   problemas.append({'tipo': 'sin_datos', 'label': 'Sin datos del vectorstore (fallback a conocimiento general)'})

            # Score rapido: 100 - (20 por cada problema)
            score = max(0, 100 - len(problemas) * 20)
            if problemas and all(p['tipo'] in ('sin_datos',) for p in problemas):
                score = min(score + 10, 100)  # sin_datos solo no es tan grave

            fin_detectado = fin_por_frase or resultado.fin_detectado

            # ── Registrar consumo de tokens ───────────────────────────────────
            if resultado.tokens_total > 0:
                try:
                    from crm.alertas_consumo import verificar_alerta_consumo
                    ConsumoTokenIA.objects.create(
                        apikey=apikey_obj, agente=agente,
                        tokens_entrada=resultado.tokens_entrada,
                        tokens_salida=resultado.tokens_salida,
                        tokens_total=resultado.tokens_total,
                        modelo=consultor.model_name,
                    )
                    verificar_alerta_consumo(apikey_obj, resultado.tokens_total)
                except Exception:
                    pass

            # ── Ejecutar acciones de fin (sin sesión_id real = chat de prueba) ──
            if fin_detectado and regla_fin:
                try:
                    contexto_fin = {
                        'nombre_contacto': request.user.get_full_name() or request.user.username,
                        'numero': '',
                        'sesion': f'Chat de prueba — {agente.nombre}',
                        'sesion_id': '',   # sin sesión WA real
                        'resumen': '',
                        'agente': agente.nombre,
                    }
                    ejecutar_acciones_fin(regla_fin, contexto_fin)
                except Exception:
                    pass

            return JsonResponse({
                'error': False,
                'respuesta': resultado.respuesta,
                'fin_detectado': fin_detectado,
                'sin_datos': resultado.sin_datos,
                'traza': {
                    'latencia_total_ms': int((time.time() - _t0) * 1000),
                    'latencia_llm_ms': _lat_llm,
                    'tokens_in': resultado.tokens_entrada,
                    'tokens_out': resultado.tokens_salida,
                    'tokens_total': resultado.tokens_total,
                    'modelo': consultor.model_name,
                    'proveedor': 'Gemini' if apikey_obj.proveedor == 2 else 'OpenAI',
                    'caracteres_respuesta': len(resultado.respuesta or ''),
                    'score_calidad': score,
                    'problemas': problemas,
                    'usa_rag': bool(agente.vectorstore_path),
                    'usa_contexto_estatico': bool(agente.contexto_estatico),
                    'fin_detectado': fin_detectado,
                    'etapas': traza_etapas,
                },
            })

        # ── Enviar imagen o audio al agente ───────────────────────────────
        if action == 'send_media':
            return _handle_media(request, agente, session_id)

        return JsonResponse({'error': True, 'message': 'Acción no reconocida.'})

    # ── GET — cargar historial previo ──────────────────────────────────
    raw_messages = DjangoChatMessageHistory(session_id=session_id).messages
    mensajes_previos = []
    for m in raw_messages:
        if isinstance(m, HumanMessage):
            mensajes_previos.append({'tipo': 'humano', 'texto': m.content})
        elif isinstance(m, AIMessage) and not m.content.startswith('LISTA_GUARDADA:'):
            mensajes_previos.append({'tipo': 'ia', 'texto': m.content})

    data['agente'] = agente
    data['agente_enc_id'] = agente_enc_id
    data['mensajes_previos'] = mensajes_previos

    return render(request, 'crm/entrenamiento/chat.html', data)


# ---------------------------------------------------------------------------
# Procesamiento de archivos multimedia (imagen / audio)
# ---------------------------------------------------------------------------

def _handle_media(request, agente, session_id):
    """Procesa imagen o audio enviados desde el chat de prueba."""
    archivo = request.FILES.get('archivo')
    texto_adicional = request.POST.get('texto', '').strip()
    tipo = request.POST.get('tipo', '')   # 'imagen' | 'audio'

    if not archivo:
        return JsonResponse({'error': True, 'message': 'No se recibió ningún archivo.'})

    apikey_obj = agente.apikey.filter(estado=True).first()
    if not apikey_obj:
        return JsonResponse({'error': True, 'message': 'Este agente no tiene una API Key activa.'})

    provider = 'gemini' if apikey_obj.proveedor == 2 else 'openai'
    ext = os.path.splitext(archivo.name)[1].lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        for chunk in archivo.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        if tipo == 'imagen':
            return _analizar_imagen(tmp_path, archivo.name, texto_adicional, apikey_obj, provider, agente)
        elif tipo == 'audio':
            return _procesar_audio(tmp_path, archivo.name, texto_adicional, apikey_obj, provider, agente, session_id)
        else:
            return JsonResponse({'error': True, 'message': 'Tipo de medio no soportado.'})
    except Exception as ex:
        line = sys.exc_info()[-1].tb_lineno
        return JsonResponse({'error': True, 'message': f'Error procesando archivo (línea {line}): {ex}'})
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _leer_base64(path: str) -> str:
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def _analizar_imagen(tmp_path, filename, texto_adicional, apikey_obj, provider, agente):
    """Llama al LLM con la imagen (multimodal) y devuelve la respuesta."""
    mime_type = mimetypes.guess_type(filename)[0] or 'image/jpeg'
    b64 = _leer_base64(tmp_path)

    contexto = ''
    if agente.contexto_estatico:
        contexto = f"\n\nContexto del negocio:\n{agente.contexto_estatico[:800]}"

    prompt_text = (
        f"Eres {agente.descripcion or 'un asistente'}.{contexto}\n\n"
        f"Analiza la imagen que te adjunto y responde en español."
    )
    if texto_adicional:
        prompt_text += f" El usuario pregunta: {texto_adicional}"

    content = [
        {"type": "text", "text": prompt_text},
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
    ]
    msg = HumanMessage(content=content)

    if provider == 'gemini':
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model='gemini-2.0-flash', google_api_key=apikey_obj.descripcion
        )
    else:
        from langchain_community.chat_models import ChatOpenAI
        llm = ChatOpenAI(model_name='gpt-4o', openai_api_key=apikey_obj.descripcion)

    resp = llm.invoke([msg])
    respuesta = resp.content.strip()

    # Registrar tokens si están disponibles
    try:
        meta = resp.response_metadata or {}
        usage = meta.get('usage_metadata') or meta.get('token_usage') or {}
        tokens_e = usage.get('prompt_token_count') or usage.get('prompt_tokens') or 0
        tokens_s = usage.get('candidates_token_count') or usage.get('completion_tokens') or 0
        if tokens_e or tokens_s:
            ConsumoTokenIA.objects.create(
                apikey=apikey_obj, agente=agente,
                tokens_entrada=tokens_e, tokens_salida=tokens_s,
                tokens_total=tokens_e + tokens_s,
                modelo=getattr(llm, 'model', 'multimodal'),
            )
    except Exception:
        pass

    return JsonResponse({'error': False, 'respuesta': respuesta, 'tipo': 'imagen'})


def _procesar_audio(tmp_path, filename, texto_adicional, apikey_obj, provider, agente, session_id):
    """Transcribe el audio y lo procesa con el agente RAG."""
    transcripcion = _transcribir_audio(tmp_path, filename, apikey_obj, provider)

    pregunta = transcripcion
    if texto_adicional:
        pregunta = f"{texto_adicional}\n[Audio]: {transcripcion}"

    # Ejecutar por el pipeline normal del agente
    vs_path = (
        os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path)
        if agente.vectorstore_path else None
    )
    vectorstore_enlaces_path = None
    try:
        agente.build_enlaces_vectorstore()
        if agente.vectorstore_enlaces_path:
            vectorstore_enlaces_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path)
    except Exception:
        pass

    fake_conv = SimpleNamespace(id=session_id, contacto=None)
    consultor = AgenteConsultor(
        vectorstore_path=vs_path,
        vectorstore_enlaces_path=vectorstore_enlaces_path,
        provider=apikey_obj.proveedor,
        apikey=apikey_obj.descripcion,
        model_name=(agente.modelo or None),
        conversacion=fake_conv,
        prompt_template_text=agente.prompt_template,
        contexto_estatico=agente.contexto_estatico or None,
        perfil=agente.perfil,
        agente=agente,
    )
    resultado = consultor.consultar(pregunta, agente.descripcion)

    if resultado.tokens_total > 0:
        try:
            from crm.alertas_consumo import verificar_alerta_consumo
            ConsumoTokenIA.objects.create(
                apikey=apikey_obj, agente=agente,
                tokens_entrada=resultado.tokens_entrada,
                tokens_salida=resultado.tokens_salida,
                tokens_total=resultado.tokens_total,
                modelo=consultor.model_name,
            )
            verificar_alerta_consumo(apikey_obj, resultado.tokens_total)
        except Exception:
            pass

    return JsonResponse({
        'error': False,
        'respuesta': resultado.respuesta,
        'transcripcion': transcripcion,
        'sin_datos': resultado.sin_datos,
        'tipo': 'audio',
    })


def _transcribir_audio(tmp_path, filename, apikey_obj, provider) -> str:
    """Transcribe audio con Whisper (OpenAI) o Gemini multimodal."""
    if provider == 'openai':
        import openai as openai_lib
        client = openai_lib.OpenAI(api_key=apikey_obj.descripcion)
        with open(tmp_path, 'rb') as f:
            transcription = client.audio.transcriptions.create(model='whisper-1', file=f)
        return transcription.text.strip()
    else:
        # Gemini multimodal — transcripción de audio
        mime_type = mimetypes.guess_type(filename)[0] or 'audio/mpeg'
        b64 = _leer_base64(tmp_path)
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model='gemini-2.0-flash', google_api_key=apikey_obj.descripcion
        )
        msg = HumanMessage(content=[
            {"type": "text", "text": "Transcribe exactamente lo que dice este audio, en el idioma en que fue hablado. Solo devuelve la transcripción, sin comentarios adicionales."},
            {"type": "media", "mime_type": mime_type, "data": b64},
        ])
        resp = llm.invoke([msg])
        return resp.content.strip()
