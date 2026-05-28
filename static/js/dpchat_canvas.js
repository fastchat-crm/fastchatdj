(function () {
    var dataEl = document.getElementById('dp-canvas-data');
    var container = document.getElementById('dp-canvas');
    var emptyEl = document.getElementById('dpc-empty');
    if (!dataEl || !container) {
        return;
    }

    var G;
    try {
        G = JSON.parse(dataEl.textContent || '{}');
    } catch (e) {
        G = { nodos: [] };
    }

    var dot = document.querySelector('.dpc-dot');
    if (dot && dot.dataset.color) {
        dot.style.background = dot.dataset.color;
    }

    if (!G.nodos || !G.nodos.length) {
        if (emptyEl) {
            emptyEl.hidden = false;
        }
        return;
    }

    var TIPO_ICON = {
        menu: 'fa-list', respuesta: 'fa-comment', pregunta: 'fa-circle-question',
        http: 'fa-cloud', funcion: 'fa-gear', condicional: 'fa-code-branch',
        set_variable: 'fa-equals', cta_url: 'fa-link', ubicacion: 'fa-location-dot',
        handoff: 'fa-headset', agenda_turno: 'fa-calendar-check', loop: 'fa-rotate',
        fin: 'fa-flag-checkered'
    };

    function escapeHtml(s) {
        return (s || '').replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    var NODE_W = 230;
    var NODE_H = 96;

    var pos = {};
    var faltanPos = G.nodos.every(function (n) { return !n.x && !n.y; });
    if (faltanPos && window.dagre) {
        var g = new dagre.graphlib.Graph();
        g.setGraph({ rankdir: 'TB', nodesep: 55, ranksep: 95, marginx: 50, marginy: 40 });
        g.setDefaultEdgeLabel(function () { return {}; });
        G.nodos.forEach(function (n) {
            g.setNode(String(n.id), { width: NODE_W, height: NODE_H });
        });
        G.nodos.forEach(function (n) {
            (n.salidas || []).forEach(function (s) {
                if (s.destino_id) {
                    g.setEdge(String(n.id), String(s.destino_id));
                }
            });
        });
        dagre.layout(g);
        G.nodos.forEach(function (n) {
            var dn = g.node(String(n.id));
            if (dn) {
                pos[n.id] = { x: dn.x - NODE_W / 2, y: dn.y - NODE_H / 2 };
            }
        });
    } else {
        G.nodos.forEach(function (n) {
            pos[n.id] = { x: n.x || 40, y: n.y || 40 };
        });
    }

    var editor = new Drawflow(container);
    editor.reroute = true;
    editor.start();

    function nodeHtml(n) {
        var icon = TIPO_ICON[n.tipo] || 'fa-circle';
        var inicio = n.es_inicio ? '<span class="dpc-node-start">INICIO</span>' : '';
        var resp = n.respuesta
            ? '<div class="dpc-node-resp">' + escapeHtml(n.respuesta) + '</div>'
            : '';
        return '' +
            '<div class="dpc-node tipo-' + n.tipo + '" data-nodo-id="' + n.id + '">' +
            '  <div class="dpc-node-head">' +
            '    <i class="fa ' + icon + '"></i>' +
            '    <span class="dpc-node-tipo">' + escapeHtml(n.tipo_label) + '</span>' +
            inicio +
            '  </div>' +
            '  <div class="dpc-node-name">' + escapeHtml(n.nombre || '(sin nombre)') + '</div>' +
            resp +
            '</div>';
    }

    var idToDf = {};
    G.nodos.forEach(function (n) {
        var nOut = Math.max(1, (n.salidas || []).length);
        var nIn = n.es_inicio ? 0 : 1;
        var p = pos[n.id] || { x: 40, y: 40 };
        var dfId = editor.addNode(
            'n' + n.id, nIn, nOut, p.x, p.y,
            'dpc-df-node tipo-' + n.tipo,
            { dbId: n.id }, nodeHtml(n)
        );
        idToDf[n.id] = dfId;
    });

    G.nodos.forEach(function (n) {
        (n.salidas || []).forEach(function (s, idx) {
            if (!s.destino_id || !(s.destino_id in idToDf)) {
                return;
            }
            try {
                editor.addConnection(
                    idToDf[n.id], idToDf[s.destino_id],
                    'output_' + (idx + 1), 'input_1'
                );
            } catch (e) {
                /* conexión inválida, se ignora */
            }
        });
    });

    var zoomBtns = document.querySelectorAll('.dpc-zoom-btn');
    Array.prototype.forEach.call(zoomBtns, function (b) {
        b.addEventListener('click', function () {
            var z = b.dataset.zoom;
            if (z === 'in') {
                editor.zoom_in();
            } else if (z === 'out') {
                editor.zoom_out();
            } else if (z === 'reset') {
                editor.zoom_reset();
            } else if (z === 'fit') {
                window.location.reload();
            }
        });
    });
})();
