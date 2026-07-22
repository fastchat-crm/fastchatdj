"""Widget de chat embebible y escalable para cualquier agente IA.

Objetivo: que cualquier pagina (el cotizador, o el sitio de otro cliente) pueda
mostrar un chatbot flotante que conversa con SU agente, manteniendo el hilo, sin
exponer ninguna credencial en el navegador.

Modelo de escalabilidad ("cada cliente su propia pagina con su propia API"):
  - Cada cliente ya tiene su AgentesIA + su ApiKeyIA (con su proveedor y su
    webservice_token secreto). No se crea nada nuevo en BD.
  - Se genera un "embed key" PUBLICO por agente: un token FIRMADO (django.signing)
    que solo contiene el id del agente (y, opcional, los dominios permitidos). Es
    a prueba de manipulacion: el cliente no puede cambiar de agente ni escalar.
  - El navegador nunca ve el webservice_token ni la key del proveedor. Solo maneja
    el embed key. El proxy resuelve server-side el agente + su ApiKeyIA y reusa
    exactamente la misma cadena que /api/ia/consultar/ (RAG + memoria + providers).

Rutas (montadas en /chat-widget/):
  GET  /chat-widget/embed.js            -> el JS del widget (CORS *, portable)
  POST /chat-widget/api/mensaje/        -> proxy de mensajes (CORS *, rate-limited)
  GET  /chat/<embed_key>/               -> pagina de chat autonoma por cliente

El hilo se mantiene con session_id (lo genera y persiste el propio widget en
localStorage), igual que el multi-turno de la API publica.
"""
import json
import logging

from django.core import signing
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.funciones import rate_limit

logger = logging.getLogger(__name__)

_SALT = 'chat-widget-v1'


# ══════════════════════════════════════════════════════════════════════
# Embed key (token firmado, publico, sin BD)
# ══════════════════════════════════════════════════════════════════════

def generar_embed_key(agente_id: int, origins=None) -> str:
    """Devuelve un embed key firmado para un agente.

    origins: lista opcional de dominios permitidos (ej: ['https://cliente.com']).
    Si se define, el proxy solo acepta peticiones cuyo Origin coincida.
    """
    payload = {'a': int(agente_id)}
    if origins:
        payload['o'] = [o.strip().rstrip('/') for o in origins if o.strip()]
    return signing.dumps(payload, salt=_SALT)


def _resolver_embed_key(embed_key: str):
    """Devuelve el payload {'a': agente_id, 'o': [origins]} o None si es invalido."""
    try:
        data = signing.loads((embed_key or '').strip(), salt=_SALT)
        if not isinstance(data, dict) or 'a' not in data:
            return None
        return data
    except signing.BadSignature:
        return None
    except Exception:
        return None


def embed_key_para_empresa(empresa_id) -> str:
    """Embed key del primer agente activo de una empresa (PerfilNegocioIA).
    Vacio si la empresa no tiene agente. Nunca lanza."""
    try:
        from crm.models import AgentesIA
        if not empresa_id:
            return ''
        agente = AgentesIA.objects.filter(perfil_id=empresa_id, status=True).order_by('id').first()
        return generar_embed_key(agente.id) if agente else ''
    except Exception as exc:
        logger.debug('embed_key_para_empresa(%s) fallo: %s', empresa_id, exc)
        return ''


# ══════════════════════════════════════════════════════════════════════
# CORS helper
# ══════════════════════════════════════════════════════════════════════

