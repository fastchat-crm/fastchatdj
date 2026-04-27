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
import logging
import re
import time as _time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

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
    Reemplaza `{{ruta.a.campo}}` en strings. Recurre sobre dict/list.
    - Si la expresión es toda la cadena (`{{x}}`), retorna el valor con su tipo
      original (útil para pasar números/bool a JSON body).
    - Si está embebida en texto, hace substitución a string.
    """
    if isinstance(valor, str):
        m = _EXPR_RE.fullmatch(valor.strip())
        if m:
            return _get_path(contexto, m.group(1).strip())

        def _repl(mo):
            r = _get_path(contexto, mo.group(1).strip())
            return '' if r is None else str(r)

        return _EXPR_RE.sub(_repl, valor)

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


def validar_entrada(tipo: str, expresion: str, texto: str) -> bool:
    t = (texto or '').strip()
    if tipo in ('', 'none', None):
        return True
    if tipo == 'email':
        return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', t))
    if tipo == 'numero':
        return bool(re.match(r'^-?\d+([.,]\d+)?$', t))
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


def ejecutar_http(nodo, contexto: dict):
    """
    Ejecuta un nodo `http`.
    Devuelve (etiqueta, body, status_code, error_str) con etiqueta ∈ {'ok','error'}.
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
    _aplicar_credencial(ep.credencial, headers, query)

    try:
        resp = requests.request(
            metodo, url,
            headers=headers,
            params=query or None,
            json=body if metodo in ('POST', 'PUT', 'PATCH') and body is not None else None,
            timeout=ep.timeout_seg or 15,
        )
    except requests.RequestException as e:
        return ('error', None, 0, str(e))

    try:
        parsed = resp.json()
    except ValueError:
        parsed = {'_raw': resp.text}

    if 200 <= resp.status_code < 300:
        return ('ok', parsed, resp.status_code, '')
    return ('error', parsed, resp.status_code, f'HTTP {resp.status_code}')


# ─────────────────────────────────────────────────────────────────────
# Motor
# ─────────────────────────────────────────────────────────────────────

