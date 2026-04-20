"""API REST para consumir los agentes IA desde sistemas externos.

Permite a cualquier sistema externo enviar una consulta (texto, imagen, audio,
documento) autenticada con una API Key de FastChat y recibir la respuesta del
agente IA en formato JSON.

URL:  POST /api/ia/consultar/
Auth: Header  Authorization: Bearer <WEBSERVICE_TOKEN>
      donde <WEBSERVICE_TOKEN> es el campo ApiKeyIA.webservice_token
      (token dedicado, auto-generado, independiente de la key del proveedor LLM).

Payload: multipart/form-data (si incluye archivos) o application/json (solo texto).

Campos:
  - mensaje      (str, requerido)  — pregunta o prompt en texto.
  - agente_id    (int, opcional)   — ID del AgentesIA a usar. Si no se pasa,
                                     se usa el primer agente que tenga esta key.
  - session_id   (str, opcional)   — ID para mantener contexto de conversacion
                                     entre llamadas (tipo chat multi-turno).
  - archivo      (file, opcional)  — imagen, audio, video o documento adjunto.

Respuesta exitosa (200):
  {
    "error": false,
    "respuesta": "Texto de la respuesta del agente...",
    "tokens": {"entrada": 120, "salida": 85, "total": 205},
    "modelo": "gemini-2.5-flash",
    "session_id": "ext-abc123",
    "tipo_procesado": "texto"
  }

Error (4xx):
  {"error": true, "message": "Descripcion del error", "code": "CODIGO"}
"""
import base64
import json
import logging
import mimetypes
import os
import tempfile
import time

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from core.funciones import rate_limit, get_client_ip
from whatsapp.trazas import registrar as registrar_traza

logger = logging.getLogger(__name__)


