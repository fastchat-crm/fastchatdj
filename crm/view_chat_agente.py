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

import logging
_logger = logging.getLogger(__name__)


def _registrar_consumo_tokens(respuesta_llm, apikey_obj, agente=None, modelo='',
                              conversacion=None, origen='chat_crm', prompt_preview=''):
    """Extrae tokens de la respuesta LangChain y crea ConsumoTokenIA + verifica alertas."""
    try:
        from crm.alertas_consumo import verificar_alerta_consumo
        meta = getattr(respuesta_llm, 'response_metadata', {}) or {}
        usage = (
            getattr(respuesta_llm, 'usage_metadata', None)
            or meta.get('usage_metadata')
            or meta.get('token_usage')
            or {}
        )
        tokens_e = usage.get('input_tokens') or usage.get('prompt_token_count') or usage.get('prompt_tokens') or 0
        tokens_s = usage.get('output_tokens') or usage.get('candidates_token_count') or usage.get('completion_tokens') or 0
        if tokens_e or tokens_s:
            ConsumoTokenIA.objects.create(
                apikey=apikey_obj, agente=agente, conversacion=conversacion,
                tokens_entrada=tokens_e, tokens_salida=tokens_s,
                tokens_total=tokens_e + tokens_s,
                modelo=modelo or getattr(respuesta_llm, 'model', ''),
                origen=origen, prompt_preview=(prompt_preview or '')[:300],
            )
            verificar_alerta_consumo(apikey_obj, tokens_e + tokens_s)
    except Exception:
        _logger.exception('Error registrando consumo de tokens')


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
            fake_conv = SimpleNamespace(id=session_id, contacto=None, contacto_id=None)

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
                    model_name=(apikey_obj.modelo or None),
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
                    'detalle': 'Proveedor: ' + {2: 'Gemini', 3: 'OpenAI', 4: 'Claude', 5: 'Ollama'}.get(apikey_obj.proveedor, 'LLM') + ' | Modelo: ' + str(consultor.model_name),
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
                modelo_cfg = (apikey_obj.modelo or '').strip() or ('gemini-2.5-flash' if apikey_obj.proveedor == 2 else 'gpt-4o-mini')
                msg_limpio, activo_final, flags = _clasificar_error_llm(ex, apikey_obj=apikey_obj, modelo_str=modelo_cfg)
                traza_etapas.append({
                    'etapa': 'error',
                    'label': 'Error en pipeline',
                    'ok': False,
                    'detalle': f'Linea {line}: {str(ex)[:400]}',
                    'ts_ms': int((time.time() - _t0) * 1000),
                })
                payload = {
                    'error': True,
                    'message': msg_limpio,
                    'traza': {'etapas': traza_etapas},
                }
                if activo_final is False:
                    payload['apikey_desactivada'] = True
                payload.update(flags)
                return JsonResponse(payload)

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
                        origen='chat_crm',
                        prompt_preview=(pregunta or '')[:300],
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
                    'proveedor': {2: 'Gemini', 3: 'OpenAI', 4: 'Claude', 5: 'Ollama'}.get(apikey_obj.proveedor, 'LLM'),
                    'caracteres_respuesta': len(resultado.respuesta or ''),
                    'score_calidad': score,
                    'problemas': problemas,
                    'usa_rag': bool(getattr(consultor, 'usar_weaviate', False)),
                    'usa_contexto_estatico': (not getattr(consultor, 'usar_weaviate', False)) and bool(agente.contexto_estatico),
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

def _billing_info_por_proveedor(proveedor):
    """URL de gestión de planes/facturación y nombre legible por proveedor."""
    if proveedor == 2:
        return {
            'proveedor': 'Google Gemini',
            'billing_url': 'https://aistudio.google.com/app/plan_information',
            'docs_url': 'https://ai.google.dev/gemini-api/docs/rate-limits',
        }
    if proveedor == 3:
        return {
            'proveedor': 'OpenAI',
            'billing_url': 'https://platform.openai.com/account/billing',
            'docs_url': 'https://platform.openai.com/docs/guides/rate-limits',
        }
    if proveedor == 4:
        return {
            'proveedor': 'Anthropic Claude',
            'billing_url': 'https://console.anthropic.com/settings/billing',
            'docs_url': 'https://docs.anthropic.com/claude/reference/rate-limits',
        }
    return {'proveedor': 'LLM', 'billing_url': '', 'docs_url': ''}


