"""
crm/motor_flujo_chatbot.py

Motor de ejecución del chatbot TRADICIONAL (árbol/DAG de nodos con APIs,
estilo n8n). Completamente desacoplado del pipeline de IA:
- No importa nada de `agents_ai`.
- No se activa automáticamente: el webhook debe invocar
  `procesar_mensaje_tradicional(...)` sólo cuando
  `SesionWhatsApp.modo_bot in ('tradicional', 'hibrido')`.

El objetivo es que pueda convivir con el agente IA sin interferir:
- `modo_bot == 'ia'`              → se ignora este motor por completo.
- `modo_bot == 'tradicional'`    → sólo corre este motor.
- `modo_bot == 'hibrido'`         → corre primero este motor; si no produce
                                   respuesta, el webhook puede delegar a IA
                                   (ver `ResultadoFlujo.fallback_ia`).
- `modo_bot == 'ninguno'`        → sólo humanos, no se llama.

Entry point:
    resultado = procesar_mensaje_tradicional(session, conversation, contacto, texto)
    if resultado.manejado:
        return      # el motor ya envió respuesta(s)
    if resultado.fallback_ia:
        ...         # modo híbrido sin match → delegar a agente IA
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time as _time
import traceback as _traceback
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


def _notificar_excepcion_chatbot(nodo, conversacion, etapa, error_msg='',
                                  exc=None, traceback_text='', extra=None):
    try:
        from django.conf import settings as _settings
        from django.core.mail import send_mail
        destinatarios = getattr(_settings, 'CHATBOT_ERROR_NOTIFY_EMAILS', None) or []
        if isinstance(destinatarios, str):
            destinatarios = [destinatarios]
        destinatarios = [d for d in destinatarios if d]
        if not destinatarios:
            return
        tb_text = traceback_text or ''
        if not tb_text and exc is not None:
            tb_text = ''.join(_traceback.TracebackException.from_exception(exc).format())
        depto = ''
        contacto_num = ''
        try:
            estado = getattr(conversacion, 'estado_flujo', None)
            depto = getattr(getattr(estado, 'departamento', None), 'nombre', '') or ''
        except Exception:
            pass
        try:
            contacto = getattr(conversacion, 'contacto', None)
            contacto_num = (getattr(contacto, 'numero_telefono', '')
                            or getattr(contacto, 'contacto_numero', '') or '')
        except Exception:
            pass
        if exc is not None and not error_msg:
            error_msg = f'{exc.__class__.__name__}: {exc}'
        lineas = [
            f'Etapa: {etapa}',
            f'Departamento: {depto}',
            f'Conversacion ID: {getattr(conversacion, "id", "?")}',
            f'Contacto: {contacto_num}',
            f'Nodo ID: {getattr(nodo, "id", "?")} ({getattr(nodo, "nombre", "?")})',
            f'Tipo nodo: {getattr(nodo, "tipo", "?")}',
            f'Codigo nodo: {getattr(nodo, "codigo", "?")}',
            f'Error: {error_msg or "(sin mensaje)"}',
        ]
        if extra:
            for k, v in (extra or {}).items():
                try:
                    lineas.append(f'{k}: {v}')
                except Exception:
                    pass
        lineas.extend(['', 'Traceback:', tb_text or '(no disponible)'])
        cuerpo = '\n'.join(lineas)
        asunto = f'[Chatbot] Error nodo {getattr(nodo, "id", "?")} ({etapa})'
        send_mail(
            asunto, cuerpo,
            getattr(_settings, 'DEFAULT_FROM_EMAIL', None) or 'no-reply@localhost',
            destinatarios,
            fail_silently=True,
        )
    except Exception as _e:
        logger.warning('No se pudo enviar mail de error chatbot: %s', _e)

# Tope duro para evitar bucles en la topología del flujo.
MAX_NODOS_POR_TURNO = 25

# Palabras reservadas que reinician el flujo desde cualquier nodo de input.
# El usuario las puede escribir si se queda atascado, en lugar de agotar
# reintentos hasta llegar a handoff.
RESET_KEYWORDS = frozenset({
    'menu', 'menú', 'inicio', 'atras', 'atrás', 'volver', 'salir', 'cancelar',
})


# ─────────────────────────────────────────────────────────────────────
# Resultado
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ResultadoFlujo:
    manejado: bool = False
    fallback_ia: bool = False
    handoff: bool = False
    finalizado: bool = False
    respuestas: list = field(default_factory=list)
    error: str = ''


# ─────────────────────────────────────────────────────────────────────
# Resolver de expresiones {{...}}
# ─────────────────────────────────────────────────────────────────────

_EXPR_RE = re.compile(r'\{\{\s*([^{}]+?)\s*\}\}')
_PATH_TOKEN_RE = re.compile(r'[^.\[\]]+|\[\d+\]')
# Tokens del parser de loops {% for %} ... {% endfor %}. Los matcheamos
# por separado para poder llevar la cuenta del nivel de anidamiento y
# emparejar correctamente cada `for` con su `endfor`.
_FOR_OPEN_RE = re.compile(r'\{%\s*for\s+(\w+)\s+in\s+([^%]+?)\s*%\}')
_FOR_END_RE = re.compile(r'\{%\s*endfor\s*%\}')


def _expandir_fors(texto: str, contexto: dict) -> str:
    """Expande loops `{% for var in path %}...{% endfor %}` en el orden
    correcto: detecta el bloque MÁS EXTERNO, itera sobre la lista del path
    inyectando la variable en un contexto derivado, y resuelve el cuerpo
    recursivamente (los loops internos heredan así la variable del padre).

    Implementación con parser balanceado — la regex sola no puede emparejar
    `for/endfor` anidados.
    """
    while True:
        m_open = _FOR_OPEN_RE.search(texto)
        if not m_open:
            return texto
        depth = 1
        pos = m_open.end()
        end_match = None
        while pos < len(texto):
            next_open = _FOR_OPEN_RE.search(texto, pos)
            next_end = _FOR_END_RE.search(texto, pos)
            if not next_end:
                # Loop sin cierre — abortamos la expansión para no romper.
                return texto
            if next_open and next_open.start() < next_end.start():
                depth += 1
                pos = next_open.end()
            else:
                depth -= 1
                if depth == 0:
                    end_match = next_end
                    break
                pos = next_end.end()
        if end_match is None:
            return texto
        var_name = m_open.group(1)
        path = m_open.group(2).strip()
        body = texto[m_open.end():end_match.start()]
        lista = _get_path(contexto, path)
        if not isinstance(lista, (list, tuple)):
            reemplazo = ''
        else:
            partes = []
            for item in lista:
                sub_ctx = dict(contexto)
                sub_ctx[var_name] = item
                # Recurre vía resolver_expresion: expande loops internos
                # Y sustituye `{{ }}` del body con el contexto actual del
                # item. Sin esto, las variables `{{d.x}}` quedarían sin
                # resolver porque el outer `resolver_expresion` solo ve el
                # contexto sin la var del loop.
                partes.append(resolver_expresion(body, sub_ctx))
            reemplazo = ''.join(partes)
        texto = texto[:m_open.start()] + reemplazo + texto[end_match.end():]


def _get_path(raiz: Any, path: str) -> Any:
    """Navega 'a.b.c' o 'a[0].b' sobre dict/list/atributos de objetos."""
    cur = raiz
    for token in _PATH_TOKEN_RE.findall(path):
        if cur is None:
            return None
        if token.startswith('['):
            try:
                cur = cur[int(token[1:-1])]
            except (IndexError, TypeError, ValueError):
                return None
        else:
            if isinstance(cur, dict):
                cur = cur.get(token)
            else:
                cur = getattr(cur, token, None)
    return cur


def resolver_expresion(valor: Any, contexto: dict) -> Any:
    """
    Reemplaza `{{ruta.a.campo}}` y procesa `{% for x in lista %}...{% endfor %}`
    sobre strings. Recurre sobre dict/list.

    Loops:
      `{% for m in variables.materias %}• {{m.asignatura}} ({{m.docente}})
      {% endfor %}`
      Itera la lista resuelta del path; si la lista no existe o no es lista,
      el loop se expande a string vacío.

    Substitución estándar:
      Si toda la cadena es `{{x}}`, retorna el valor con su tipo original
      (útil para pasar números/bool a JSON body). Si está embebida en texto,
      sustituye a string.
    """
    if isinstance(valor, str):
        valor = _expandir_fors(valor, contexto)

        for _ in range(3):
            m = _EXPR_RE.fullmatch(valor.strip())
            if m:
                resuelto = _get_path(contexto, m.group(1).strip())
                if isinstance(resuelto, str) and _EXPR_RE.search(resuelto):
                    valor = resuelto
                    continue
                return resuelto

            def _repl(mo):
                r = _get_path(contexto, mo.group(1).strip())
                return '' if r is None else str(r)

            nuevo = _EXPR_RE.sub(_repl, valor)
            if nuevo == valor or not _EXPR_RE.search(nuevo):
                return nuevo
            valor = nuevo
        return valor

    if isinstance(valor, dict):
        return {k: resolver_expresion(v, contexto) for k, v in valor.items()}
    if isinstance(valor, list):
        return [resolver_expresion(v, contexto) for v in valor]
    return valor


# ─────────────────────────────────────────────────────────────────────
# Validaciones de entrada del usuario
# ─────────────────────────────────────────────────────────────────────

def _valida_cedula_ec(cedula: str) -> bool:
    if len(cedula) != 10 or not cedula.isdigit():
        return False
    d = [int(c) for c in cedula]
    if d[2] >= 6:
        return False
    coef = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = 0
    for n, c in zip(d[:9], coef):
        p = n * c
        total += p - 9 if p >= 10 else p
    return ((10 - total % 10) % 10) == d[9]


_NUMERO_LIMPIO_RE = re.compile(r'[\s.,]')


def normalizar_numero(texto: str) -> str:
    t = (texto or '').strip()
    if not t:
        return ''
    signo = ''
    if t[0] in '+-':
        signo, t = t[0] if t[0] == '-' else '', t[1:]
    if not t:
        return ''
    has_dot = '.' in t
    has_comma = ',' in t
    if has_dot and has_comma:
        if t.rfind('.') > t.rfind(','):
            t = t.replace(',', '')
        else:
            t = t.replace('.', '').replace(',', '.')
    elif has_dot or has_comma:
        sep = '.' if has_dot else ','
        partes = t.split(sep)
        if all(len(p) == 3 for p in partes[1:]) and len(partes[0]) <= 3 and len(partes) >= 2:
            t = t.replace(sep, '')
        elif sep == ',':
            t = t.replace(',', '.')
    return signo + t


def _normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes y sin espacios sobrantes.

    Sirve para comparar la entrada del cliente contra etiquetas/keywords sin
    que una tilde o una mayúscula rompa la coincidencia: 'informacion' debe
    matchear 'Información', 'BECAS' debe matchear 'becas'.
    """
    t = (texto or '').strip().lower()
    if not t:
        return ''
    t = unicodedata.normalize('NFKD', t)
    return ''.join(c for c in t if not unicodedata.combining(c))