@csrf_exempt
@rate_limit(limit=60, seconds=60)
def consultar_ia_view(request):
    if request.method != 'POST':
        return JsonResponse(
            {'error': True, 'message': 'Metodo no permitido. Use POST.', 'code': 'METHOD_NOT_ALLOWED'},
            status=405,
        )

    # ── Auth ──────────────────────────────────────────────────────────
    apikey_obj = _autenticar(request)
    if isinstance(apikey_obj, JsonResponse):
        return apikey_obj

    # Datos de origen del caller (para "quién" usa el webservice)
    client_ip = get_client_ip(request) or ''
    user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:200]
    referer = (request.META.get('HTTP_REFERER') or '')[:200]

    # ── Parsear request ──────────────────────────────────────────────
    mensaje = (request.POST.get('mensaje') or '').strip()
    if not mensaje and request.content_type and 'json' in request.content_type:
        try:
            body = json.loads(request.body.decode('utf-8'))
            mensaje = (body.get('mensaje') or '').strip()
        except Exception:
            pass
    if not mensaje:
        return _error('Campo "mensaje" es requerido.', 'MISSING_FIELD', 400)

    agente_id = request.POST.get('agente_id') or (body.get('agente_id') if 'body' in dir() else None)
    session_id = request.POST.get('session_id') or (body.get('session_id') if 'body' in dir() else None)
    archivo = request.FILES.get('archivo')

    # ── Resolver agente ──────────────────────────────────────────────
    from crm.models import AgentesIA
    if agente_id:
        agente = AgentesIA.objects.filter(pk=agente_id, apikey=apikey_obj, status=True).first()
        if not agente:
            registrar_traza(
                etapa='ws_sin_agente', nivel='warning', apikey=apikey_obj,
                detalle={
                    'apikey_id': apikey_obj.id, 'agente_id_pedido': agente_id,
                    'code': 'AGENT_NOT_FOUND', 'ip': client_ip, 'user_agent': user_agent,
                },
            )
            return _error('Agente no encontrado o no asociado a esta API Key.', 'AGENT_NOT_FOUND', 404)
    else:
        agente = AgentesIA.objects.filter(apikey=apikey_obj, status=True).first()
        if not agente:
            registrar_traza(
                etapa='ws_sin_agente', nivel='warning', apikey=apikey_obj,
                detalle={
                    'apikey_id': apikey_obj.id, 'code': 'NO_AGENT',
                    'ip': client_ip, 'user_agent': user_agent,
                },
            )
            return _error('No hay agentes asociados a esta API Key.', 'NO_AGENT', 404)

    # ── Determinar tipo de procesamiento ─────────────────────────────
    tipo = 'texto'
    if archivo:
        ct = archivo.content_type or ''
        if 'image' in ct:
            tipo = 'imagen'
        elif 'audio' in ct:
            tipo = 'audio'
        elif 'video' in ct:
            tipo = 'video'
        else:
            tipo = 'documento'

    # ── Provider info ────────────────────────────────────────────────
    provider_map = {2: 'gemini', 3: 'openai', 4: 'claude'}
    provider = provider_map.get(apikey_obj.proveedor, 'gemini')
    _default_model = {'gemini': 'gemini-2.5-flash', 'openai': 'gpt-4o-mini', 'claude': 'claude-haiku-4-5-20251001'}
    model_name = apikey_obj.modelo or _default_model.get(provider, 'gemini-2.5-flash')

    registrar_traza(
        etapa='ws_request', nivel='info', apikey=apikey_obj,
        detalle={
            'apikey_id': apikey_obj.id, 'agente_id': agente.id,
            'agente_nombre': agente.nombre, 'tipo': tipo,
            'session_id': session_id or '', 'modelo': model_name,
            'mensaje_preview': mensaje[:300],
            'archivo_nombre': (archivo.name if archivo else ''),
            'archivo_content_type': (archivo.content_type if archivo else ''),
            'ip': client_ip, 'user_agent': user_agent, 'referer': referer,
        },
    )

    t0 = time.time()

    try:
        if tipo == 'texto':
            respuesta_texto, tokens = _procesar_texto(
                mensaje, agente, apikey_obj, provider, model_name, session_id,
            )
        elif tipo == 'imagen':
            respuesta_texto, tokens = _procesar_imagen(
                mensaje, archivo, agente, apikey_obj, provider, model_name,
            )
        elif tipo == 'audio':
            respuesta_texto, tokens = _procesar_audio(
                mensaje, archivo, agente, apikey_obj, provider, model_name,
            )
        else:
            respuesta_texto, tokens = _procesar_texto(
                f"{mensaje}\n\n[Archivo adjunto: {archivo.name}, tipo: {archivo.content_type}]",
                agente, apikey_obj, provider, model_name, session_id,
            )
    except Exception as e:
        logger.exception('API IA: error procesando consulta')
        registrar_traza(
            etapa='ws_error', nivel='error', apikey=apikey_obj,
            detalle={
                'apikey_id': apikey_obj.id, 'agente_id': agente.id, 'tipo': tipo,
                'exc': str(e)[:500], 'modelo': model_name,
                'ip': client_ip, 'user_agent': user_agent,
                'mensaje_preview': mensaje[:300],
            },
            latencia_ms=int((time.time() - t0) * 1000),
        )
        return _error(f'Error interno: {str(e)[:500]}', 'PROCESSING_ERROR', 500)

    latencia_ms = int((time.time() - t0) * 1000)

    registrar_traza(
        etapa='ws_respuesta', nivel='success', apikey=apikey_obj,
        detalle={
            'apikey_id': apikey_obj.id, 'agente_id': agente.id,
            'agente_nombre': agente.nombre, 'tipo': tipo,
            'tokens': tokens, 'modelo': model_name, 'session_id': session_id or '',
            'ip': client_ip, 'user_agent': user_agent,
            'mensaje_preview': mensaje[:300],
            'respuesta_preview': (respuesta_texto or '')[:500],
        },
        latencia_ms=latencia_ms,
    )

    return JsonResponse({
        'error': False,
        'respuesta': respuesta_texto,
        'tokens': tokens,
        'modelo': model_name,
        'session_id': session_id or '',
        'tipo_procesado': tipo,
        'latencia_ms': latencia_ms,
    })


# ══════════════════════════════════════════════════════════════════════
# Autenticacion
# ══════════════════════════════════════════════════════════════════════

def _autenticar(request):
    """Valida el header Authorization: Bearer <webservice_token>.

    Autentica contra el campo ApiKeyIA.webservice_token (token dedicado al
    WebService, separado de la API key del proveedor LLM). Asi la key de
    Gemini/OpenAI nunca se expone en headers HTTP."""
    from crm.models import ApiKeyIA
    auth = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION') or ''
    if not auth.startswith('Bearer '):
        return _error('Header Authorization: Bearer <WEBSERVICE_TOKEN> requerido.', 'AUTH_MISSING', 401)
    token = auth[7:].strip()
    if not token:
        return _error('Token vacio.', 'AUTH_EMPTY', 401)
    apikey = ApiKeyIA.objects.filter(webservice_token=token, estado=True, status=True).first()
    if not apikey:
        return _error('Token de WebService invalido o desactivado.', 'AUTH_INVALID', 401)
    return apikey


# ══════════════════════════════════════════════════════════════════════
# Procesadores por tipo
# ══════════════════════════════════════════════════════════════════════