class MotorFlujo:
    def __init__(self, session, conversation, contacto, texto, estado, ws_service, boton_id=''):
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
        # True cuando _elegir_departamento determina que hay >1 depto activo y
        # ninguno matcheó → caller debe presentar meta-menú al usuario.
        self.pendiente_seleccion = False
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
            self.ws.send_text_message(
                self.session.session_id,
                self.contacto.from_number,
                resuelto,
                self.conversation.id,
                True,
            )
            self.respuestas.append(resuelto)
            self._trace('envio', 'Mensaje enviado', True,
                        {'preview': resuelto[:160], 'chars': len(resuelto)})
        except Exception as e:
            logger.exception('Error enviando mensaje tradicional: %s', e)
            self._trace('envio', 'Error al enviar', False, {'error': str(e)[:200]})

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
                rows = [{'id': o['id'], 'title': o.get('title', '')[:24],
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
        txt = self.texto.lower()

        # 1) palabras clave
        for d in deptos:
            palabras = d.get_palabras_clave()
            if palabras and any(p in txt for p in palabras):
                return d

        # 2) selector numérico (compat con el menú clásico de departamentos)
        if txt.isdigit():
            idx = int(txt) - 1
            if 0 <= idx < len(deptos):
                return deptos[idx]

        # 3) Ambigüedad: >1 depto activo y nada matcheó → meta-menú.
        # Marcamos pendiente_seleccion para que `ejecutar` presente la lista al usuario.
        if len(deptos) > 1:
            self.pendiente_seleccion = True
            return None

        # 4) default de la sesión
        dd = getattr(self.session, 'departamento_default', None)
        if dd and dd.status and dd.activo_tradicional:
            return dd

        # 5) default marcado en el departamento
        return next((d for d in deptos if getattr(d, 'es_default', False)), None)

    def _avanzar(self, etiqueta: str):
        nodo = self.estado.nodo_actual
        if not nodo:
            return None
        conn = nodo.salidas.filter(status=True, etiqueta=etiqueta).order_by('orden').first()
        if conn:
            return conn.nodo_destino
        # Fallback legacy: árbol por opcion_padre cuando la etiqueta es default
        if etiqueta == '':
            return nodo.subopciones.filter(status=True).order_by('orden').first()
        # Si no hay conexión específica, caer a la default
        conn_def = nodo.salidas.filter(status=True, etiqueta='').order_by('orden').first()
        return conn_def.nodo_destino if conn_def else None

    # ── Loop principal ───────────────────────────────────────────────

    def ejecutar(self):
        self._trace('inicio', 'Mensaje recibido', True, {
            'texto': self.texto[:160],
            'primer_turno': not bool(self.estado.nodo_actual),
        })

        variables = self.estado.variables or {}

        # 0) Comando global de reset: si el usuario está atascado y escribe
        #    una palabra reservada (menu/inicio/atras/...), reiniciamos el
        #    flujo y re-enrutamos como si fuera el primer turno.
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
        t_low = t.lower()
        elegido = None

        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(deptos):
                elegido = deptos[idx]
        if not elegido:
            for d in deptos:
                if d.nombre.lower() == t_low or t_low in d.nombre.lower():
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
            self.estado.nodo_actual = siguiente
            self.estado.intentos = 0
            self.estado.save()

    # ── Presentación de nodos de input ───────────────────────────────

    def _opciones_menu(self, nodo):
        """
        Devuelve la lista de opciones del menú. Usa `config.opciones` si existe,
        y como fallback, los hijos del árbol legacy (subopciones).
        """
        cfg = nodo.config or {}
        opciones = cfg.get('opciones') or []
        if opciones:
            return opciones
        hijos = list(nodo.subopciones.filter(status=True).order_by('orden'))
        return [{'etiqueta': h.nombre, 'valor': h.nombre, 'salida': '', '_hijo_id': h.id}
                for h in hijos]

    def _presentar_nodo_input(self, nodo):
        cfg = nodo.config or {}
        if nodo.tipo_nodo == 'menu':
            mensaje = cfg.get('mensaje') or nodo.respuesta or 'Elige una opción:'
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
            self.enviar(cfg.get('pregunta') or nodo.respuesta or '¿Puedes indicarme el dato?')

    # ── Procesamiento por tipo ───────────────────────────────────────

    def _procesar_nodo(self, nodo, consumir_mensaje: bool) -> Optional[str]:
        tipo = nodo.tipo_nodo
        cfg = nodo.config or {}

        if tipo == 'inicio':
            return ''

        if tipo == 'respuesta':
            self.enviar(cfg.get('mensaje') or nodo.respuesta)
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
                return None
            if nodo.variable_destino:
                self.estado.set_variable(nodo.variable_destino, self.texto)
                self.estado.save()
                self._trace('set_variable', f'Variable "{nodo.variable_destino}" capturada',
                            True, {'valor': self.texto[:120]})
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
            t_low = t.lower()
            elegida = None
            if t.isdigit():
                idx = int(t) - 1
                if 0 <= idx < len(opciones):
                    elegida = opciones[idx]
            else:
                # Pase 1: match exacto contra etiqueta o valor (case-insensitive).
                # Pase 2: substring del valor o etiqueta (cubre "becas" → "Información de becas").
                for op in opciones:
                    et = str(op.get('etiqueta', '')).lower()
                    va = str(op.get('valor', '')).lower()
                    if t_low == et or (va and t_low == va):
                        elegida = op
                        break
                if not elegida:
                    for op in opciones:
                        et = str(op.get('etiqueta', '')).lower()
                        va = str(op.get('valor', '')).lower()
                        if (va and va in t_low) or (et and t_low in et):
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
                self.enviar(nodo.mensaje_error or 'Opción no válida. Elige el número de la opción.')
                return None
            if nodo.variable_destino:
                self.estado.set_variable(
                    nodo.variable_destino,
                    elegida.get('valor', elegida.get('etiqueta', '')),
                )
                self.estado.save()
            self._trace('menu_elegido', f'Opción "{elegida.get("etiqueta", "?")}" seleccionada',
                        True, {'salida': elegida.get('salida') or '(default)',
                               'valor': elegida.get('valor', '')})
            # Salida explícita o fallback por etiqueta del hijo legacy
            return elegida.get('salida') or ''

        if tipo == 'set_variable':
            ctx = self.contexto()
            for a in (cfg.get('asignaciones') or []):
                var = a.get('variable')
                if var:
                    self.estado.set_variable(var, resolver_expresion(a.get('expresion', ''), ctx))
            self.estado.save()
            return ''

        if tipo == 'http':
            etq, body, status, err = ejecutar_http(nodo, self.contexto())
            self._trace('http', f'Llamada HTTP → {status or "sin respuesta"}',
                        etq == 'ok', {'status': status, 'error': err[:200] if err else ''})
            self.estado.set_variable('_last_http', {'status': status, 'error': err})
            for ex in (cfg.get('extraer') or []):
                if etq == 'ok' and ex.get('variable'):
                    raw_path = (ex.get('jsonpath') or '').lstrip('$').lstrip('.')
                    self.estado.set_variable(ex['variable'], _get_path(body, raw_path))
            self.estado.save()
            plantilla = cfg.get('plantilla_respuesta')
            if plantilla and (etq == 'ok' or cfg.get('enviar_respuesta_en_error')):
                self.enviar(plantilla)
            if etq == 'error' and err:
                logger.warning('Nodo http %s falló: %s', nodo.id, err)
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
            self._trace('handoff', 'Transferido a agente humano', True, {'nodo_id': nodo.id})
            return ''

        if tipo == 'fin':
            mensaje = cfg.get('mensaje') or self.session.mensaje_despedida or ''
            if mensaje:
                self.enviar(mensaje)
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

def procesar_mensaje_tradicional(session, conversation, contacto, texto) -> ResultadoFlujo:
    """
    Procesa un mensaje entrante usando el flujo tradicional de la sesión.

    Se debe invocar SOLO cuando session.modo_bot in ('tradicional', 'hibrido').
    El webhook es responsable de decidir la llamada — este módulo nunca se
    activa solo (cero interferencia con el pipeline IA).
    """
    # Imports perezosos: evitan ciclos y desacoplan el módulo.
    from crm.models import EstadoFlujoChatbot
    from whatsapp.services import get_whatsapp_service

    if (session.modo_bot or 'ia') not in ('tradicional', 'hibrido'):
        return ResultadoFlujo(manejado=False)

    estado, _ = EstadoFlujoChatbot.objects.get_or_create(conversacion=conversation)

    # Ya está en handoff humano: el motor no responde hasta que humanos lo liberen.
    if estado.en_handoff:
        return ResultadoFlujo(manejado=False, handoff=True)

    # Si venía finalizado de un turno previo, reiniciar la máquina de estados.
    if estado.finalizado:
        estado.reset()
        estado.save()

    motor = MotorFlujo(session, conversation, contacto, texto, estado, get_whatsapp_service(session))
    try:
        motor.ejecutar()
    except Exception as e:
        logger.exception('Motor flujo falló conv#%s: %s', conversation.id, e)
        return ResultadoFlujo(
            manejado=False,
            fallback_ia=(session.modo_bot == 'hibrido'),
            error=str(e),
        )

    manejado = bool(motor.respuestas) or motor.handoff or motor.finalizado
    fallback = (not manejado) and session.modo_bot == 'hibrido'
    return ResultadoFlujo(
        manejado=manejado,
        fallback_ia=fallback,
        handoff=motor.handoff,
        finalizado=motor.finalizado,
        respuestas=motor.respuestas,
    )