def validar_entrada(tipo: str, expresion: str, texto: str) -> bool:
    t = (texto or '').strip()
    if tipo in ('', 'none', None):
        return True
    if tipo == 'email':
        return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', t))
    if tipo == 'numero':
        n = normalizar_numero(t)
        return bool(re.match(r'^-?\d+(\.\d+)?$', n))
    if tipo == 'telefono':
        return bool(re.match(r'^\+?[\d\s\-]{7,}$', t))
    if tipo == 'fecha':
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', t))
    if tipo == 'cedula':
        return _valida_cedula_ec(t)
    if tipo == 'ruc':
        return len(t) == 13 and t.isdigit()
    if tipo == 'regex':
        try:
            return bool(re.match(expresion or '.*', t))
        except re.error:
            return False
    return True


# ─────────────────────────────────────────────────────────────────────
# Comparadores para `condicional`
# ─────────────────────────────────────────────────────────────────────

def _numeric_or_string(v: Any):
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    return v


def evaluar_condicion(cond: dict, contexto: dict) -> bool:
    izq = resolver_expresion(cond.get('izq', ''), contexto)
    der = resolver_expresion(cond.get('der', ''), contexto)
    op = (cond.get('op') or '==').strip()

    if op in ('vacio', 'no_vacio'):
        ok = not bool(izq)
        return ok if op == 'vacio' else not ok

    if op in ('==', '!='):
        eq = str(izq) == str(der)
        return eq if op == '==' else not eq

    if op in ('>', '<', '>=', '<='):
        a, b = _numeric_or_string(izq), _numeric_or_string(der)
        try:
            if op == '>':  return a > b
            if op == '<':  return a < b
            if op == '>=': return a >= b
            if op == '<=': return a <= b
        except TypeError:
            # Tipos incomparables (ej. número vs texto que no es numérico). No
            # es un error del sistema pero sí una condición mal armada: la
            # dejamos en False y la registramos para poder diagnosticarla.
            logger.warning(
                'Condición %r no comparable: izq=%r der=%r → False', op, izq, der)
            return False

    if op in ('contiene', 'no_contiene'):
        cont = str(der).lower() in str(izq).lower()
        return cont if op == 'contiene' else not cont

    logger.warning('Operador condicional desconocido: %s', op)
    return False


# ─────────────────────────────────────────────────────────────────────
# HTTP runner (nodo tipo `http`)
# ─────────────────────────────────────────────────────────────────────

def _aplicar_credencial(cred, headers: dict, query: dict) -> None:
    if cred is None:
        return
    s = cred.secretos or {}
    tipo = cred.tipo
    if tipo == 'bearer':
        headers['Authorization'] = f"Bearer {s.get('token', '')}"
    elif tipo == 'basic':
        tok = base64.b64encode(
            f"{s.get('usuario', '')}:{s.get('password', '')}".encode()
        ).decode()
        headers['Authorization'] = f'Basic {tok}'
    elif tipo == 'apikey_header':
        headers[s.get('nombre_header', 'X-API-Key')] = s.get('valor', '')
    elif tipo == 'apikey_query':
        query[s.get('nombre_param', 'api_key')] = s.get('valor', '')
    elif tipo == 'custom_header':
        headers.update(s.get('headers') or {})


_CLAVES_SECRETAS = ('api_key', 'apikey', 'api-key', 'token', 'access_token',
                    'key', 'secret', 'password', 'passwd', 'pwd', 'auth', 'signature')


def _redactar_secretos(query):
    """Devuelve una copia de `query` con los valores de parámetros sensibles
    reemplazados por '***', para no persistir credenciales en TrazaMensajeIA."""
    if not isinstance(query, dict):
        return query
    limpio = {}
    for k, v in query.items():
        if any(sec in str(k).lower() for sec in _CLAVES_SECRETAS):
            limpio[k] = '***'
        else:
            limpio[k] = v
    return limpio


def ejecutar_http(nodo, contexto: dict, _traza_extra: Optional[dict] = None):
    """
    Ejecuta un nodo `http`.
    Devuelve (etiqueta, body, status_code, error_str) con etiqueta ∈ {'ok','error'}.

    Si se pasa `_traza_extra` (dict), lo rellena in-place con info de la
    request/response: url, metodo, request_body, response_body — útil para
    persistir en TrazaMensajeIA y diagnosticar.
    """
    ep = nodo.endpoint
    if ep is None:
        return ('error', None, 0, 'Nodo http sin endpoint configurado')

    cfg = nodo.config or {}
    metodo = (cfg.get('metodo') or 'GET').upper()
    path = resolver_expresion(cfg.get('path') or '', contexto) or ''
    url = (ep.base_url or '').rstrip('/') + '/' + str(path).lstrip('/')
    query = resolver_expresion(cfg.get('query') or {}, contexto) or {}
    body = resolver_expresion(cfg.get('body') or None, contexto)
    headers = dict(ep.headers_default or {})
    # Headers extra definidos en el nodo (ej: Referer requerido por CSRF Django)
    headers.update(resolver_expresion(cfg.get('headers') or {}, contexto) or {})
    _aplicar_credencial(ep.credencial, headers, query)

    # Elegir serialización del body según Content-Type:
    #   - application/x-www-form-urlencoded  → data=  (request.POST en Django)
    #   - multipart/form-data                → data=  (sin boundary explicit)
    #   - application/json (o no especificado) → json= (default histórico)
    body_kwargs = {}
    if metodo in ('POST', 'PUT', 'PATCH') and body is not None:
        ct = ''
        for k, v in headers.items():
            if k.lower() == 'content-type':
                ct = (v or '').lower()
                break
        if 'x-www-form-urlencoded' in ct or 'multipart/form-data' in ct:
            body_kwargs['data'] = body
        else:
            body_kwargs['json'] = body

    if _traza_extra is not None:
        _traza_extra.update({
            'url': url, 'metodo': metodo,
            'query': _redactar_secretos(query), 'request_body': body,
        })

    # Timeout: prefiere el del nodo (cfg.timeout_seg) si está definido — útil
    # cuando un POST específico (ej. /cotizar/) toma más que el resto y no
    # quieres subir el timeout global del endpoint.
    timeout_eff = int(cfg.get('timeout_seg') or ep.timeout_seg or 15)

    try:
        resp = requests.request(
            metodo, url,
            headers=headers,
            params=query or None,
            timeout=timeout_eff,
            **body_kwargs,
        )
    except Exception as e:
        if _traza_extra is not None:
            _traza_extra['exception'] = f'{e.__class__.__name__}: {e}'
            _traza_extra['traceback'] = _traceback.format_exc()
        return ('error', None, 0, f'{e.__class__.__name__}: {e}')

    try:
        parsed = resp.json()
    except ValueError:
        parsed = {'_raw': resp.text}

    if _traza_extra is not None:
        _traza_extra['response_body'] = parsed

    if 200 <= resp.status_code < 300:
        # Convención común: API responde 200 con `success/result: false` para
        # errores de negocio (no encontrado, validación, etc.). Tratamos eso
        # como 'error' para que el flujo enrute a la rama de fallback en lugar
        # de avanzar como si todo estuviera bien.
        if isinstance(parsed, dict):
            biz_ok = parsed.get('success', parsed.get('result', True))
            if biz_ok is False:
                msg = (parsed.get('message') or parsed.get('msg')
                       or parsed.get('error') or 'Respuesta de negocio negativa')
                return ('error', parsed, resp.status_code, str(msg)[:200])
        return ('ok', parsed, resp.status_code, '')
    return ('error', parsed, resp.status_code, f'HTTP {resp.status_code}')


# ─────────────────────────────────────────────────────────────────────
# Motor
# ─────────────────────────────────────────────────────────────────────