def _procesar_texto(mensaje, agente, apikey_obj, provider, model_name, session_id=None):
    from agents_ai.agente_consultor import AgenteConsultor
    from core.constantes import PROMPT_TEMPLATES

    vs_path = agente.vectorstore_path and os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path) or ''
    vectorstore_enlaces_path = (
        os.path.join(settings.MEDIA_ROOT, agente.vectorstore_enlaces_path)
        if agente.vectorstore_enlaces_path else ''
    )
    prompt_tpl = (agente.prompt_template or '').strip() or PROMPT_TEMPLATES.get('es', '')

    consultor = AgenteConsultor(
        vectorstore_path=vs_path,
        vectorstore_enlaces_path=vectorstore_enlaces_path,
        provider=provider,
        apikey=apikey_obj.descripcion,
        model_name=model_name,
        conversacion=None,
        prompt_template_text=prompt_tpl,
        contexto_estatico=agente.contexto_estatico or None,
        perfil=agente.perfil,
        agente=agente,
    )

    if agente.requiere_tools():
        resultado = consultor.consultar_con_listas(mensaje, agente.descripcion)
    else:
        resultado = consultor.consultar(mensaje, agente.descripcion)

    tokens = {
        'entrada': getattr(resultado, 'tokens_entrada', 0) or 0,
        'salida': getattr(resultado, 'tokens_salida', 0) or 0,
        'total': getattr(resultado, 'tokens_total', 0) or 0,
    }

    _registrar_consumo(apikey_obj, agente, tokens, model_name, 'webservice', mensaje)

    return resultado.respuesta, tokens


def _procesar_imagen(mensaje, archivo, agente, apikey_obj, provider, model_name):
    b64 = base64.b64encode(archivo.read()).decode('utf-8')
    ct = archivo.content_type or 'image/jpeg'

    if provider == 'gemini':
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=apikey_obj.descripcion)
    elif provider == 'claude':
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=(apikey_obj.modelo or 'claude-sonnet-4-5'), anthropic_api_key=apikey_obj.descripcion)
    else:
        from langchain_community.chat_models import ChatOpenAI
        llm = ChatOpenAI(model_name='gpt-4o', openai_api_key=apikey_obj.descripcion)

    from langchain_core.messages import HumanMessage
    msg = HumanMessage(content=[
        {'type': 'text', 'text': mensaje},
        {'type': 'image_url', 'image_url': {'url': f'data:{ct};base64,{b64}'}},
    ])
    resp = llm.invoke([msg])
    tokens = _extraer_tokens(resp)
    _registrar_consumo(apikey_obj, agente, tokens, model_name, 'imagen', mensaje)
    return resp.content.strip(), tokens


def _procesar_audio(mensaje, archivo, agente, apikey_obj, provider, model_name):
    from whatsapp.transcribe_whatsapp_audio import convert_audio, transcribe_audio, extract_voiced_audio
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(archivo.name)[1] or '.ogg')
    try:
        for chunk in archivo.chunks():
            tmp.write(chunk)
        tmp.close()
        wav = convert_audio(tmp.name, tmp.name + '.wav')
        voiced = extract_voiced_audio(wav, tmp.name + '_voiced.wav')
        transcripcion = transcribe_audio(voiced, model_size='base', lang='es')
    finally:
        for f in (tmp.name, tmp.name + '.wav', tmp.name + '_voiced.wav'):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass

    pregunta = f"{mensaje}\n\n[Transcripcion del audio]: {transcripcion}" if mensaje else transcripcion
    return _procesar_texto(pregunta, agente, apikey_obj, provider, model_name)[0], {
        'entrada': 0, 'salida': 0, 'total': 0,
        'transcripcion': transcripcion,
    }


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _extraer_tokens(resp) -> dict:
    meta = getattr(resp, 'response_metadata', {}) or {}
    usage = (
        getattr(resp, 'usage_metadata', None)
        or meta.get('usage_metadata')
        or meta.get('token_usage')
        or {}
    )
    te = usage.get('input_tokens') or usage.get('prompt_token_count') or usage.get('prompt_tokens') or 0
    ts = usage.get('output_tokens') or usage.get('candidates_token_count') or usage.get('completion_tokens') or 0
    return {'entrada': te, 'salida': ts, 'total': te + ts}


def _registrar_consumo(apikey_obj, agente, tokens, modelo, origen='webservice', prompt_preview=''):
    try:
        from crm.models import ConsumoTokenIA
        from crm.alertas_consumo import verificar_alerta_consumo
        total = tokens.get('total', 0) or 0
        if total:
            ConsumoTokenIA.objects.create(
                apikey=apikey_obj, agente=agente,
                tokens_entrada=tokens.get('entrada', 0),
                tokens_salida=tokens.get('salida', 0),
                tokens_total=total, modelo=modelo,
                origen=origen, prompt_preview=(prompt_preview or '')[:300],
            )
            verificar_alerta_consumo(apikey_obj, total)
    except Exception:
        logger.exception('API IA: error registrando consumo')


def _error(message, code, status):
    return JsonResponse({'error': True, 'message': message, 'code': code}, status=status)