def _clasificar_error_llm(ex, apikey_obj=None, modelo_str=''):
    """Devuelve (message, activo_final, flags) para mostrar un error amigable
    del LLM y opcionalmente desactivar la API Key cuando el plan se quedó sin cupo.
    """
    err_str = str(ex)
    err_lower = err_str.lower()
    is_quota = ('429' in err_str
                or 'quota' in err_lower
                or 'rate limit' in err_lower
                or 'resource has been exhausted' in err_lower
                or 'too many requests' in err_lower
                or 'credit balance is too low' in err_lower
                or 'insufficient_quota' in err_lower)
    is_auth = ('401' in err_str
               or '403' in err_str
               or ('api key' in err_lower and ('invalid' in err_lower or 'not valid' in err_lower))
               or 'unauthenticated' in err_lower
               or 'permission denied' in err_lower
               or 'invalid x-api-key' in err_lower)
    is_model = ('404' in err_str
                or ('not found' in err_lower and 'model' in err_lower)
                or 'does not exist' in err_lower)
    proveedor_id = getattr(apikey_obj, 'proveedor', None)
    billing = _billing_info_por_proveedor(proveedor_id) if proveedor_id else {
        'proveedor': 'LLM', 'billing_url': '', 'docs_url': '',
    }
    flags = {'billing': billing}
    if is_quota:
        flags['quota_exceeded'] = True
        modelo_lbl = modelo_str or 'el modelo configurado'
        msg = (
            f"⚠️ Sin cupo en {modelo_lbl} ({billing['proveedor']} · quota/rate limit). "
            "La API Key se desactivó automáticamente para evitar seguir consumiendo. "
            f"Actualiza tu plan de facturación en {billing['proveedor']} o espera a que "
            "el límite se renueve y luego reactívala."
        )
        if apikey_obj is not None:
            try:
                apikey_obj.estado = False
                apikey_obj.msgerror = f'Quota/rate limit ({modelo_lbl}): {err_str[:400]}'
                apikey_obj.save()
            except Exception:
                pass
        return msg, False, flags
    if is_auth:
        flags['auth_error'] = True
        if apikey_obj is not None:
            try:
                apikey_obj.estado = False
                apikey_obj.msgerror = f'Clave inválida/sin permisos: {err_str[:400]}'
                apikey_obj.save()
            except Exception:
                pass
        return "❌ Clave inválida o sin permisos del proveedor LLM. La API Key se desactivó.", False, flags
    if is_model:
        flags['modelo_invalido'] = True
        modelo_lbl = modelo_str or 'el modelo configurado'
        if apikey_obj is not None:
            try:
                apikey_obj.msgerror = f"Modelo '{modelo_lbl}' no disponible: {err_str[:400]}"
                apikey_obj.save(update_fields=['msgerror'])
            except Exception:
                pass
        return f"⚠️ El modelo '{modelo_lbl}' no está disponible para esta API Key. Edita la key y cambia el Modelo LLM.", True, flags
    # Otro: no tocamos la key, solo mostramos mensaje corto
    return f"❌ Error del proveedor LLM: {err_str[:300]}", None, flags


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

    _provider_map = {2: 'gemini', 3: 'openai', 4: 'claude', 5: 'ollama'}
    provider = _provider_map.get(apikey_obj.proveedor, 'openai')
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
        modelo_cfg = (apikey_obj.modelo or '').strip() or ('gemini-2.0-flash' if provider == 'gemini' else 'gpt-4o')
        msg, activo, flags = _clasificar_error_llm(ex, apikey_obj=apikey_obj, modelo_str=modelo_cfg)
        payload = {'error': True, 'message': msg}
        if activo is False:
            payload['apikey_desactivada'] = True
        payload.update(flags)
        return JsonResponse(payload)
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
    if provider == 'ollama':
        # Ollama Cloud no soporta multimodal; evitar misroutear la key a OpenAI.
        return JsonResponse({
            'error': False,
            'respuesta': 'Este agente (Ollama) no procesa imágenes por ahora.',
            'tipo': 'imagen',
        })

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

    # Usa el modelo configurado en la ApiKey; fallback a uno multimodal razonable.
    modelo_cfg = (apikey_obj.modelo or '').strip()
    if provider == 'gemini':
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model=(modelo_cfg or 'gemini-2.0-flash'),
            google_api_key=apikey_obj.descripcion,
        )
    elif provider == 'claude':
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model=(modelo_cfg or 'claude-sonnet-4-5'),
            anthropic_api_key=apikey_obj.descripcion,
        )
    else:
        from langchain_community.chat_models import ChatOpenAI
        llm = ChatOpenAI(
            model_name=(modelo_cfg or 'gpt-4o'),
            openai_api_key=apikey_obj.descripcion,
        )

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
                origen='imagen',
                prompt_preview=(texto_adicional or 'Analisis de imagen')[:300],
            )
    except Exception:
        pass

    return JsonResponse({'error': False, 'respuesta': respuesta, 'tipo': 'imagen'})


def _procesar_audio(tmp_path, filename, texto_adicional, apikey_obj, provider, agente, session_id):
    """Transcribe el audio y lo procesa con el agente RAG."""
    transcripcion = _transcribir_audio(tmp_path, filename, apikey_obj, provider, agente=agente)

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

    fake_conv = SimpleNamespace(id=session_id, contacto=None, contacto_id=None)
    consultor = AgenteConsultor(
        vectorstore_path=vs_path,
        vectorstore_enlaces_path=vectorstore_enlaces_path,
        provider=apikey_obj.proveedor,
        apikey=apikey_obj.descripcion,
        model_name=(apikey_obj.modelo or None),
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
                origen='chat_crm',
                prompt_preview=(pregunta or '')[:300],
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


def _transcribir_audio(tmp_path, filename, apikey_obj=None, provider=None, agente=None) -> str:
    """Transcribe audio usando Whisper local (gratis, sin tokens).
    Antes usaba Gemini multimodal / OpenAI Whisper API — reemplazado por
    el mismo pipeline local que ya usa el webhook de WhatsApp."""
    from whatsapp.transcribe_whatsapp_audio import convert_audio, transcribe_audio, extract_voiced_audio
    wav_file = ''
    voiced_wav = ''
    try:
        wav_file = convert_audio(tmp_path, tmp_path + '.wav')
        voiced_wav = extract_voiced_audio(wav_file, tmp_path + '_voiced.wav')
        return transcribe_audio(voiced_wav, model_size='base', lang='es')
    finally:
        for f in (wav_file, voiced_wav):
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