class MotorFlujo:
    def __init__(self, session, conversation, contacto, texto, estado, ws_service, boton_id='',
                 skip_side_effects=False):
        self.session = session
        self.conversation = conversation
        self.contacto = contacto
        self.texto = (texto or '').strip()
        # boton_id (Meta interactive button_reply.id / list_reply.id) — cuando
        # el cliente toca un botón, llega acá para matchear contra
        # OpcionDepartamentoChatBot.boton_id sin depender del texto del título.
        self.boton_id = (boton_id or '').strip()
        self.estado = estado
        self.ws = ws_service
        self.respuestas: list[str] = []
        self.handoff = False
        self.finalizado = False
        # `skip_side_effects=True` desactiva los efectos colaterales no
        # cliente-facing del flujo (envío de correo a asesores, etc.). Lo usa
        # el simulador `/prueba/` cuando el operador tilda "modo dry-run"
        # para iterar sin spamear. Por defecto OFF: en una conv real siempre
        # se disparan los side-effects configurados en cada nodo.
        self.skip_side_effects = bool(skip_side_effects)
        # True cuando _elegir_departamento determina que hay >1 depto activo y
        # ninguno matcheó → caller debe presentar meta-menú al usuario.
        self.pendiente_seleccion = False
        self._hijo_menu_elegido = None
        # Timeline de trazabilidad — lista de dicts consumida por las vistas de prueba.
        # Se popula siempre (overhead despreciable) para permitir debugging en prod.
        self.trace: list[dict] = []
        self._trace_t0 = _time.time()

    def _trace(self, etapa: str, label: str, ok: bool = True, detalle: Optional[dict] = None):
        """Agrega una entrada al timeline del motor."""
        self.trace.append({
            'etapa': etapa,
            'label': label,
            'ok': bool(ok),
            'detalle': detalle or {},
            'ts_ms': int((_time.time() - self._trace_t0) * 1000),
        })

    def _traza_db(self, etapa_db: str, label: str, ok: bool, detalle: Optional[dict] = None,
                  latencia_ms: Optional[int] = None):
        """Persiste un evento al modelo TrazaMensajeIA.

        Solo se llama para eventos importantes (http, ruteo, errores) — no para
        cada transición de nodo. La idea es que /whatsapp/trazas/ refleje el
        flujo del chatbot tradicional igual que el del pipeline IA.
        """
        try:
            from whatsapp.models import TrazaMensajeIA
            nivel = 'info' if ok else 'error'
            partes = [label]
            if detalle:
                # Serializa el detalle pero acota el body de la response a 1500
                # chars para que la fila no se vuelva enorme.
                d = dict(detalle)
                rb = d.get('response_body')
                if rb is not None:
                    try:
                        rb_str = json.dumps(rb, ensure_ascii=False)
                    except (TypeError, ValueError):
                        rb_str = str(rb)
                    d['response_body'] = rb_str[:1500] + ('…' if len(rb_str) > 1500 else '')
                qb = d.get('request_body')
                if qb is not None:
                    try:
                        qb_str = json.dumps(qb, ensure_ascii=False)
                    except (TypeError, ValueError):
                        qb_str = str(qb)
                    d['request_body'] = qb_str[:500] + ('…' if len(qb_str) > 500 else '')
                partes.append(json.dumps(d, ensure_ascii=False, default=str))
            TrazaMensajeIA.objects.create(
                sesion=self.session,
                conversacion=self.conversation,
                numero=self.contacto.from_number,
                etapa=etapa_db,
                nivel=nivel,
                detalle=' | '.join(partes)[:4000],
                latencia_ms=latencia_ms,
            )
        except Exception:
            logger.exception('Error persistiendo traza chatbot')

    # ── Contexto de expresiones ──────────────────────────────────────

    def contexto(self, extra: Optional[dict] = None) -> dict:
        ctx = {
            'variables': dict(self.estado.variables or {}),
            'contacto': {
                'numero': self.contacto.from_number,
                'nombre': (self.contacto.contacto_nombre or '').strip(),
            },
            'conversacion': {'id': self.conversation.id},
            'sesion': {
                'numero': self.session.numero,
                'nombre': self.session.nombre,
                'session_id': self.session.session_id,
            },
            'mensaje': {'texto': self.texto},
        }
        if extra:
            ctx.update(extra)
        return ctx

    # ── I/O ──────────────────────────────────────────────────────────

    def enviar(self, texto: str):
        if not texto:
            return
        resuelto = resolver_expresion(texto, self.contexto())
        try:
            r = self.ws.send_text_message(
                self.session.session_id,
                self.contacto.from_number,
                resuelto,
                self.conversation.id,
                True,
            )
            self.respuestas.append(resuelto)
            self._persistir_mensaje_saliente(resuelto, r)
            self._trace('envio', 'Mensaje enviado', True,
                        {'preview': resuelto[:160], 'chars': len(resuelto)})
        except Exception as e:
            logger.exception('Error enviando mensaje tradicional: %s', e)
            self._trace('envio', 'Error al enviar', False, {'error': str(e)[:200]})

    def _persistir_mensaje_saliente(self, texto: str, response: dict | None = None):
        """Guarda el mensaje saliente en MensajeWhatsApp para que aparezca
        en /whatsapp/conversaciones/<id>/. Sin esto el motor manda al cliente
        pero el historial queda en blanco."""
        try:
            from whatsapp.models import MensajeWhatsApp
            from django.utils import timezone
            msg_id_ext = ''
            if isinstance(response, dict):
                msg_id_ext = response.get('message_id') or ''
                # MetaWhatsAppService a veces devuelve dict con messages: [{'id':...}]
                if not msg_id_ext and 'messages' in response:
                    try:
                        msg_id_ext = response['messages'][0].get('id', '')
                    except Exception:
                        pass
            MensajeWhatsApp.objects.create(
                conversacion=self.conversation,
                remitente=self.session.numero or '',
                mensaje=texto,
                tipo='texto',
                fecha=timezone.now(),
                mensaje_id_externo=msg_id_ext or None,
                leido=True,
                fecha_leido=timezone.now(),
                es_automatico=True,
            )
        except Exception as ex:
            logger.warning('Motor: no pude persistir saliente: %s', ex)

    def _enviar_cta_url(self, body_text: str, url: str, display_text: str = 'Abrir') -> bool:
        """Envía un botón CTA URL (Meta interactive cta_url). Si la sesión NO es
        Meta, fallback a mandar el texto + el link en línea (Baileys no soporta CTA)."""
        body_resuelto = resolver_expresion(body_text or '', self.contexto())
        if not getattr(self.session, 'es_meta', False):
            self.enviar(body_resuelto + (f"\n\n👉 {url}" if url else ''))
            return False
        try:
            resp = self.ws.send_interactive_cta_url(
                self.session.session_id,
                self.contacto.from_number,
                body_resuelto,
                url=url,
                display_text=(display_text or 'Abrir')[:20],
                conversacion_id=self.conversation.id,
            )
            ok = bool((resp or {}).get('success'))
            self.respuestas.append(body_resuelto)
            if ok:
                # Persistir con el link entre corchetes para auditoría
                self._persistir_mensaje_saliente(
                    body_resuelto + f"\n[CTA: {display_text} → {url}]", resp,
                )
            self._trace('envio_cta_url', 'CTA URL enviado', ok, {
                'url': url[:200], 'display_text': display_text,
                'error': (resp or {}).get('error', '') if not ok else '',
            })
            return ok
        except Exception as e:
            logger.exception('Error enviando CTA URL: %s', e)
            self._trace('envio_cta_url', 'Error', False, {'error': str(e)[:200]})
            self.enviar(body_resuelto + f"\n\n👉 {url}")
            return False

    def enviar_menu_interactivo(self, body_text: str, opciones: list,
                                 header: str = None, footer: str = None) -> bool:
        """Envía un menú con botones (≤3) o lista (≤10) si la sesión es Meta.
        Devuelve True si pudo mandar interactivo, False si tuvo que caer a texto.

        opciones: lista de dicts [{'id': 'opt_id', 'title': 'Texto botón'}, ...]
        """
        if not opciones:
            return False
        if not getattr(self.session, 'es_meta', False):
            # Baileys no soporta interactivos → fallback texto numerado.
            lineas = [body_text or 'Elige una opción:']
            for i, op in enumerate(opciones, start=1):
                lineas.append(f"{i}. {op.get('title', '')}")
            self.enviar('\n'.join(lineas))
            return False
        # Meta: button (≤3) o list (≤10)
        body_resuelto = resolver_expresion(body_text or 'Elige una opción:', self.contexto())
        try:
            if len(opciones) <= 3:
                resp = self.ws.send_interactive_buttons(
                    self.session.session_id, self.contacto.from_number,
                    body_resuelto, opciones,
                    header_text=header, footer_text=footer,
                    conversacion_id=self.conversation.id,
                )
            else:
                # Limitar a 10 ítems (regla Meta).
                from meta.whatsapp import titulo_boton_interactivo
                rows = [{'id': o['id'], 'title': titulo_boton_interactivo(o.get('title'), limite=24),
                         'description': (o.get('description') or '')[:72]}
                        for o in opciones[:10] if o.get('id')]
                resp = self.ws.send_interactive_list(
                    self.session.session_id, self.contacto.from_number,
                    body_resuelto,
                    sections=[{'title': 'Opciones', 'rows': rows}],
                    button_text='Ver opciones',
                    header_text=header, footer_text=footer,
                    conversacion_id=self.conversation.id,
                )
            ok = bool((resp or {}).get('success'))
            self.respuestas.append(body_resuelto)
            if ok:
                # Persistir el body del menú interactivo en historial.
                # Los botones/items quedan implícitos en el preview de las
                # opciones (son audit suficiente desde la traza).
                preview_opts = ' · '.join(o.get('title', '') for o in opciones[:5])
                texto_log = body_resuelto + (f"\n[Opciones: {preview_opts}]" if preview_opts else '')
                self._persistir_mensaje_saliente(texto_log, resp)
            self._trace('envio_interactivo', 'Menú interactivo enviado', ok, {
                'tipo': 'button' if len(opciones) <= 3 else 'list',
                'opciones': len(opciones),
                'error': (resp or {}).get('error', '') if not ok else '',
            })
            return ok
        except Exception as e:
            logger.exception('Error enviando menú interactivo: %s', e)
            self._trace('envio_interactivo', 'Error', False, {'error': str(e)[:200]})
            # Fallback a texto si falla
            self.enviar(body_resuelto + '\n\n' +
                        '\n'.join(f"{i+1}. {o.get('title','')}" for i, o in enumerate(opciones)))
            return False

    # ── Routing ──────────────────────────────────────────────────────

    def _departamentos_activos(self) -> list:
        """Lista ordenada de deptos activos en la sesión (resultado puntual, no cacheado)."""
        return list(
            self.session.departamentos
            .filter(status=True, activo_tradicional=True)
            .order_by('id')
        )

    def _elegir_departamento(self):
        deptos = self._departamentos_activos()
        txt = _normalizar_texto(self.texto)

        # 1) palabras clave (sin tildes ni mayúsculas, para no fallar por acentos)
        for d in deptos:
            palabras = d.get_palabras_clave()
            if palabras and any((np := _normalizar_texto(p)) and np in txt for p in palabras):
                return d

        # 2) selector numérico (compat con el menú clásico de departamentos)
        if txt.isdigit():
            idx = int(txt) - 1
            if 0 <= idx < len(deptos):
                return deptos[idx]

        # 3) default de la sesión: si está configurado, gana sobre la
        # ambigüedad. La idea: M2M provee opciones para keyword-routing,
        # pero el default es la "puerta de entrada" cuando nada matchea.
        dd = getattr(self.session, 'departamento_default', None)
        if dd and dd.status and dd.activo_tradicional:
            return dd

        # 4) default marcado en algún depto del M2M
        elegido = next((d for d in deptos if getattr(d, 'es_default', False)), None)
        if elegido:
            return elegido

        # 5) Ambigüedad: >1 depto y no hay default ni keyword match → meta-menú.
        if len(deptos) > 1:
            self.pendiente_seleccion = True
            return None

        # 6) Único depto en M2M sin default explícito → úsalo.
        if len(deptos) == 1:
            return deptos[0]

        return None

    def _avanzar(self, etiqueta: str):
        hijo_especifico = getattr(self, '_hijo_menu_elegido', None)
        self._hijo_menu_elegido = None
        nodo = self.estado.nodo_actual
        if not nodo:
            return None
        conn = nodo.salidas.filter(status=True, etiqueta=etiqueta).order_by('orden').first()
        if conn:
            return conn.nodo_destino
        # Fallback legacy: árbol por opcion_padre cuando la etiqueta es default
        if etiqueta == '':
            # Menú de varias opciones elegido por texto/número: navegar al hijo
            # elegido puntualmente, no al primero del árbol.
            if hijo_especifico:
                esp = nodo.subopciones.filter(status=True, id=hijo_especifico).first()
                if esp:
                    return esp
            return nodo.subopciones.filter(status=True).order_by('orden').first()
        # Si no hay conexión específica, caer a la default
        conn_def = nodo.salidas.filter(status=True, etiqueta='').order_by('orden').first()
        return conn_def.nodo_destino if conn_def else None

    # ── Anti-rebobinado (botones viejos de WhatsApp) ─────────────────

    def _destinos_directos(self, nodo) -> set:
        """IDs de nodos directamente alcanzables desde `nodo` (aristas de salida
        + subopciones legacy). Sirve para distinguir un botón legítimo del nodo
        actual de un botón viejo de un menú anterior."""
        ids = set()
        if not nodo:
            return ids
        for c in nodo.salidas.filter(status=True):
            if c.nodo_destino_id:
                ids.add(c.nodo_destino_id)
        for h in nodo.subopciones.filter(status=True):
            ids.add(h.id)
        return ids

    def _marcar_historial(self, nodo):
        """Registra el nodo en el historial de visitados de la conversación.
        Lo usa la guarda anti-rebobinado: si el cliente toca un botón viejo del
        chat de WhatsApp cuyo nodo YA pasó, el flujo no se reinicia desde ahí."""
        if not nodo:
            return
        hist = list((self.estado.variables or {}).get('__historial') or [])
        if hist and hist[-1] == nodo.id:
            return
        hist.append(nodo.id)
        if len(hist) > 100:
            hist = hist[-100:]
        self.estado.set_variable('__historial', hist)
        self.estado.save()

    # ── Reset configurable por depto ─────────────────────────────────

    def _reiniciar_flujo_depto(self, depto):
        """Limpia variables y vuelve al `nodo_inicio` del depto.
        Si el depto tiene `mensaje_reset`, lo envía antes de procesar el inicio.
        Genérico — aplica a cualquier flujo/negocio (cotizador, soporte, etc.).
        """
        nodo_anterior_id = getattr(self.estado.nodo_actual, 'id', None)
        nodo_inicio = depto.nodo_inicio()

        self._trace(
            'reset_depto',
            f'Reset por trigger ("{self.texto[:60]}") en depto "{depto.nombre}"',
            True,
            {'nodo_anterior_id': nodo_anterior_id,
             'nodo_inicio_id': getattr(nodo_inicio, 'id', None)},
        )

        self.estado.departamento = depto
        self.estado.nodo_actual = nodo_inicio
        self.estado.intentos = 0
        self.estado.variables = {}
        self.estado.finalizado = False
        self.estado.save()

        # Mensaje de reset (opcional). Soporta {{variables.x}} y {{contacto.numero}}.
        msg_reset = (depto.mensaje_reset or '').strip()
        if msg_reset:
            try:
                msg_reset = resolver_expresion(msg_reset, self.contexto()) or msg_reset
            except Exception:
                pass
            self.enviar(msg_reset)

        # Procesar el nodo de inicio sin consumir el mensaje del cliente
        # (el mensaje ya fue interpretado como trigger, no como respuesta).
        if nodo_inicio:
            self._run_loop(consumir_mensaje=False)

    # ── Loop principal ───────────────────────────────────────────────

    def ejecutar(self):
        self._trace('inicio', 'Mensaje recibido', True, {
            'texto': self.texto[:160],
            'primer_turno': not bool(self.estado.nodo_actual),
            'boton_id': self.boton_id,
        })

        variables = self.estado.variables or {}

        # 0a) Salto directo por boton_id (Meta interactive). Si el cliente tocó
        #     un botón que existe en CUALQUIER nodo del depto, saltamos ahí
        #     directo. Resuelve el caso "elegí transferencia, terminé esa rama,
        #     y ahora elijo tarjeta-crédito" — el motor estaría en raíz y no
        #     reconocería el botón sin este atajo.
        if self.boton_id:
            from .models import OpcionDepartamentoChatBot as _Op
            depto_actual = self.estado.departamento or self.session.departamento_default
            objetivo = None
            if depto_actual:
                objetivo = _Op.objects.filter(
                    departamento=depto_actual, status=True, boton_id=self.boton_id,
                ).first()
                if not objetivo and self.boton_id.startswith('op_'):
                    try:
                        op_id = int(self.boton_id.split('_', 1)[1])
                        objetivo = _Op.objects.filter(
                            departamento=depto_actual, id=op_id, status=True,
                        ).first()
                    except (ValueError, IndexError):
                        pass
            if objetivo:
                # Anti-rebobinado: si el botón apunta a un nodo que YA pasó (está
                # en el historial) y NO es alcanzable desde el nodo actual, es un
                # botón viejo del chat de WhatsApp. No reiniciar el flujo desde
                # ahí — reorientar al cliente al punto donde va.
                historial = (self.estado.variables or {}).get('__historial') or []
                actual_id = getattr(self.estado.nodo_actual, 'id', None)
                if (objetivo.id != actual_id and objetivo.id in historial
                        and objetivo.id not in self._destinos_directos(self.estado.nodo_actual)):
                    self._trace('boton_obsoleto',
                                f'Botón obsoleto ignorado: "{objetivo.nombre}" ya fue visitado',
                                True, {'boton_id': self.boton_id, 'destino_id': objetivo.id,
                                       'actual_id': actual_id})
                    nodo_actual = self.estado.nodo_actual
                    if nodo_actual and nodo_actual.tipo_nodo in ('menu', 'pregunta'):
                        self.enviar('Esa opción ya la procesamos. Sigamos por aquí:')
                        self._presentar_nodo_input(nodo_actual)
                    return
                self._trace('salto_boton_id', f'Salto directo a "{objetivo.nombre}"',
                            True, {'boton_id': self.boton_id, 'destino_id': objetivo.id,
                                   'desde_id': getattr(self.estado.nodo_actual, 'id', None)})
                self.estado.departamento = depto_actual
                self.estado.nodo_actual = objetivo
                self.estado.intentos = 0
                self.estado.save()
                # Procesar el nodo destino directamente. Si es 'respuesta', envía
                # y avanza. Si es 'menu', presenta opciones y espera.
                self._run_loop(consumir_mensaje=False)
                return

        # 0) Comando de reset configurable POR DEPTO. Cualquier flujo (cotizador,
        #    soporte, ventas) puede definir su propia lista de triggers en
        #    `DepartamentoChatBot.reset_triggers`. Si el cliente envía uno
        #    estando dentro del depto, el motor reinicia el flujo desde el
        #    nodo de inicio del MISMO depto (no rerutea), limpia variables y
        #    opcionalmente envía `mensaje_reset`. Funciona igual con texto
        #    libre o con valor de botón (Meta interactive).
        depto_actual_reset = self.estado.departamento or (
            self.session.departamento_default if self.session else None
        )
        if (
            self.estado.nodo_actual
            and depto_actual_reset
            and depto_actual_reset.es_trigger_reset(self.texto)
        ):
            self._reiniciar_flujo_depto(depto_actual_reset)
            return

        # 0.1) Reset GLOBAL legacy (palabras hardcoded, fuera del depto):
        #      vuelve al meta-menú de deptos. Se mantiene para no romper UX
        #      existente cuando no hay reset_triggers configurados.
        if (self.estado.nodo_actual or variables.get('__esperando_depto')) \
                and self.texto.lower().strip() in RESET_KEYWORDS:
            self._trace('reset_keyword', f'Reset solicitado por "{self.texto}"', True,
                        {'nodo_anterior_id': getattr(self.estado.nodo_actual, 'id', None)})
            self.estado.nodo_actual = None
            self.estado.departamento = None
            self.estado.intentos = 0
            self.estado.variables = {}
            self.estado.save()
            variables = {}

        # 0.5) Estado virtual: el turno previo presentó el meta-menú de deptos
        #      y este mensaje contiene la selección.
        if variables.get('__esperando_depto'):
            self._resolver_seleccion_depto()
            return

        # 1) Primer turno de la conversación → elegir depto + nodo inicio
        if not self.estado.nodo_actual:
            depto = self._elegir_departamento()
            if not depto:
                # Ambigüedad: hay >1 depto y ninguno matcheó → presentar meta-menú.
                if self.pendiente_seleccion:
                    self._presentar_meta_menu_depto()
                    return
                self._trace('ruteo', 'Sin match — ningún departamento elegible', False,
                            {'razon': 'No hay palabras clave coincidentes ni default configurado'})
                return  # no hubo match → caller decide (p.ej. fallback IA)
            self._trace('ruteo', f'Departamento elegido: {depto.nombre}', True,
                        {'departamento_id': depto.id, 'nombre': depto.nombre,
                         'es_default': bool(getattr(depto, 'es_default', False))})
            self._traza_db(
                etapa_db='chatbot_ruteo',
                label=f'Departamento elegido: {depto.nombre}',
                ok=True,
                detalle={
                    'departamento_id': depto.id,
                    'es_default': bool(getattr(depto, 'es_default', False)),
                    'texto_entrada': self.texto[:120],
                },
            )
            self.estado.departamento = depto
            if depto.mensaje_saludo:
                self.enviar(depto.mensaje_saludo)
            self.estado.nodo_actual = depto.nodo_inicio()
            self.estado.intentos = 0
            self.estado.save()
            if not self.estado.nodo_actual:
                self._trace('nodo_inicio', 'El departamento no tiene nodo de inicio configurado',
                            False, {'departamento_id': depto.id})
                return
            self._run_loop(consumir_mensaje=False)
            return

        # 2) Ya había un nodo esperando input
        nodo = self.estado.nodo_actual
        self._trace('retomar', f'Retomando en nodo {nodo.nombre}', True, {
            'nodo_id': nodo.id, 'tipo': nodo.tipo_nodo,
        })
        self._run_loop(consumir_mensaje=True)

    # ── Meta-menú de selección de departamento ──────────────────────

    def _presentar_meta_menu_depto(self):
        """Muestra al usuario los departamentos disponibles y deja un flag para
        que el siguiente turno sea interpretado como selección."""
        deptos = self._departamentos_activos()
        lineas = ['¿Con qué departamento te puedo ayudar?']
        for i, d in enumerate(deptos, 1):
            lineas.append(f'{i}. {d.nombre}')
        self.enviar('\n'.join(lineas))
        self.estado.set_variable('__esperando_depto', True)
        self.estado.save()
        self._trace('meta_menu_depto', 'Meta-menú de departamentos presentado',
                    True, {'opciones': len(deptos)})

    def _resolver_seleccion_depto(self):
        """Interpreta el mensaje del usuario como selección del meta-menú,
        asigna el departamento y arranca su nodo de inicio."""
        deptos = self._departamentos_activos()
        t = self.texto.strip()
        t_norm = _normalizar_texto(t)
        elegido = None

        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(deptos):
                elegido = deptos[idx]
        if not elegido and t_norm:
            for d in deptos:
                dn = _normalizar_texto(d.nombre)
                if dn == t_norm or t_norm in dn:
                    elegido = d
                    break

        if not elegido:
            self.estado.intentos = (self.estado.intentos or 0) + 1
            self._trace('meta_menu_invalido',
                        f'Selección "{t}" no coincide con ningún depto',
                        False, {'intentos': self.estado.intentos,
                                'opciones_disponibles': len(deptos)})
            if self.estado.intentos >= 3:
                # 3 intentos fallidos → limpiar flag y reintentar ruteo normal
                # en el siguiente mensaje (mejor que dejar al usuario atascado).
                self.estado.set_variable('__esperando_depto', False)
                self.estado.intentos = 0
                self.estado.save()
                self.enviar('Demasiados intentos. Escribe *menu* para empezar de nuevo.')
                return
            self.estado.save()
            self.enviar('Opción no válida. Responde con el *número* del departamento.')
            return

        # Limpiar flag y arrancar el flujo del depto elegido.
        self.estado.set_variable('__esperando_depto', False)
        self.estado.departamento = elegido
        self.estado.intentos = 0
        if elegido.mensaje_saludo:
            self.enviar(elegido.mensaje_saludo)
        self.estado.nodo_actual = elegido.nodo_inicio()
        self.estado.save()
        self._trace('meta_menu_seleccion', f'Departamento elegido: {elegido.nombre}',
                    True, {'departamento_id': elegido.id, 'nombre': elegido.nombre})
        if not self.estado.nodo_actual:
            self._trace('nodo_inicio',
                        'El departamento elegido no tiene nodo de inicio configurado',
                        False, {'departamento_id': elegido.id})
            return
        self._run_loop(consumir_mensaje=False)

    # ── Loop principal ───────────────────────────────────────────────

    def _run_loop(self, consumir_mensaje: bool):
        pasos = 0
        while self.estado.nodo_actual and not self.finalizado and not self.handoff:
            pasos += 1
            if pasos > MAX_NODOS_POR_TURNO:
                logger.error('Loop detectado en flujo conv#%s', self.conversation.id)
                self._trace('bucle', f'Loop detectado — cortado en {pasos} pasos', False,
                            {'max': MAX_NODOS_POR_TURNO})
                self.enviar('⚠️ El flujo entró en un bucle. Contacta a soporte.')
                return

            nodo = self.estado.nodo_actual
            self._marcar_historial(nodo)
            tipo = nodo.tipo_nodo
            pide_input = tipo in ('pregunta', 'menu')

            if pide_input and not consumir_mensaje:
                self._trace('nodo_pide_input', f'Presentando {tipo} "{nodo.nombre}"', True,
                            {'nodo_id': nodo.id, 'tipo': tipo})
                self._presentar_nodo_input(nodo)
                return

            self._trace('nodo_procesar', f'Procesando {tipo} "{nodo.nombre}"', True, {
                'nodo_id': nodo.id, 'tipo': tipo, 'consume_msg': consumir_mensaje,
            })
            etiqueta = self._procesar_nodo(nodo, consumir_mensaje=consumir_mensaje)
            consumir_mensaje = False  # sólo el primer nodo consume el mensaje
            self._notificar_asesor_nodo(nodo)
            if self.handoff or self.finalizado:
                return
            if etiqueta is None:
                # Nodo pidió reintento (ej. validación falló) → no avanzar
                self._trace('nodo_reintento', f'Nodo "{nodo.nombre}" pidió reintento',
                            True, {'intentos': self.estado.intentos})
                return
            siguiente = self._avanzar(etiqueta)
            self._trace('nodo_avance', f'Avance por etiqueta "{etiqueta}"', bool(siguiente), {
                'desde_id': nodo.id, 'etiqueta': etiqueta,
                'siguiente_id': siguiente.id if siguiente else None,
                'siguiente_nombre': getattr(siguiente, 'nombre', None),
            })
            if siguiente is None and etiqueta == 'timeout':
                # Se agotaron los reintentos y el nodo no tiene salida 'timeout'
                # configurada → handoff en vez de dejar al cliente en silencio.
                self._trace('timeout_sin_arista',
                            'Reintentos agotados sin salida "timeout" → handoff',
                            True, {'desde_id': nodo.id})
                self._forzar_handoff('reintentos_agotados')
                return
            self.estado.nodo_actual = siguiente
            self.estado.intentos = 0
            self.estado.save()

    # ── Handoff forzado (sin nodo handoff) ───────────────────────────

    def _forzar_handoff(self, motivo='timeout', mensaje=None):
        """Transfiere a un agente humano sin requerir un nodo `handoff`.
        Se usa cuando se agotan los reintentos y el flujo no tiene una salida
        'timeout' — evita dejar al cliente atascado en silencio."""
        msg = (mensaje or getattr(self.session, 'mensaje_handoff', '')
               or 'No pude entender tu respuesta. Te comunico con un asesor para continuar.')
        # Intentamos asignar ANTES de fijar en_handoff: si no hay ningún asesor
        # disponible, dejar en_handoff=True apagaba el bot y nadie tomaba la
        # conversación → cliente atascado sin bot ni humano. En ese caso NO
        # entramos en handoff y dejamos que el flujo/IA siga respondiendo.
        agente = None
        try:
            from crm.helpers_asignacion import auto_asignar_agente
            # `avisar_si_ya_asignado`: en sesiones con `auto_asignar_round_robin`
            # la conversación llega con asesor desde el primer mensaje. No se
            # reasigna, pero el asesor que ya la tiene debe enterarse y el
            # cliente recibir el handoff igual.
            agente = auto_asignar_agente(
                self.conversation, motivo=motivo, avisar_si_ya_asignado=True,
            )
        except Exception:
            logger.exception('Auto-asignación fallida (%s) conv=%s',
                             motivo, self.conversation.id)
        if not agente:
            logger.warning('Handoff sin asesor disponible conv=%s motivo=%s — no se fija en_handoff',
                           self.conversation.id, motivo)
            self._trace('handoff_sin_asesor',
                        f'Handoff solicitado ({motivo}) pero no hay asesor disponible', False,
                        {'motivo': motivo})
            aviso = 'En este momento no hay un asesor disponible. Te responderemos apenas se libere uno.'
            self.enviar(aviso)
            return
        if msg:
            self.enviar(msg)
        self.handoff = True
        self.estado.en_handoff = True
        self.estado.save()
        self._trace('handoff_auto', f'Handoff automático ({motivo})', True,
                    {'motivo': motivo, 'agente': getattr(agente, 'username', '')})

    # ── Presentación de nodos de input ───────────────────────────────

    def _opciones_menu(self, nodo):
        """
        Devuelve la lista de opciones del menú. Usa `config.opciones` si existe,
        y como fallback, los hijos del árbol legacy (subopciones).

        Si `config.opcion_default` está presente, el menú actúa como atajo
        Sí/Otra y NO se cargan ni opciones estáticas ni dinámicas: la lista
        completa vive en otro nodo posterior conectado vía `salida_otra`.
        """
        cfg = nodo.config or {}

        default_cfg = cfg.get('opcion_default') or {}
        if isinstance(default_cfg, dict) and default_cfg.get('valor') is not None:
            etq_si = (default_cfg.get('etiqueta_si') or '').strip()
            if not etq_si:
                etq_si = f"✅ Sí, {default_cfg.get('etiqueta', 'continuar')}"
            etq_otra = (default_cfg.get('etiqueta_otra') or '').strip() or '📍 Otra'
            return [
                {
                    'etiqueta': etq_si,
                    'valor': '__default_si__',
                    'salida': default_cfg.get('salida_si', '') or '',
                },
                {
                    'etiqueta': etq_otra,
                    'valor': '__default_otra__',
                    'salida': default_cfg.get('salida_otra', '') or '',
                },
            ]

        opciones = list(cfg.get('opciones') or [])

        # Opciones dinámicas: se construyen desde una variable del contexto en
        # runtime. Útil para catálogos (tipos vehículo, colores, etc.) traídos
        # por un nodo HTTP previo. Todas las opciones dinámicas comparten la
        # misma `salida` (default = '') → una sola conexión saliente del menú.
        fuente = cfg.get('opciones_fuente') or {}
        if fuente:
            path = fuente.get('variable', '')
            campo_id = fuente.get('campo_id', 'id')
            campo_etq = fuente.get('campo_etiqueta', 'nombre')
            salida = fuente.get('salida', '')
            limite = int(fuente.get('limite', 10))
            items = _get_path(self.contexto(), path)
            if isinstance(items, (list, tuple)):
                for it in items[:limite]:
                    if isinstance(it, dict):
                        valor = str(it.get(campo_id, ''))
                        etq = str(it.get(campo_etq, valor))
                    else:
                        valor = str(it)
                        etq = valor
                    if valor:
                        opciones.append({'etiqueta': etq, 'valor': valor, 'salida': salida})

        if opciones:
            return opciones
        hijos = list(nodo.subopciones.filter(status=True).order_by('orden'))
        return [{'etiqueta': h.nombre, 'valor': h.nombre, 'salida': '', '_hijo_id': h.id}
                for h in hijos]

    def _presentar_nodo_input(self, nodo):
        cfg = nodo.config or {}
        if nodo.tipo_nodo == 'menu':
            default_cfg = cfg.get('opcion_default') or {}
            pregunta_default = (
                default_cfg.get('pregunta') if isinstance(default_cfg, dict) else ''
            ) or ''
            mensaje = (
                pregunta_default
                or cfg.get('mensaje')
                or nodo.respuesta
                or 'Elige una opción:'
            )
            mensaje = resolver_expresion(mensaje, self.contexto()) or mensaje
            opciones = self._opciones_menu(nodo)
            if not opciones:
                self.enviar(mensaje + '\n_(este menú no tiene opciones configuradas — contacta al administrador)_')
                return
            # Para Meta: arma payload interactive (button≤3 / list≤10).
            # Para Baileys: cae a texto numerado dentro de enviar_menu_interactivo.
            opciones_meta = []
            for op in opciones:
                hijo_id = op.get('_hijo_id')
                titulo = op.get('etiqueta') or op.get('valor') or ''
                # Resolver boton_id: prefiere el persistido en BD, sino genera uno determinístico.
                bid = ''
                if hijo_id:
                    try:
                        from .models import OpcionDepartamentoChatBot as _Op
                        hijo_obj = _Op.objects.filter(id=hijo_id).only('boton_id').first()
                        if hijo_obj:
                            bid = (hijo_obj.boton_id or '').strip()
                    except Exception:
                        pass
                if not bid:
                    bid = f'op_{hijo_id}' if hijo_id else f'op_{titulo[:30]}'
                opciones_meta.append({'id': bid[:256], 'title': titulo[:24]})
            self.enviar_menu_interactivo(mensaje, opciones_meta)
        elif nodo.tipo_nodo == 'pregunta':
            pregunta = cfg.get('pregunta') or nodo.respuesta or '¿Puedes indicarme el dato?'
            self.enviar(pregunta)

    def _notificar_asesor_nodo(self, nodo):
        cfg = nodo.config or {}
        if not cfg.get('notificar_asesor'):
            return
        if getattr(self, '_fin_asignado_nodo_id', None) == nodo.id:
            self._trace('notificar_asesor',
                        'Notificación al departamento omitida: el agente asignado '
                        'ya recibió notificación y correo con el link', True,
                        {'nodo_id': nodo.id})
            return
        if self.skip_side_effects:
            self._trace('side_effect_skipped',
                        'Notificación a asesor OMITIDA (dry-run)', True,
                        {'nodo_id': nodo.id})
            return
        try:
            from crm.helpers_correo_flujo import notificar_asesores_depto
            notificar_asesores_depto(
                conv=self.conversation,
                nodo=nodo,
                mensaje_custom=(cfg.get('mensaje_asesor') or '').strip(),
            )
            self._trace('notificar_asesor', 'Asesor notificado', True,
                        {'nodo_id': nodo.id})
        except Exception:
            logger.exception('Error notificando asesor (nodo %s)', nodo.id)

    # ── Procesamiento por tipo ───────────────────────────────────────

    def _procesar_nodo(self, nodo, consumir_mensaje: bool) -> Optional[str]:
        tipo = nodo.tipo_nodo
        cfg = nodo.config or {}

        if tipo == 'inicio':
            return ''

        if tipo == 'respuesta':
            mensaje = cfg.get('mensaje') or nodo.respuesta
            # Si el nodo tiene `config.cta_url` definido y la sesión es Meta,
            # mandamos como botón interactivo CTA URL en vez de texto plano.
            cta_url = (cfg.get('cta_url') or '').strip()
            cta_text = (cfg.get('cta_display_text') or 'Abrir').strip()
            if cta_url and getattr(self.session, 'es_meta', False):
                self._enviar_cta_url(mensaje, cta_url, cta_text)
            else:
                # Baileys / preview: anexar el link al final del cuerpo, así
                # el usuario ve clicable al menos como URL plana.
                if cta_url:
                    mensaje = (mensaje or '').rstrip() + f'\n\n👉 {cta_text}: {cta_url}'
                self.enviar(mensaje)
            return ''

        if tipo == 'pregunta':
            if not consumir_mensaje:
                return None
            if not validar_entrada(nodo.validacion_tipo, nodo.validacion_expresion, self.texto):
                self.estado.intentos = (self.estado.intentos or 0) + 1
                self._trace('validacion', f'Validación {nodo.validacion_tipo or "libre"} falló',
                            False, {'intentos': self.estado.intentos,
                                    'max': nodo.reintentos_max or 3,
                                    'entrada': self.texto[:120]})
                if self.estado.intentos >= (nodo.reintentos_max or 3):
                    self.estado.save()
                    return 'timeout'
                self.estado.save()
                self.enviar(nodo.mensaje_error or 'Dato inválido, intenta de nuevo.')
                self._presentar_nodo_input(nodo)
                return None
            if nodo.variable_destino:
                valor = self.texto
                if nodo.validacion_tipo == 'numero':
                    valor = normalizar_numero(valor)
                nombre_var = resolver_expresion(nodo.variable_destino, self.contexto())
                if isinstance(nombre_var, str) and nombre_var.strip():
                    nombre_var = nombre_var.strip()
                    self.estado.set_variable(nombre_var, valor)
                    self.estado.save()
                    self._trace('set_variable', f'Variable "{nombre_var}" capturada',
                                True, {'valor': str(valor)[:120]})
            return ''

        if tipo == 'menu':
            if not consumir_mensaje:
                return None
            opciones = self._opciones_menu(nodo)
            if not opciones:
                # Sin opciones configuradas → salir por default para no bloquear.
                logger.warning('Nodo menu %s sin opciones configuradas', nodo.id)
                self._trace('menu_vacio', f'Menú "{nodo.nombre}" sin opciones configuradas',
                            False, {'nodo_id': nodo.id})
                return ''
            t = self.texto.strip()
            t_norm = _normalizar_texto(t)
            elegida = None
            # Pase 0: boton_id de Meta interactive (más confiable que texto).
            if self.boton_id:
                from .models import OpcionDepartamentoChatBot as _Op
                # Match directo por boton_id persistido en BD
                hijo_match = _Op.objects.filter(
                    boton_id=self.boton_id, status=True
                ).first()
                if hijo_match:
                    for op in opciones:
                        if op.get('_hijo_id') == hijo_match.id:
                            elegida = op
                            break
                # Fallback: boton_id determinístico tipo "op_<id>"
                if not elegida and self.boton_id.startswith('op_'):
                    try:
                        target_id = int(self.boton_id.split('_', 1)[1])
                        for op in opciones:
                            if op.get('_hijo_id') == target_id:
                                elegida = op
                                break
                    except (ValueError, IndexError):
                        pass
            if elegida:
                pass  # ya matcheó por boton_id
            elif t.isdigit():
                idx = int(t) - 1
                if 0 <= idx < len(opciones):
                    elegida = opciones[idx]
            else:
                # Pase 1: match exacto contra etiqueta o valor (sin tildes/mayúsculas).
                # Pase 2: substring del valor o etiqueta (cubre "becas" → "Información de becas").
                for op in opciones:
                    et = _normalizar_texto(str(op.get('etiqueta', '')))
                    va = _normalizar_texto(str(op.get('valor', '')))
                    if t_norm and (t_norm == et or (va and t_norm == va)):
                        elegida = op
                        break
                if not elegida:
                    for op in opciones:
                        et = _normalizar_texto(str(op.get('etiqueta', '')))
                        va = _normalizar_texto(str(op.get('valor', '')))
                        if (va and va in t_norm) or (et and t_norm in et):
                            elegida = op
                            break
            if not elegida:
                self.estado.intentos = (self.estado.intentos or 0) + 1
                self._trace('menu_invalido', f'Opción no válida en "{nodo.nombre}"',
                            False, {'entrada': t[:120], 'intentos': self.estado.intentos,
                                    'max': nodo.reintentos_max or 3,
                                    'opciones_disponibles': len(opciones)})
                if self.estado.intentos >= (nodo.reintentos_max or 3):
                    self.estado.save()
                    return 'timeout'
                self.estado.save()
                self.enviar(nodo.mensaje_error or 'Opción no válida. Estas son las opciones disponibles:')
                self._presentar_nodo_input(nodo)
                return None
            valor_elegido = elegida.get('valor', elegida.get('etiqueta', ''))
            # Atajo "valor por defecto": si el cliente eligió la opción Sí del
            # opcion_default, el valor que guardamos no es el marcador interno
            # sino el `valor` configurado (ej: provincia_id='19'). Si eligió
            # "Otra" no asignamos nada — el siguiente nodo (catálogo) sobreescribe.
            default_cfg = cfg.get('opcion_default') or {}
            es_default_si = (
                isinstance(default_cfg, dict)
                and valor_elegido == '__default_si__'
            )
            es_default_otra = (
                isinstance(default_cfg, dict)
                and valor_elegido == '__default_otra__'
            )
            if es_default_si:
                valor_a_guardar = default_cfg.get('valor', '')
            elif es_default_otra:
                valor_a_guardar = None  # no tocar variable
            else:
                valor_a_guardar = valor_elegido
            if nodo.variable_destino and valor_a_guardar is not None:
                nombre_var_menu = resolver_expresion(nodo.variable_destino, self.contexto())
                if isinstance(nombre_var_menu, str) and nombre_var_menu.strip():
                    self.estado.set_variable(nombre_var_menu.strip(), valor_a_guardar)
                    self.estado.save()
            self._trace('menu_elegido', f'Opción "{elegida.get("etiqueta", "?")}" seleccionada',
                        True, {'salida': elegida.get('salida') or '(default)',
                               'valor': valor_a_guardar if valor_a_guardar is not None else '(no asignado)',
                               'es_default_si': es_default_si,
                               'es_default_otra': es_default_otra})
            # Salida explícita o, si no hay, navegación al hijo elegido puntual
            salida_menu = elegida.get('salida') or ''
            self._hijo_menu_elegido = elegida.get('_hijo_id') if not salida_menu else None
            return salida_menu

        if tipo == 'set_variable':
            ctx = self.contexto()
            for a in (cfg.get('asignaciones') or []):
                var = a.get('variable')
                if var:
                    var_resuelta = resolver_expresion(var, ctx)
                    if not isinstance(var_resuelta, str) or not var_resuelta.strip():
                        continue
                    self.estado.set_variable(var_resuelta.strip(), resolver_expresion(a.get('expresion', ''), ctx))
            self.estado.save()
            return ''

        if tipo == 'agenda_turno':
            from agenda.chatbot_handlers import procesar_nodo_turno
            return procesar_nodo_turno(self, nodo, consumir_mensaje)

        if tipo == 'loop':
            state_iter_key = f'_loop_{nodo.id}_iter'
            state_total_key = f'_loop_{nodo.id}_total'
            ctx = self.contexto()
            iter_actual = (self.estado.variables or {}).get(state_iter_key)

            if iter_actual is None:
                total_expr = str(cfg.get('iterations_expr') or '0')
                try:
                    total = int(resolver_expresion(total_expr, ctx) or 0)
                except (ValueError, TypeError):
                    total = 0
                if total < 0:
                    total = 0
                self.estado.set_variable(state_total_key, total)
                iter_actual = 0
                self.estado.set_variable(state_iter_key, iter_actual)
                self._trace('loop_init', f'Bucle "{nodo.nombre}" inicia ({total} iteraciones)',
                            True, {'total': total, 'nodo_id': nodo.id})
            else:
                iter_actual = int(iter_actual) + 1
                self.estado.set_variable(state_iter_key, iter_actual)

            total = int((self.estado.variables or {}).get(state_total_key) or 0)

            if iter_actual >= total:
                if (self.estado.variables or {}).get(state_iter_key) is not None:
                    self.estado.variables.pop(state_iter_key, None)
                if (self.estado.variables or {}).get(state_total_key) is not None:
                    self.estado.variables.pop(state_total_key, None)
                index_var_done = (cfg.get('index_var') or '').strip()
                if index_var_done and index_var_done in (self.estado.variables or {}):
                    self.estado.variables.pop(index_var_done, None)
                self.estado.save()
                self._trace('loop_done', f'Bucle "{nodo.nombre}" terminó ({total} iteraciones)',
                            True, {'total': total, 'nodo_id': nodo.id})
                return cfg.get('done_label') or 'done'

            index_var = (cfg.get('index_var') or 'i').strip()
            base_index = int(cfg.get('base_index') or 1)
            self.estado.set_variable(index_var, iter_actual + base_index)
            self.estado.save()
            self._trace('loop_step', f'Bucle "{nodo.nombre}" iteración {iter_actual + base_index}/{total}',
                        True, {'iter': iter_actual + base_index, 'total': total, 'nodo_id': nodo.id})
            return cfg.get('body_label') or 'body'

        if tipo == 'http':
            traza_extra = {}
            t0 = _time.time()
            etq, body, status, err = ejecutar_http(nodo, self.contexto(), _traza_extra=traza_extra)
            latencia_ms = int((_time.time() - t0) * 1000)
            self._trace('http', f'Llamada HTTP → {status or "sin respuesta"}',
                        etq == 'ok', {'status': status, 'error': err[:200] if err else ''})
            # Persistir a TrazaMensajeIA para inspección posterior en /whatsapp/trazas/
            self._traza_db(
                etapa_db='chatbot_http',
                label=f'{traza_extra.get("metodo", "?")} {traza_extra.get("url", "?")} → HTTP {status} ({etq})',
                ok=(etq == 'ok'),
                detalle={
                    'nodo': nodo.nombre,
                    'request_body': traza_extra.get('request_body'),
                    'query': traza_extra.get('query'),
                    'response_body': traza_extra.get('response_body'),
                    'error': err,
                },
                latencia_ms=latencia_ms,
            )
            self.estado.set_variable('_last_http', {'status': status, 'error': err})
            for ex in (cfg.get('extraer') or []):
                if etq == 'ok' and ex.get('variable'):
                    raw_path = (ex.get('jsonpath') or '').lstrip('$').lstrip('.')
                    nombre_ex = resolver_expresion(ex['variable'], self.contexto())
                    if isinstance(nombre_ex, str) and nombre_ex.strip():
                        self.estado.set_variable(nombre_ex.strip(), _get_path(body, raw_path))
            self.estado.save()
            plantilla = cfg.get('plantilla_respuesta')
            if plantilla and (etq == 'ok' or cfg.get('enviar_respuesta_en_error')):
                self.enviar(plantilla)
            # Side-effect genérico: si el nodo está marcado con
            # `config.envia_correo`, notifica por mail a los asesores del
            # depto al que pertenece el flujo. Falla silenciosa: si no hay
            # asesores o el envío rebota, solo loguea (el cliente sigue).
            # En modo dry-run (`skip_side_effects=True`) solo se loguea — útil
            # para iterar el flujo desde el simulador sin spamear asesores.
            if etq == 'ok' and cfg.get('envia_correo'):
                if self.skip_side_effects:
                    self._trace('side_effect_skipped',
                                'Correo a asesores OMITIDO (dry-run)', True,
                                {'nodo_id': nodo.id})
                    logger.info('Side-effect omitido (dry-run) en nodo %s', nodo.id)
                else:
                    try:
                        from crm.helpers_correo_flujo import notificar_asesores_depto
                        notificar_asesores_depto(
                            conv=self.conversation,
                            nodo=nodo,
                            request_body=traza_extra.get('request_body'),
                            response_body=traza_extra.get('response_body'),
                        )
                    except Exception:
                        logger.exception('Error enviando correo (nodo %s)', nodo.id)
            if etq == 'error' and err:
                logger.warning('Nodo http %s falló: %s', nodo.id, err)
                # Email SOLO para fallas técnicas reales (red/timeout → hay
                # traceback). Los errores de negocio (HTTP 4xx / success:false,
                # ej. "cédula no encontrada") NO mandan correo: ya quedan en la
                # traza (/whatsapp/trazas/) y el flujo los maneja con su rama
                # `error`. Esto evita el spam de mails por casos esperados.
                if traza_extra.get('traceback'):
                    _notificar_excepcion_chatbot(
                        nodo, self.conversation, etapa='http',
                        error_msg=err,
                        traceback_text=traza_extra.get('traceback', ''),
                        extra={
                            'url': traza_extra.get('url'),
                            'metodo': traza_extra.get('metodo'),
                            'query': traza_extra.get('query'),
                            'request_body': traza_extra.get('request_body'),
                            'response_body': traza_extra.get('response_body'),
                        },
                    )
            return etq

        if tipo == 'funcion':
            # Función Python registrada en `crm.funciones_chatbot`. Reemplaza
            # un nodo HTTP cuando la lógica vive dentro de Django (no tiene
            # sentido el roundtrip a sí mismo). El operador elige el código
            # registrado vía `config.funcion_codigo`. Branching ok/error y
            # `extraer` funcionan igual que en HTTP.
            from .funciones_chatbot import obtener_funcion

            codigo = (cfg.get('funcion_codigo') or '').strip()
            t0 = _time.time()
            if not codigo:
                etq, body, status, err = (
                    'error', {}, 0,
                    f'Nodo "{nodo.nombre}" sin `funcion_codigo` configurado.',
                )
            else:
                fn = obtener_funcion(codigo)
                if not fn:
                    etq, body, status, err = (
                        'error', {}, 0,
                        f'Función "{codigo}" no registrada.',
                    )
                else:
                    try:
                        resultado = fn(
                            self.conversation,
                            (self.estado.variables or {}),
                            cfg,
                            endpoint=nodo.endpoint,
                        ) or {}
                    except Exception as ex:  # noqa: BLE001 — la función no debe romper el flujo
                        logger.exception('Función %s nodo %s lanzó: %s', codigo, nodo.id, ex)
                        _notificar_excepcion_chatbot(
                            nodo, self.conversation, etapa='funcion', exc=ex,
                            extra={'funcion_codigo': codigo,
                                   'variables': (self.estado.variables or {})},
                        )
                        resultado = {
                            'etiqueta': 'error', 'body': {}, 'status': 0,
                            'error': f'{ex.__class__.__name__}: {str(ex)[:200]}',
                        }
                    etq = resultado.get('etiqueta') or 'error'
                    body = resultado.get('body') or {}
                    status = resultado.get('status') or 0
                    err = resultado.get('error') or ''
            latencia_ms = int((_time.time() - t0) * 1000)

            self._trace(
                'funcion', f'Función "{codigo}" → {etq}',
                etq == 'ok', {'codigo': codigo, 'status': status,
                              'error': err[:200] if err else ''},
            )
            self._traza_db(
                etapa_db='chatbot_funcion',
                label=f'fn:{codigo} → {etq} (status {status})',
                ok=(etq == 'ok'),
                detalle={'nodo': nodo.nombre, 'codigo': codigo,
                         'response_body': body, 'error': err},
                latencia_ms=latencia_ms,
            )
            self.estado.set_variable('_last_http', {'status': status, 'error': err})
            for ex in (cfg.get('extraer') or []):
                if etq == 'ok' and ex.get('variable'):
                    raw_path = (ex.get('jsonpath') or '').lstrip('$').lstrip('.')
                    nombre_ex = resolver_expresion(ex['variable'], self.contexto())
                    if isinstance(nombre_ex, str) and nombre_ex.strip():
                        self.estado.set_variable(nombre_ex.strip(), _get_path(body, raw_path))
            self.estado.save()
            plantilla = cfg.get('plantilla_respuesta')
            if plantilla and (etq == 'ok' or cfg.get('enviar_respuesta_en_error')):
                self.enviar(plantilla)
            # Side-effect: correo a asesores (mismo patrón que el nodo http).
            if etq == 'ok' and cfg.get('envia_correo'):
                if self.skip_side_effects:
                    self._trace('side_effect_skipped',
                                'Correo a asesores OMITIDO (dry-run)', True,
                                {'nodo_id': nodo.id})
                else:
                    try:
                        from crm.helpers_correo_flujo import notificar_asesores_depto
                        notificar_asesores_depto(
                            conv=self.conversation,
                            nodo=nodo,
                            request_body=cfg.get('body'),
                            response_body=body,
                        )
                    except Exception:
                        logger.exception('Error enviando correo (nodo %s)', nodo.id)
            if etq == 'error' and err:
                logger.warning('Nodo funcion %s [%s] falló: %s', nodo.id, codigo, err)
            return etq

        if tipo == 'condicional':
            conds = cfg.get('condiciones') or []
            operador = (cfg.get('operador') or 'and').lower()
            ctx = self.contexto()
            resultados = [evaluar_condicion(c, ctx) for c in conds]
            ok = all(resultados) if operador == 'and' else any(resultados)
            return 'true' if ok else 'false'

        if tipo == 'switch':
            valor = str(resolver_expresion(cfg.get('valor', ''), self.contexto()))
            for caso in (cfg.get('casos') or []):
                if str(caso.get('match', '')) == valor:
                    return caso.get('salida', '') or ''
            return 'default'

        if tipo == 'esperar':
            try:
                _time.sleep(min(float(cfg.get('segundos', 1)), 10))
            except (TypeError, ValueError):
                pass
            return ''

        if tipo == 'handoff':
            mensaje = cfg.get('mensaje') or nodo.respuesta or self.session.mensaje_handoff or ''
            if mensaje:
                self.enviar(mensaje)
            self.handoff = True
            self.estado.en_handoff = True
            self.estado.save()
            try:
                from crm.helpers_asignacion import auto_asignar_agente
                auto_asignar_agente(
                    self.conversation, motivo='handoff', avisar_si_ya_asignado=True,
                )
            except Exception:
                logger.exception('Auto-asignación fallida en handoff conv=%s', self.conversation.id)
            self._trace('handoff', 'Transferido a agente humano', True, {'nodo_id': nodo.id})
            return ''

        if tipo == 'fin':
            mensaje = cfg.get('mensaje') or nodo.respuesta or self.session.mensaje_despedida or ''
            if mensaje:
                self.enviar(mensaje)
            if (cfg.get('notificar_asesor') and not self.skip_side_effects
                    and not self.conversation.asignado_a_id):
                try:
                    from crm.helpers_asignacion import auto_asignar_agente
                    asignado = auto_asignar_agente(self.conversation, motivo='fin_flujo')
                except Exception:
                    asignado = None
                    logger.exception('Auto-asignación fallida en fin conv=%s',
                                     self.conversation.id)
                if asignado:
                    self._fin_asignado_nodo_id = nodo.id
                    self._trace('fin_asignacion',
                                f'Conversación asignada a {asignado} (menor carga 24h)',
                                True, {'nodo_id': nodo.id, 'agente_id': asignado.id})
            self.finalizado = True
            self.estado.finalizado = True
            self.estado.save()
            self._trace('fin', 'Flujo finalizado', True, {'nodo_id': nodo.id})
            return ''

        logger.warning('Tipo de nodo desconocido: %s', tipo)
        self._trace('tipo_desconocido', f'Tipo de nodo desconocido: {tipo}', False,
                    {'nodo_id': nodo.id})
        return ''


