/* dpchat_preview.js — simulador WhatsApp-like del flujo del depto.
   Toma el JSON de #dp-preview-data y deja al usuario navegar tocando los
   botones que el bot expondría en Cloud API. */

(function () {
    'use strict';

    var dataEl = document.getElementById('dp-preview-data');
    if (!dataEl) return;
    var DATA;
    try { DATA = JSON.parse(dataEl.textContent); }
    catch (e) { console.error('preview JSON invalido', e); return; }

    var chat = document.getElementById('dpprev-chat');
    var btnReset = document.getElementById('dpprev-reset');

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
    function systemBubble(text) {
        var n = el('div', 'dpprev-msg system', escHtml(text));
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
            setTimeout(function () {
                t.remove();
                resolve();
            }, ms || 600);
        });
    }

    function renderButtons(hijos) {
        // Meta: ≤3 buttons, >3 list. Para preview simplificamos como botones.
        var box = el('div', 'dpprev-buttons');
        hijos.forEach(function (h) {
            var b = el('button', 'dpprev-btn');
            b.type = 'button';
            b.textContent = h.nombre || '(sin nombre)';
            b.addEventListener('click', function () {
                disableButtons(box);
                userBubble(h.nombre || '');
                setTimeout(function () { ejecutarNodo(h); }, 200);
            });
            box.appendChild(b);
        });
        chat.appendChild(box);
        scroll();
    }
    function disableButtons(container) {
        container.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
    }

    function renderCtaUrl(node) {
        var cfg = node.config || {};
        var box = el('div', 'dpprev-buttons');
        var a = document.createElement('a');
        a.className = 'dpprev-cta';
        a.href = cfg.url || '#';
        a.target = '_blank';
        a.rel = 'noopener';
        a.innerHTML = '<i class="fa fa-external-link-alt me-1"></i> '
            + escHtml(cfg.display_text || 'Abrir enlace');
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

    function ejecutarNodo(node) {
        typing().then(function () {
            // Cuerpo del nodo (todos los tipos pueden tener body excepto location pura)
            if (node.respuesta) botBubble(node.respuesta);

            // Despacho por tipo nativo
            if (node.tipo === 'cta_url') {
                renderCtaUrl(node);
            } else if (node.tipo === 'ubicacion') {
                renderLocation(node);
            }

            if (node.tipo === 'handoff') {
                systemBubble('🤝 [Bot derivó la conversación a un humano]');
                return;
            }
            if (node.tipo === 'fin') {
                systemBubble('🏁 [Flujo terminado]');
                return;
            }
            // Hijos → botones interactive
            if (node.hijos && node.hijos.length) {
                renderButtons(node.hijos);
            } else {
                systemBubble('— Sin más opciones desde este nodo —');
            }
        });
    }

    function start() {
        chat.innerHTML = '';
        // Saludo del depto (si existe)
        if (DATA.departamento && DATA.departamento.mensaje_saludo) {
            botBubble(DATA.departamento.mensaje_saludo);
        }
        // Encontrar root (es_inicio o el primero)
        var raices = DATA.raices || [];
        if (!raices.length) {
            systemBubble('El depto no tiene opciones cargadas.');
            return;
        }
        var inicio = raices.find(function (r) { return r.es_inicio; }) || raices[0];
        setTimeout(function () { ejecutarNodo(inicio); }, 400);
    }

    if (btnReset) btnReset.addEventListener('click', start);
    start();
})();