def _cors(resp, request):
    origin = request.headers.get('Origin') or '*'
    resp['Access-Control-Allow-Origin'] = origin
    resp['Vary'] = 'Origin'
    resp['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    resp['Access-Control-Allow-Headers'] = 'Content-Type'
    resp['Access-Control-Max-Age'] = '86400'
    return resp


def _origen_permitido(payload, request) -> bool:
    """True si el embed key no restringe dominios, o si el Origin/Referer casa."""
    origins = payload.get('o')
    if not origins:
        return True
    origin = (request.headers.get('Origin') or '').rstrip('/')
    if origin and origin in origins:
        return True
    referer = (request.META.get('HTTP_REFERER') or '')
    return any(referer.startswith(o) for o in origins)


# ══════════════════════════════════════════════════════════════════════
# Proxy de mensajes
# ══════════════════════════════════════════════════════════════════════

@csrf_exempt
@rate_limit(limit=40, seconds=60)
def widget_mensaje_view(request):
    """Recibe {embed_key, mensaje, session_id} y responde con el agente.

    Reusa crm.api_ia._procesar_texto: misma cadena RAG + memoria + providers,
    sin duplicar logica. El webservice_token nunca sale del servidor.
    """
    if request.method == 'OPTIONS':
        return _cors(HttpResponse(status=204), request)
    if request.method != 'POST':
        return _cors(JsonResponse({'ok': False, 'error': 'Metodo no permitido.'}, status=405), request)

    try:
        body = json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        body = {}
    embed_key = body.get('embed_key') or request.POST.get('embed_key') or ''
    mensaje = (body.get('mensaje') or request.POST.get('mensaje') or '').strip()
    session_id = (body.get('session_id') or request.POST.get('session_id') or '').strip() or None
    lead_context = body.get('lead_context') if isinstance(body.get('lead_context'), dict) else {}

    payload = _resolver_embed_key(embed_key)
    if not payload:
        return _cors(JsonResponse({'ok': False, 'error': 'Widget no autorizado.'}, status=403), request)
    if not _origen_permitido(payload, request):
        return _cors(JsonResponse({'ok': False, 'error': 'Origen no permitido.'}, status=403), request)
    if not mensaje:
        return _cors(JsonResponse({'ok': False, 'error': 'Mensaje vacio.'}, status=400), request)

    from crm.models import AgentesIA
    from crm.api_ia import _procesar_texto

    agente = AgentesIA.objects.filter(pk=payload['a'], status=True).first()
    if not agente:
        return _cors(JsonResponse({'ok': False, 'error': 'Agente no disponible.'}, status=404), request)
    apikey_obj = agente.apikey.filter(estado=True, status=True).first()
    if not apikey_obj:
        return _cors(JsonResponse({'ok': False, 'error': 'Agente sin API Key activa.'}, status=409), request)

    provider_map = {2: 'gemini', 3: 'openai', 4: 'claude', 5: 'ollama', 8: 'ollama_local'}
    provider = provider_map.get(apikey_obj.proveedor, 'gemini')
    _default_model = {
        'gemini': 'gemini-2.5-flash', 'openai': 'gpt-4o-mini',
        'claude': 'claude-haiku-4-5-20251001', 'ollama': 'gpt-oss:20b',
        'ollama_local': 'llama3.1',
    }
    model_name = apikey_obj.modelo or _default_model.get(provider, 'gemini-2.5-flash')

    try:
        respuesta, tokens = _procesar_texto(
            mensaje, agente, apikey_obj, provider, model_name, session_id,
        )
    except Exception as exc:
        logger.exception('chat-widget: error procesando mensaje')
        return _cors(JsonResponse({'ok': False, 'error': f'Error interno: {str(exc)[:200]}'}, status=500), request)

    # Captura de lead al panel: si el cliente dejó su correo (o teléfono), el lead
    # aterriza en Contactos + Pipeline con el contexto del plan que trae el widget.
    # Nunca rompe la respuesta del chat (registrar_lead degrada silencioso).
    try:
        from crm.lead_panel import registrar_lead, detectar_email, detectar_telefono
        email = detectar_email(mensaje)
        telefono = detectar_telefono(mensaje)
        if (email or telefono) and session_id:
            datos = {k: lead_context.get(k) for k in
                     ('nombre', 'cedula', 'edad', 'genero', 'plan_interes', 'valor_estimado')}
            datos['email'] = email or lead_context.get('email') or ''
            datos['telefono'] = telefono or lead_context.get('telefono') or ''
            datos['mensaje'] = mensaje
            registrar_lead(agente, session_id, **datos)
    except Exception:
        logger.exception('chat-widget: captura de lead falló (no crítico)')

    return _cors(JsonResponse({
        'ok': True,
        'respuesta': respuesta,
        'session_id': session_id or '',
        'tokens': tokens,
    }), request)


# ══════════════════════════════════════════════════════════════════════
# JS del widget (servido por Django: portable, CORS, sin collectstatic)
# ══════════════════════════════════════════════════════════════════════

def embed_js_view(request):
    base = request.build_absolute_uri('/').rstrip('/')
    js = _WIDGET_JS.replace('__ENDPOINT__', base + '/chat-widget/api/mensaje/')
    resp = HttpResponse(js, content_type='application/javascript; charset=utf-8')
    resp['Access-Control-Allow-Origin'] = '*'
    resp['Cache-Control'] = 'public, max-age=300'
    return resp


# ══════════════════════════════════════════════════════════════════════
# Pagina de chat autonoma (una por cliente)
# ══════════════════════════════════════════════════════════════════════

@require_http_methods(['GET'])
def pagina_chat_view(request, embed_key):
    payload = _resolver_embed_key(embed_key)
    if not payload:
        return HttpResponseBadRequest('Widget no autorizado.')
    from crm.models import AgentesIA
    agente = AgentesIA.objects.filter(pk=payload['a'], status=True).first()
    titulo = request.GET.get('titulo') or (agente.nombre if agente else 'Asistente')
    color = request.GET.get('color') or '#1b6ec2'
    bienvenida = request.GET.get('bienvenida') or '¡Hola! ¿En qué puedo ayudarte hoy?'
    return render(request, 'crm/chat_widget_pagina.html', {
        'embed_key': embed_key,
        'titulo': titulo,
        'color': color,
        'bienvenida': bienvenida,
    })


# JS autocontenido, sin dependencias. __ENDPOINT__ se inyecta en embed_js_view.
_WIDGET_JS = r"""
(function(){
  if (window.__vidaChatCargado) return; window.__vidaChatCargado = true;
  var ENDPOINT = "__ENDPOINT__";
  var S = document.currentScript || (function(){var s=document.getElementsByTagName('script');return s[s.length-1];})();
  var cfg = {
    key:   S.getAttribute('data-embed-key') || '',
    titulo:S.getAttribute('data-titulo') || 'Asistente IA',
    color: S.getAttribute('data-color') || '#1b6ec2',
    bienvenida: S.getAttribute('data-bienvenida') || '¡Hola! ¿En qué puedo ayudarte?',
    abierto: S.getAttribute('data-abierto') === 'true'
  };
  if (!cfg.key) { console.warn('[chat-widget] falta data-embed-key'); return; }

  var SKEY = 'cw_session_' + cfg.key.slice(-12);
  var sesion = localStorage.getItem(SKEY);
  if (!sesion) { sesion = 'cw-' + Math.random().toString(36).slice(2) + '-' + (new Date().getTime()); localStorage.setItem(SKEY, sesion); }
  var prefacio = '';
  var leadContext = {};

  function esc(t){var d=document.createElement('div');d.textContent=t;return d.innerHTML;}
  function md(t){
    t = esc(t);
    t = t.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<i>$2</i>');
    t = t.replace(/`([^`]+)`/g,'<code>$1</code>');
    t = t.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
    var lineas = t.split(/\n/), out=[], enLista=false;
    for (var i=0;i<lineas.length;i++){
      var ln=lineas[i];
      if (/^\s*[-*]\s+/.test(ln)) { if(!enLista){out.push('<ul>');enLista=true;} out.push('<li>'+ln.replace(/^\s*[-*]\s+/,'')+'</li>'); }
      else { if(enLista){out.push('</ul>');enLista=false;} out.push(ln.trim()===''?'<br>':'<p>'+ln+'</p>'); }
    }
    if (enLista) out.push('</ul>');
    return out.join('');
  }

  var css = ''
   + '.cww{position:fixed;bottom:22px;right:22px;z-index:2147483000;font-family:"Segoe UI",Roboto,Arial,sans-serif;}'
   + '.cww *{box-sizing:border-box;}'
   + '.cww-bt{width:60px;height:60px;border-radius:50%;border:none;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.25);color:#fff;font-size:26px;display:flex;align-items:center;justify-content:center;transition:transform .15s;}'
   + '.cww-bt:hover{transform:scale(1.06);}'
   + '.cww-panel{position:fixed;bottom:94px;right:22px;width:370px;max-width:calc(100vw - 32px);height:540px;max-height:calc(100vh - 130px);background:#fff;border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.28);display:none;flex-direction:column;overflow:hidden;}'
   + '.cww-panel.open{display:flex;}'
   + '.cww-hd{padding:15px 16px;color:#fff;display:flex;align-items:center;gap:10px;}'
   + '.cww-hd .cww-av{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.25);display:flex;align-items:center;justify-content:center;font-size:18px;}'
   + '.cww-hd .cww-t{font-weight:700;font-size:15px;line-height:1.1;} .cww-hd .cww-s{font-size:11px;opacity:.85;}'
   + '.cww-x{margin-left:auto;background:none;border:none;color:#fff;font-size:22px;cursor:pointer;opacity:.85;}'
   + '.cww-body{flex:1;overflow-y:auto;padding:14px;background:#f5f8fc;}'
   + '.cww-msg{margin:8px 0;display:flex;}'
   + '.cww-msg.u{justify-content:flex-end;}'
   + '.cww-b{max-width:82%;padding:9px 13px;border-radius:14px;font-size:14px;line-height:1.42;white-space:normal;word-wrap:break-word;}'
   + '.cww-b p{margin:0 0 6px;} .cww-b p:last-child{margin:0;} .cww-b ul{margin:4px 0 4px 18px;padding:0;} .cww-b li{margin:2px 0;} .cww-b code{background:rgba(0,0,0,.06);padding:1px 5px;border-radius:5px;font-size:13px;}'
   + '.cww-msg.a .cww-b{background:#fff;color:#13293d;border:1px solid #e6edf5;border-bottom-left-radius:4px;}'
   + '.cww-msg.u .cww-b{color:#fff;border-bottom-right-radius:4px;}'
   + '.cww-dots span{display:inline-block;width:7px;height:7px;margin:0 2px;background:#9fb2c8;border-radius:50%;animation:cwb 1s infinite;}'
   + '.cww-dots span:nth-child(2){animation-delay:.2s;} .cww-dots span:nth-child(3){animation-delay:.4s;}'
   + '@keyframes cwb{0%,60%,100%{opacity:.3;transform:translateY(0);}30%{opacity:1;transform:translateY(-4px);}}'
   + '.cww-ft{display:flex;gap:8px;padding:10px;border-top:1px solid #eef2f7;background:#fff;}'
   + '.cww-in{flex:1;border:1px solid #d6e0ec;border-radius:22px;padding:10px 14px;font-size:14px;outline:none;resize:none;max-height:90px;font-family:inherit;}'
   + '.cww-send{border:none;color:#fff;width:42px;height:42px;border-radius:50%;cursor:pointer;font-size:17px;flex-shrink:0;}'
   + '.cww-send:disabled{opacity:.5;cursor:default;}'
   + '.cww-cred{text-align:center;font-size:10px;color:#a7b4c4;padding:4px;background:#fff;}';
  var st=document.createElement('style'); st.textContent=css; document.head.appendChild(st);

  var root=document.createElement('div'); root.className='cww'; root.innerHTML=''
   + '<button class="cww-bt" style="background:'+cfg.color+'" aria-label="Abrir chat">💬</button>'
   + '<div class="cww-panel">'
   +   '<div class="cww-hd" style="background:'+cfg.color+'">'
   +     '<div class="cww-av">🤖</div>'
   +     '<div><div class="cww-t">'+esc(cfg.titulo)+'</div><div class="cww-s">En línea</div></div>'
   +     '<button class="cww-x" aria-label="Cerrar">×</button>'
   +   '</div>'
   +   '<div class="cww-body"></div>'
   +   '<div class="cww-ft">'
   +     '<textarea class="cww-in" rows="1" placeholder="Escribe tu mensaje..."></textarea>'
   +     '<button class="cww-send" style="background:'+cfg.color+'">➤</button>'
   +   '</div>'
   +   '<div class="cww-cred">Powered by IA</div>'
   + '</div>';
  document.body.appendChild(root);

  var bt=root.querySelector('.cww-bt'), panel=root.querySelector('.cww-panel'),
      body=root.querySelector('.cww-body'), input=root.querySelector('.cww-in'),
      send=root.querySelector('.cww-send'), cerrar=root.querySelector('.cww-x');
  var bienvenidaMostrada=false;

  function scroll(){ body.scrollTop=body.scrollHeight; }
  function burbuja(texto, quien){
    var w=document.createElement('div'); w.className='cww-msg '+(quien==='u'?'u':'a');
    var b=document.createElement('div'); b.className='cww-b';
    if(quien==='u'){ b.style.background=cfg.color; b.textContent=texto; } else { b.innerHTML=md(texto); }
    w.appendChild(b); body.appendChild(w); scroll(); return b;
  }
  function typing(){
    var w=document.createElement('div'); w.className='cww-msg a'; w.setAttribute('data-typing','1');
    w.innerHTML='<div class="cww-b"><div class="cww-dots"><span></span><span></span><span></span></div></div>';
    body.appendChild(w); scroll(); return w;
  }

  function abrir(){
    panel.classList.add('open');
    if(!bienvenidaMostrada){ burbuja(cfg.bienvenida,'a'); bienvenidaMostrada=true; }
    input.focus();
  }
  function toggle(){ panel.classList.contains('open') ? panel.classList.remove('open') : abrir(); }
  bt.addEventListener('click', toggle);
  cerrar.addEventListener('click', function(){ panel.classList.remove('open'); });

  function enviar(){
    var txt=input.value.trim(); if(!txt) return;
    input.value=''; input.style.height='auto';
    burbuja(txt,'u');
    var mensajeReal = prefacio ? (prefacio+'\n\n'+txt) : txt; prefacio='';
    send.disabled=true;
    var t=typing();
    fetch(ENDPOINT,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({embed_key:cfg.key,mensaje:mensajeReal,session_id:sesion,lead_context:leadContext})})
     .then(function(r){return r.json();})
     .then(function(d){ t.remove();
        if(d && d.ok){ burbuja(d.respuesta||'',''); }
        else { burbuja((d&&d.error)||'No pude responder ahora. Intenta de nuevo.',''); }
     })
     .catch(function(){ t.remove(); burbuja('Error de conexión. Intenta de nuevo.',''); })
     .finally(function(){ send.disabled=false; input.focus(); });
  }
  send.addEventListener('click', enviar);
  input.addEventListener('keydown', function(e){ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); enviar(); } });
  input.addEventListener('input', function(){ input.style.height='auto'; input.style.height=Math.min(input.scrollHeight,90)+'px'; });

  window.VidaChat = {
    abrir: abrir,
    cerrar: function(){ panel.classList.remove('open'); },
    setPrefacio: function(t){ prefacio = t || ''; },
    setLeadContext: function(obj){ leadContext = obj || {}; },
    getSessionId: function(){ return sesion; },
    enviar: function(t){ if(t){ input.value=t; enviar(); } },
    nuevaSesion: function(){ sesion='cw-'+Math.random().toString(36).slice(2); localStorage.setItem(SKEY,sesion); body.innerHTML=''; bienvenidaMostrada=false; }
  };
  if (cfg.abierto) abrir();
})();
"""