# ─────────────────────────────────────────────────────────────────────
# Entry point público
# ─────────────────────────────────────────────────────────────────────

def procesar_mensaje_tradicional(session, conversation, contacto, texto, boton_id='') -> ResultadoFlujo:
    """
    Procesa un mensaje entrante usando el flujo tradicional de la sesión.

    Se debe invocar SOLO cuando session.modo_bot == 'tradicional'.
    El webhook es responsable de decidir la llamada — este módulo nunca se
    activa solo (cero interferencia con el pipeline IA).

    Args:
        boton_id: Si el cliente tocó un botón Meta (interactive), el webhook
            extrae `button_reply.id` o `list_reply.id` y lo pasa acá. El motor
            lo matchea contra OpcionDepartamentoChatBot.boton_id, evitando
            depender del título visible (que cambia con i18n / typos).
    """
    # Imports perezosos: evitan ciclos y desacoplan el módulo.
    from crm.models import EstadoFlujoChatbot
    from whatsapp.services import get_whatsapp_service

    if (session.modo_bot or 'ia') != 'tradicional':
        return ResultadoFlujo(manejado=False)

    # get_or_create es race-safe para la creación (EstadoFlujoChatbot.conversacion
    # es OneToOne único). No envolvemos el turno en una transacción con
    # select_for_update: motor.ejecutar() hace I/O HTTP (envíos a WhatsApp y nodos
    # http de hasta 15s), y mantener el lock + una conexión del pool durante esa
    # latencia agota conexiones bajo carga; peor aún, un fallo de ORM a mitad de
    # turno haría rollback de mensajes ya enviados → respuestas duplicadas.
    # La serialización estricta por conversación (dos mensajes casi simultáneos)
    # requiere un rediseño con flag de claim y queda como trabajo futuro.
    estado, _ = EstadoFlujoChatbot.objects.get_or_create(conversacion=conversation)

    # Ya está en handoff humano: el motor no responde hasta que humanos lo liberen.
    if estado.en_handoff:
        return ResultadoFlujo(manejado=False, handoff=True)

    # Si venía finalizado de un turno previo, reiniciar la máquina de estados.
    if estado.finalizado:
        estado.reset()
        estado.save()

    motor = MotorFlujo(session, conversation, contacto, texto, estado,
                      get_whatsapp_service(session), boton_id=boton_id)
    try:
        motor.ejecutar()
    except Exception as e:
        logger.exception('Motor flujo falló conv#%s: %s', conversation.id, e)
        return ResultadoFlujo(
            manejado=False,
            fallback_ia=False,
            error=str(e),
        )

    manejado = bool(motor.respuestas) or motor.handoff or motor.finalizado
    return ResultadoFlujo(
        manejado=manejado,
        fallback_ia=False,
        handoff=motor.handoff,
        finalizado=motor.finalizado,
        respuestas=motor.respuestas,
    )


