/* dpchat_preview.js — simulador WhatsApp + state-machine del flujo del depto.

   Lee el grafo plano de #dp-preview-data y lo recorre paso a paso,
   evaluando cada nodo según su tipo:
     - menu      → render opciones (botones), espera click
     - pregunta  → input de texto, captura en variable_destino
     - respuesta → muestra texto, avanza ''
     - http      → mock (placeholder) o real (llama probar_http)
     - condicional → evalúa local con izq/op/der, avanza true/false
     - set_variable → aplica asignaciones, avanza ''
     - cta_url, ubicacion → render, avanza ''
     - handoff/fin → finaliza
*/

(function () {
    'use strict';

    var dataEl = document.getElementById('dp-preview-data');
    if (!dataEl) return;
    var DATA;
    try { DATA = JSON.parse(dataEl.textContent); }
    catch (e) { console.error('preview JSON invalido', e); return; }

    // ── Estado runtime + memoria persistente ────────────────────
    var DEPTO_ID = (DATA.departamento && DATA.departamento.id) || 0;
    var STORAGE_KEY = 'dpprev_vars_' + DEPTO_ID;
    var MODE_KEY = 'dpprev_mode_' + DEPTO_ID;

    function cargarVarsPersistentes() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return {};
            var parsed = JSON.parse(raw);
            return (parsed && typeof parsed === 'object') ? parsed : {};
        } catch (e) { return {}; }
    }
    function guardarVarsPersistentes() {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(STATE.vars)); }
        catch (e) { /* localStorage lleno o deshabilitado — ignorar */ }
    }
    function limpiarMemoriaPersistente() {
        try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
    }

    var STATE = {
        vars: cargarVarsPersistentes(),
        currentId: null,
        mode: localStorage.getItem(MODE_KEY) || 'mock',
        ended: false,
        awaitingInput: false,
        currentPreguntaNode: null,
    };

    // ── Refs DOM ────────────────────────────────────────────────
    var chat = document.getElementById('dpprev-chat');
    var btnReset = document.getElementById('dpprev-reset');
    var modeToggle = document.getElementById('dpprev-mode-real');
    var varsPre = document.getElementById('dpprev-vars');
    var logBox = document.getElementById('dpprev-log');
    var logClear = document.getElementById('dpprev-log-clear');
    var textInputBar = document.getElementById('dpprev-text-input');
    var textField = document.getElementById('dpprev-text-field');
    var textSend = document.getElementById('dpprev-text-send');

    // ── Helpers DOM ─────────────────────────────────────────────
    function el(tag, cls, html) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (html != null) n.innerHTML = html;
        return n;
    }
    function escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function scroll() { chat.scrollTop = chat.scrollHeight; }
    function botBubble(text) {
        var n = el('div', 'dpprev-msg bot', escHtml(text).replace(/\n/g, '<br>'));
        chat.appendChild(n);
        scroll();
    }
    function userBubble(text) {
        var n = el('div', 'dpprev-msg user', escHtml(text));
        chat.appendChild(n);
        scroll();
    }
    function systemBubble(text, kind) {
        var n = el('div', 'dpprev-msg system' + (kind ? ' system-' + kind : ''),
                   escHtml(text));
        chat.appendChild(n);
        scroll();
    }
    function typing(ms) {
        return new Promise(function (resolve) {
            var t = el('div', 'dpprev-msg bot');
            t.appendChild(el('div', 'dpprev-typing',
                '<span></span><span></span><span></span>'));
            chat.appendChild(t);
            scroll();
            setTimeout(function () { t.remove(); resolve(); }, ms || 350);
        });
    }

    // ── Variables panel + log ───────────────────────────────────
    function refreshVars() {
        if (varsPre) {
            try { varsPre.textContent = JSON.stringify(STATE.vars, null, 2); }
            catch (e) { varsPre.textContent = String(STATE.vars); }
        }
        guardarVarsPersistentes();
    }
    function logEvt(level, msg, detail) {
        if (!logBox) return;
        var ts = new Date().toLocaleTimeString();
        var row = el('div', 'dpprev-log-row level-' + (level || 'info'));
        var html = '<span class="ts">' + ts + '</span> '
                 + '<span class="lvl">' + escHtml(level || 'info') + '</span> '
                 + escHtml(msg);
        if (detail) {
            html += '<details class="ms-3"><summary>detalle</summary><pre>'
                  + escHtml(JSON.stringify(detail, null, 2)) + '</pre></details>';
        }
        row.innerHTML = html;
        logBox.appendChild(row);
        logBox.scrollTop = logBox.scrollHeight;
    }
    if (logClear) logClear.addEventListener('click', function () { logBox.innerHTML = ''; });

    // ── Tabs side panel ─────────────────────────────────────────
    document.querySelectorAll('#dpprev-tabs .nav-link').forEach(function (b) {
        b.addEventListener('click', function () {
            document.querySelectorAll('#dpprev-tabs .nav-link').forEach(function (x) {
                x.classList.remove('active');
            });
            b.classList.add('active');
            var tab = b.getAttribute('data-tab');
            document.querySelectorAll('.tab-pane').forEach(function (p) {
                p.style.display = (p.getAttribute('data-pane') === tab) ? '' : 'none';
            });
        });
    });

    // ── Resolver `{{variables.x}}` + `{% for %}` ───────────────
    var EXPR_RE = /\{\{\s*([^{}]+?)\s*\}\}/g;
    // Tokens individuales del parser de loops anidados.
    var FOR_OPEN_RE = /\{%\s*for\s+(\w+)\s+in\s+([^%]+?)\s*%\}/;
    var FOR_END_RE = /\{%\s*endfor\s*%\}/;

    function pathGet(obj, path) {
        var parts = path.match(/[^.\[\]]+|\[\d+\]/g) || [];
        var cur = obj;
        for (var i = 0; i < parts.length; i++) {
            if (cur == null) return null;
            var p = parts[i];
            if (p.charAt(0) === '[') {
                var idx = parseInt(p.slice(1, -1), 10);
                cur = (Array.isArray(cur) && idx >= 0 && idx < cur.length) ? cur[idx] : null;
            } else if (typeof cur === 'object') {
                cur = cur[p];
            } else { return null; }
        }
        return cur;
    }

    // Expande loops {% for %}...{% endfor %} balanceados (anidados).
    // Encuentra el bloque MÁS EXTERNO con un parser stack-based, itera la
    // lista del path inyectando `var` en sub-context, y resuelve el cuerpo
    // recursivamente vía resolverExprCtx para que tanto los loops internos
    // como las {{ }} del body usen el contexto del item actual.
    function expandirFors(texto, ctx) {
        while (true) {
            var openSearch = texto.search(FOR_OPEN_RE);
            if (openSearch < 0) return texto;
            var openMatch = texto.slice(openSearch).match(FOR_OPEN_RE);
            var openStart = openSearch;
            var openEnd = openSearch + openMatch[0].length;
            var varName = openMatch[1];
            var path = openMatch[2].trim();

            var depth = 1;
            var pos = openEnd;
            var endStart = -1, endEnd = -1;
            while (pos < texto.length) {
                var rest = texto.slice(pos);
                var nextOpenIdx = rest.search(FOR_OPEN_RE);
                var nextEndIdx = rest.search(FOR_END_RE);
                if (nextEndIdx < 0) return texto;  // sin cierre — abortar
                if (nextOpenIdx >= 0 && nextOpenIdx < nextEndIdx) {
                    var nm = rest.match(FOR_OPEN_RE);
                    depth++;
                    pos = pos + nextOpenIdx + nm[0].length;
                } else {
                    var em = rest.match(FOR_END_RE);
                    depth--;
                    if (depth === 0) {
                        endStart = pos + nextEndIdx;
                        endEnd = endStart + em[0].length;
                        break;
                    }
                    pos = pos + nextEndIdx + em[0].length;
                }
            }
            if (endStart < 0) return texto;

            var body = texto.slice(openEnd, endStart);
            var lista = pathGet(ctx, path);
            var reemplazo = '';
            if (Array.isArray(lista)) {
                reemplazo = lista.map(function (item) {
                    var sub = Object.assign({}, ctx);
                    sub[varName] = item;
                    return resolverExprCtx(body, sub);
                }).join('');
            }
            texto = texto.slice(0, openStart) + reemplazo + texto.slice(endEnd);
        }
    }

    function resolverExprCtx(valor, ctx) {
        if (typeof valor === 'string') {
            valor = expandirFors(valor, ctx);
            var fullMatch = valor.match(/^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$/);
            if (fullMatch) return pathGet(ctx, fullMatch[1].trim());
            return valor.replace(EXPR_RE, function (_, p) {
                var r = pathGet(ctx, p.trim());
                return (r == null) ? '' : String(r);
            });
        }
        if (Array.isArray(valor)) return valor.map(function (v) { return resolverExprCtx(v, ctx); });
        if (valor && typeof valor === 'object') {
            var out = {};
            Object.keys(valor).forEach(function (k) { out[k] = resolverExprCtx(valor[k], ctx); });
            return out;
        }
        return valor;
    }

    function resolverExpr(valor) {
        var ctx = { variables: STATE.vars, contacto: { numero: 'preview', nombre: 'Preview' } };
        return resolverExprCtx(valor, ctx);
    }

    // ── Navegación: encontrar destino por etiqueta ──────────────
    function buscarSalida(node, etiqueta) {
        var sals = node.salidas || [];
        for (var i = 0; i < sals.length; i++) {
            if ((sals[i].etiqueta || '') === etiqueta) {
                return DATA.nodos[String(sals[i].destino_id)];
            }
        }
        return null;
    }
    function siguienteDefault(node) {
        return buscarSalida(node, '') || buscarSalida(node, 'ok');
    }

    // ── Despacho por tipo ───────────────────────────────────────
    function avanzarA(idOrNode) {
        var node = (typeof idOrNode === 'object') ? idOrNode :
                   DATA.nodos[String(idOrNode)];
        if (!node) {
            STATE.ended = true;
            systemBubble('— Sin nodo siguiente. Fin del flujo. —');
            logEvt('warn', 'No hay nodo siguiente, flujo terminado');
            return;
        }
        STATE.currentId = node.id;
        logEvt('info', '→ Nodo #' + node.id + ' [' + node.tipo + '] ' + (node.nombre || ''));
        typing().then(function () { ejecutar(node); });
    }

    function ejecutar(node) {
        var cfg = node.config || {};

        // Render del cuerpo según tipo
        if (node.tipo === 'menu') {
            if (cfg.mensaje) botBubble(cfg.mensaje);
            else if (node.respuesta) botBubble(node.respuesta);
            renderMenu(node);
            return;
        }
        if (node.tipo === 'pregunta') {
            if (cfg.pregunta) botBubble(cfg.pregunta);
            else if (node.respuesta) botBubble(node.respuesta);
            mostrarInputTexto(node);
            return;
        }
        if (node.tipo === 'respuesta') {
            var msg = resolverExpr(cfg.mensaje || node.respuesta || '');
            if (msg) botBubble(msg);
            avanzarA(siguienteDefault(node));
            return;
        }
        if (node.tipo === 'cta_url') {
            renderCtaUrl(node);
            avanzarA(siguienteDefault(node));
            return;
        }
        if (node.tipo === 'ubicacion') {
            renderLocation(node);
            avanzarA(siguienteDefault(node));
            return;
        }
        if (node.tipo === 'set_variable') {
            (cfg.asignaciones || []).forEach(function (a) {
                if (a.variable) {
                    var val = resolverExpr(a.expresion || '');
                    STATE.vars[a.variable] = val;
                }
            });
            refreshVars();
            logEvt('info', 'set_variable aplicado',
                   { asignaciones: cfg.asignaciones });
            avanzarA(siguienteDefault(node));
            return;
        }
        if (node.tipo === 'condicional') {
            evaluarCondicional(node);
            return;
        }
        if (node.tipo === 'http') {
            ejecutarHttp(node);
            return;
        }
        if (node.tipo === 'handoff') {
            if (cfg.mensaje) botBubble(cfg.mensaje);
            systemBubble('🤝 [Bot derivó la conversación a un humano]', 'handoff');
            STATE.ended = true;
            logEvt('warn', 'Handoff a humano');
            return;
        }
        if (node.tipo === 'fin') {
            if (cfg.mensaje) botBubble(cfg.mensaje);
            systemBubble('🏁 [Flujo terminado]', 'fin');
            STATE.ended = true;
            logEvt('info', 'Fin del flujo');
            return;
        }
        systemBubble('— Tipo "' + node.tipo + '" no manejado —', 'warn');
        logEvt('warn', 'Tipo no manejado: ' + node.tipo);
    }

    // ── menu ────────────────────────────────────────────────────
    function renderMenu(node) {
        var cfg = node.config || {};
        var opciones = cfg.opciones || [];
        if (!opciones.length) {
            // Fallback: hijos legacy via opcion_padre
            (node.hijos_legacy || []).forEach(function (hid) {
                var h = DATA.nodos[String(hid)];
                if (h) opciones.push({
                    etiqueta: h.nombre || '?', valor: '', salida: '',
                    _legacy_destino: hid,
                });
            });
        }
        if (!opciones.length) {
            systemBubble('— Menú sin opciones —', 'warn');
            return;
        }
        var box = el('div', 'dpprev-buttons');
        opciones.forEach(function (opt) {
            var b = el('button', 'dpprev-btn');
            b.type = 'button';
            b.textContent = opt.etiqueta || opt.valor || '(sin etiqueta)';
            b.addEventListener('click', function () {
                deshabilitar(box);
                userBubble(opt.etiqueta || '');
                if (node.variable_destino) {
                    STATE.vars[node.variable_destino] = opt.valor || opt.etiqueta || '';
                    refreshVars();
                }
                logEvt('info', 'Menú: opción "' + (opt.etiqueta || opt.valor) + '"');
                var salida = opt.salida || '';
                var dest = opt._legacy_destino
                    ? DATA.nodos[String(opt._legacy_destino)]
                    : buscarSalida(node, salida);
                if (!dest) {
                    systemBubble('— Sin destino para salida "' + salida + '" —', 'warn');
                    logEvt('error', 'Sin destino', { salida: salida });
                    return;
                }
                avanzarA(dest);
            });
            box.appendChild(b);
        });
        chat.appendChild(box);
        scroll();
    }
    function deshabilitar(container) {
        container.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
    }

    // ── pregunta (input texto) ──────────────────────────────────
    function mostrarInputTexto(node) {
        STATE.awaitingInput = true;
        STATE.currentPreguntaNode = node;
        textInputBar.style.display = 'flex';
        textField.disabled = false;
        textField.focus();
    }
    function ocultarInputTexto() {
        STATE.awaitingInput = false;
        STATE.currentPreguntaNode = null;
        textInputBar.style.display = 'none';
        textField.value = '';
    }
    if (textSend) textSend.addEventListener('click', enviarRespuestaTexto);
    if (textField) textField.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); enviarRespuestaTexto(); }
    });
    function enviarRespuestaTexto() {
        if (!STATE.awaitingInput) return;
        var txt = (textField.value || '').trim();
        if (!txt) return;
        var node = STATE.currentPreguntaNode;
        userBubble(txt);
        ocultarInputTexto();
        // Validación básica de cédula EC (longitud + dígito verificador)
        if (node.validacion_tipo === 'cedula' && !validarCedulaEC(txt)) {
            var mensajeError = (node.config && node.config.mensaje_error) ||
                'Cédula inválida. Reintenta.';
            botBubble(mensajeError);
            logEvt('warn', 'Validación cédula falló', { input: txt });
            mostrarInputTexto(node);
            return;
        }
        if (node.variable_destino) {
            STATE.vars[node.variable_destino] = txt;
            refreshVars();
            logEvt('info', 'Captura: ' + node.variable_destino + ' = "' + txt + '"');
        }
        avanzarA(siguienteDefault(node));
    }
    function validarCedulaEC(c) {
        if (!/^\d{10}$/.test(c)) return false;
        var d = c.split('').map(Number);
        if (d[2] >= 6) return false;
        var coef = [2,1,2,1,2,1,2,1,2], total = 0;
        for (var i = 0; i < 9; i++) {
            var p = d[i] * coef[i];
            total += (p >= 10) ? p - 9 : p;
        }
        return ((10 - total % 10) % 10) === d[9];
    }

    // ── http: mock o real ──────────────────────────────────────
    function ejecutarHttp(node) {
        var cfg = node.config || {};
        var metodo = (cfg.metodo || 'GET').toUpperCase();
        var pathResuelto = resolverExpr(cfg.path || '/');
        systemBubble('🌐 ' + metodo + ' ' + pathResuelto, 'http');

        if (STATE.mode !== 'real') {
            // Mock: muestra plantilla con vars actuales y avanza ok
            if (cfg.plantilla_respuesta) {
                botBubble(resolverExpr(cfg.plantilla_respuesta));
            }
            logEvt('info', '[mock] HTTP ' + metodo + ' ' + pathResuelto);
            avanzarA(buscarSalida(node, 'ok') || siguienteDefault(node));
            return;
        }

        // Real: llama al backend probar_http con la config + vars actuales.
        if (!node.endpoint_id) {
            systemBubble('⚠️ Nodo http sin endpoint configurado', 'warn');
            logEvt('error', 'Sin endpoint_id', { nodo: node.id });
            avanzarA(buscarSalida(node, 'error') || siguienteDefault(node));
            return;
        }
        var fd = new FormData();
        fd.append('action', 'probar_http');
        fd.append('csrfmiddlewaretoken', getCsrf());
        fd.append('endpoint_id', node.endpoint_id);
        fd.append('metodo', metodo);
        fd.append('path', cfg.path || '');
        fd.append('query_json', JSON.stringify(cfg.query || {}));
        fd.append('body_json', cfg.body == null ? '' : JSON.stringify(cfg.body));
        fd.append('headers_json', JSON.stringify(cfg.headers || {}));
        fd.append('variables_test_json', JSON.stringify(STATE.vars));

        fetch(window.DPPREV_PROBAR_URL || '/crm/departamentos_chatbots/', {
            method: 'POST', body: fd, credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (r) { return r.json(); }).then(function (resp) {
            if (!resp.ok) {
                systemBubble('⚠️ Error: ' + (resp.error || 'desconocido'), 'warn');
                logEvt('error', 'probar_http rechazó', resp);
                avanzarA(buscarSalida(node, 'error') || siguienteDefault(node));
                return;
            }
            logEvt(resp.etiqueta === 'ok' ? 'info' : 'error',
                   'HTTP ' + resp.status + ' (' + resp.etiqueta + ') · ' + resp.duracion_ms + 'ms',
                   { url: resp.url, body: resp.body, error: resp.error });

            // Mostrar la response del API en el chat con detalle expandible
            mostrarResponseEnChat(resp, cfg);

            // Aplicar extracciones a STATE.vars + reportar qué se extrajo
            var extrajo = {};
            (cfg.extraer || []).forEach(function (ex) {
                if (resp.etiqueta === 'ok' && ex.variable) {
                    var rawPath = (ex.jsonpath || '').replace(/^\$/, '').replace(/^\./, '');
                    var val = getPath(resp.body, rawPath);
                    STATE.vars[ex.variable] = val;
                    extrajo[ex.variable] = { jsonpath: ex.jsonpath, valor: val };
                }
            });
            refreshVars();
            if (Object.keys(extrajo).length) {
                mostrarExtraccionEnChat(extrajo);
                logEvt('info', 'Variables extraídas del response', extrajo);
            }

            if (resp.etiqueta === 'ok' && cfg.plantilla_respuesta) {
                botBubble(resolverExpr(cfg.plantilla_respuesta));
            } else if (resp.etiqueta === 'error') {
                systemBubble('❌ API retornó error: ' + (resp.error || 'HTTP ' + resp.status), 'warn');
            }
            avanzarA(buscarSalida(node, resp.etiqueta) || siguienteDefault(node));
        }).catch(function (err) {
            systemBubble('⚠️ Error de red: ' + err.message, 'warn');
            logEvt('error', 'fetch falló', { error: err.message });
            avanzarA(buscarSalida(node, 'error') || siguienteDefault(node));
        });
    }

    function mostrarResponseEnChat(resp, cfg) {
        var icono = (resp.etiqueta === 'ok') ? '✅' : '❌';
        var headerHtml = icono + ' <strong>HTTP ' + escHtml(resp.status || '0') + '</strong>'
            + ' · ' + escHtml(resp.metodo || '') + ' ' + escHtml(resp.url || '')
            + ' · <span class="text-muted">' + (resp.duracion_ms || 0) + 'ms</span>';
        if (resp.error) {
            headerHtml += '<div class="text-danger small mt-1">⚠️ ' + escHtml(resp.error) + '</div>';
        }
        var bodyStr = '';
        if (resp.body !== null && resp.body !== undefined) {
            try { bodyStr = JSON.stringify(resp.body, null, 2); }
            catch (e) { bodyStr = String(resp.body); }
        }
        var hint = '';
        if (cfg && (cfg.extraer || []).length) {
            hint = '<div class="dpprev-extraer-hint mt-2">'
                + '<small class="text-muted">Tu config <code>extraer</code>:</small>'
                + '<pre class="dpprev-extraer-pre">'
                + escHtml(JSON.stringify(cfg.extraer, null, 2))
                + '</pre></div>';
        }
        var detallesAbiertos = (resp.etiqueta !== 'ok') ? ' open' : '';
        var html = '<div class="dpprev-api-resp">'
            + '<div class="dpprev-api-header">' + headerHtml + '</div>'
            + '<details' + detallesAbiertos + '>'
            +   '<summary>📦 Response body (click para ver)</summary>'
            +   '<pre class="dpprev-api-body">' + escHtml(bodyStr || '(vacío)') + '</pre>'
            +   hint
            + '</details>'
            + '</div>';
        var n = el('div', 'dpprev-msg system system-api', html);
        chat.appendChild(n);
        scroll();
    }

    function mostrarExtraccionEnChat(extrajo) {
        var rows = Object.keys(extrajo).map(function (k) {
            var v = extrajo[k].valor;
            var vDisp = (v === null || v === undefined) ? '<em class="text-danger">null/undefined</em>'
                      : (typeof v === 'object') ? '<code>' + escHtml(JSON.stringify(v)) + '</code>'
                      : '<code>' + escHtml(String(v)) + '</code>';
            return '<tr>'
                +   '<td><code>' + escHtml(k) + '</code></td>'
                +   '<td><code class="text-muted">' + escHtml(extrajo[k].jsonpath) + '</code></td>'
                +   '<td>' + vDisp + '</td>'
                + '</tr>';
        }).join('');
        var html = '<div class="dpprev-extraer-result">'
            + '<div class="small fw-bold mb-1">📥 Variables extraídas:</div>'
            + '<table class="dpprev-extraer-table">'
            +   '<thead><tr><th>variable</th><th>jsonpath</th><th>valor</th></tr></thead>'
            +   '<tbody>' + rows + '</tbody>'
            + '</table></div>';
        var n = el('div', 'dpprev-msg system system-api', html);
        chat.appendChild(n);
        scroll();
    }

    function getPath(obj, path) {
        var parts = (path || '').match(/[^.\[\]]+|\[\d+\]/g) || [];
        var cur = obj;
        for (var i = 0; i < parts.length; i++) {
            if (cur == null) return null;
            var p = parts[i];
            if (p.charAt(0) === '[') {
                var idx = parseInt(p.slice(1, -1), 10);
                cur = (Array.isArray(cur) && idx >= 0 && idx < cur.length) ? cur[idx] : null;
            } else if (typeof cur === 'object') {
                cur = cur[p];
            } else { return null; }
        }
        return cur;
    }
    function getCsrf() {
        var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    // ── condicional: evalúa local ──────────────────────────────
    function evalCondicion(c) {
        var izq = resolverExpr(c.izq);
        var der = resolverExpr(c.der);
        var op = (c.op || '==').trim();
        if (op === 'vacio')      return !izq;
        if (op === 'no_vacio')   return !!izq;
        if (op === '==')         return String(izq) === String(der);
        if (op === '!=')         return String(izq) !== String(der);
        if (op === 'contiene')   return String(izq || '').toLowerCase().indexOf(String(der || '').toLowerCase()) >= 0;
        if (op === 'no_contiene')return String(izq || '').toLowerCase().indexOf(String(der || '').toLowerCase()) < 0;
        if (['>', '<', '>=', '<='].indexOf(op) >= 0) {
            var a = parseFloat(izq), b = parseFloat(der);
            if (isNaN(a) || isNaN(b)) return false;
            if (op === '>')  return a > b;
            if (op === '<')  return a < b;
            if (op === '>=') return a >= b;
            if (op === '<=') return a <= b;
        }
        return false;
    }
    function evaluarCondicional(node) {
        var cfg = node.config || {};
        var operador = (cfg.operador || 'and').toLowerCase();
        var conds = cfg.condiciones || [];
        var resultado;
        if (operador === 'or') {
            resultado = conds.some(evalCondicion);
        } else {
            resultado = conds.length === 0 ? true : conds.every(evalCondicion);
        }
        var rama = resultado ? 'true' : 'false';
        systemBubble('🔀 Condicional: ' + (resultado ? '✅ Sí' : '❌ No'), 'cond');
        logEvt('info', 'Condicional → ' + rama,
               { operador: operador, condiciones: conds, vars: STATE.vars });
        var dest = buscarSalida(node, rama);
        if (!dest) {
            systemBubble('— Rama "' + rama + '" sin destino —', 'warn');
            logEvt('warn', 'Sin destino para rama ' + rama);
            return;
        }
        avanzarA(dest);
    }

    // ── cta_url + ubicacion ────────────────────────────────────
    function renderCtaUrl(node) {
        var cfg = node.config || {};
        var box = el('div', 'dpprev-buttons');
        var a = document.createElement('a');
        a.className = 'dpprev-cta';
        a.href = cfg.url || '#';
        a.target = '_blank';
        a.rel = 'noopener';
        a.innerHTML = '<i class="fa fa-external-link-alt me-1"></i> '
            + escHtml(cfg.display_text || 'Abrir');
        box.appendChild(a);
        chat.appendChild(box);
        scroll();
    }
    function renderLocation(node) {
        var cfg = node.config || {};
        var card = el('div', 'dpprev-location');
        card.appendChild(el('div', 'dpprev-location-map', '<i class="fa fa-map-marker-alt"></i>'));
        var info = el('div', 'dpprev-location-info');
        info.innerHTML = '<strong>' + escHtml(cfg.name || 'Ubicación') + '</strong>'
            + escHtml(cfg.address || '')
            + '<br><small class="text-muted">' + (cfg.lat || 0) + ', ' + (cfg.lng || 0) + '</small>';
        card.appendChild(info);
        chat.appendChild(card);
        scroll();
    }

    // ── Inicio / Reset ──────────────────────────────────────────
    // Inicio "blando" — preserva variables capturadas (cédula, matricula_id…)
    // como hace WhatsApp entre mensajes de la misma conversación.
    function start(opts) {
        opts = opts || {};
        if (opts.limpiarMemoria) {
            STATE.vars = {};
            limpiarMemoriaPersistente();
        }
        STATE.currentId = null;
        STATE.ended = false;
        STATE.awaitingInput = false;
        chat.innerHTML = '';
        if (logBox) logBox.innerHTML = '';
        refreshVars();
        ocultarInputTexto();

        var dep = DATA.departamento || {};
        if (dep.mensaje_saludo) botBubble(dep.mensaje_saludo);
        var memCount = Object.keys(STATE.vars).length;
        if (memCount > 0) {
            systemBubble('💾 Memoria recuperada: ' + memCount
                       + ' variable(s) (cédula, matrícula, etc.)', 'memo');
            logEvt('info', 'Vars cargadas de localStorage', STATE.vars);
        }
        logEvt('info', 'Inicio del simulador (modo: ' + STATE.mode
                       + (memCount ? ', con memoria' : ', sin memoria') + ')');

        var inicioId = DATA.inicio_id;
        if (!inicioId) {
            systemBubble('— Departamento sin nodo de inicio —', 'warn');
            return;
        }
        setTimeout(function () { avanzarA(inicioId); }, 300);
    }

    // Reset suave (mantiene memoria, solo reinicia conversación)
    if (btnReset) btnReset.addEventListener('click', function () { start(); });

    // Botón "limpiar memoria" en panel derecho
    var btnLimpiar = document.getElementById('dpprev-clear-mem');
    if (btnLimpiar) btnLimpiar.addEventListener('click', function () {
        if (confirm('¿Borrar todas las variables guardadas (cédula, matrícula, etc.)?')) {
            start({ limpiarMemoria: true });
        }
    });

    if (modeToggle) {
        modeToggle.checked = (STATE.mode === 'real');
        modeToggle.addEventListener('change', function () {
            STATE.mode = modeToggle.checked ? 'real' : 'mock';
            try { localStorage.setItem(MODE_KEY, STATE.mode); } catch (e) {}
            logEvt('info', 'Modo cambiado a: ' + STATE.mode);
        });
    }
    start();
})();