def reiniciar_flujo_tradicional(conversation, depto=None) -> ResultadoFlujo:
    """Fuerza el reinicio del flujo tradicional de una conversación desde
    fuera del webhook (botón del agente, comando admin, etc).

    Limpia variables, libera handoff, vuelve al `nodo_inicio` del depto
    indicado (o el del estado actual / `session.departamento_default`) y
    procesa ese nodo para que el cliente reciba el mensaje de bienvenida
    sin necesidad de que escriba un trigger.

    Garantiza al menos un mensaje saliente: si el depto no tiene
    `mensaje_reset` ni `mensaje_saludo` y el `nodo_inicio` no produce
    respuesta visible, se envía un aviso genérico. Detecta fallas del
    servicio WhatsApp (Node caído, ventana 24h Meta, sesión rate-limited,
    etc.) y las propaga como `error` en el `ResultadoFlujo`.
    """
    from crm.models import EstadoFlujoChatbot
    from whatsapp.services import get_whatsapp_service

    session = conversation.sesion
    if (session.modo_bot or 'ia') != 'tradicional':
        return ResultadoFlujo(manejado=False, error='La sesión no es tradicional.')

    contacto = conversation.contacto
    if contacto is None:
        return ResultadoFlujo(manejado=False, error='Conversación sin contacto.')

    estado, _ = EstadoFlujoChatbot.objects.get_or_create(conversacion=conversation)

    depto_objetivo = depto or estado.departamento or session.departamento_default
    if depto_objetivo is None:
        return ResultadoFlujo(
            manejado=False,
            error='La sesión no tiene un departamento de entrada configurado.',
        )

    # Reset duro: variables, nodo, handoff. Hacer en una sola escritura
    # para que nada quede inconsistente si algo falla más adelante.
    estado.departamento = depto_objetivo
    estado.nodo_actual = depto_objetivo.nodo_inicio()
    estado.variables = {}
    estado.intentos = 0
    estado.finalizado = False
    estado.en_handoff = False
    estado.save()

    motor = MotorFlujo(session, conversation, contacto, '', estado,
                      get_whatsapp_service(session))

    # Wrap motor.enviar para capturar fallas reales del transporte.
    # `WhatsAppService.send_text_message` y `MetaWhatsAppService.send_text_message`
    # nunca lanzan: devuelven `{'success': False, 'error': ...}`. Sin este
    # wrapper, motor.enviar persiste el mensaje en BD aunque el cliente
    # nunca lo reciba. Acá interceptamos para reportar la verdad al usuario.
    fallas_transporte: list[str] = []
    enviar_original = motor.enviar

    def enviar_con_seguimiento(texto: str):
        if not texto:
            return
        resuelto = resolver_expresion(texto, motor.contexto())
        try:
            r = motor.ws.send_text_message(
                session.session_id,
                contacto.from_number,
                resuelto,
                conversation.id,
                True,
            ) or {}
        except Exception as e:
            logger.exception('Reset manual: send_text_message lanzó: %s', e)
            fallas_transporte.append(f'{type(e).__name__}: {str(e)[:200]}')
            return
        if not r.get('success'):
            fallas_transporte.append(r.get('error', 'transporte rechazó el mensaje'))
            return
        motor.respuestas.append(resuelto)
        motor._persistir_mensaje_saliente(resuelto, r)

    motor.enviar = enviar_con_seguimiento

    # Mensaje inicial: prioridad mensaje_reset > mensaje_saludo.
    msg_inicial = (depto_objetivo.mensaje_reset or depto_objetivo.mensaje_saludo or '').strip()
    if msg_inicial:
        try:
            msg_inicial = resolver_expresion(msg_inicial, motor.contexto()) or msg_inicial
        except Exception:
            logger.exception('Reset manual: error resolviendo plantilla')
        motor.enviar(msg_inicial)

    # Ejecutar el nodo de inicio para que el cliente reciba la primera
    # pregunta/respuesta del flujo. Si falla, ya enviamos el mensaje
    # inicial — no se rompe la operación completa.
    if estado.nodo_actual:
        try:
            motor._run_loop(consumir_mensaje=False)
        except Exception as e:
            logger.exception('Reset manual: _run_loop falló conv#%s: %s',
                             conversation.id, e)

    # Restaurar enviar original por si algún lugar guardó referencia al motor.
    motor.enviar = enviar_original

    # Si todo el ciclo falló (nada llegó al cliente), reportar el primer
    # error del transporte para que el agente sepa el motivo real.
    if not motor.respuestas:
        if fallas_transporte:
            return ResultadoFlujo(
                manejado=False,
                error=f'WhatsApp rechazó el mensaje: {fallas_transporte[0]}',
            )
        return ResultadoFlujo(
            manejado=False,
            error='No se pudo enviar ningún mensaje. Revisa el estado de la sesión.',
        )

    # Notificar a las pestañas abiertas (ChatConsumer) para que el panel
    # de la conversación re-renderice los mensajes recién persistidos sin
    # necesidad de refrescar manualmente.
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        cl = get_channel_layer()
        if cl is not None:
            async_to_sync(cl.group_send)(
                f'chat_{conversation.id}',
                {
                    'type': 'whatsapp_message',
                    'event': 'new_message',
                    'conversation_id': conversation.id,
                    'sender': session.numero or '',
                    'from_me': True,
                },
            )
    except Exception:
        logger.exception('Reset manual: error notificando ChatConsumer')

    return ResultadoFlujo(
        manejado=bool(motor.respuestas),
        fallback_ia=False,
        handoff=motor.handoff,
        finalizado=motor.finalizado,
        respuestas=motor.respuestas,
    )
