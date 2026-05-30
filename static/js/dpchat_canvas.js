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

    var DEPTO_ID = (G.departamento && G.departamento.id) || 0;
    var BASE_URL = '/crm/departamentos_chatbots/';

    function getCsrf() {
        var inp = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (inp && inp.value) {
            return inp.value;
        }
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    function confirmar(titulo, texto) {
        if (typeof Swal === 'undefined') {
            return Promise.resolve(window.confirm(titulo + '\n\n' + (texto || '')));
        }
        return Swal.fire({
            title: titulo,
            text: texto || '',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Sí, eliminar',
            cancelButtonText: 'Cancelar',
            confirmButtonColor: '#dc2626',
            cancelButtonColor: '#6b7280'
        }).then(function (r) { return !!(r && (r.value || r.isConfirmed)); });
    }

    function notifyError(msg) {
        if (typeof Swal !== 'undefined') {
            Swal.fire({ icon: 'error', title: 'Error', text: msg || 'Ocurrió un error.' });
        } else {
            window.alert(msg || 'Ocurrió un error.');
        }
    }

    var TIPO_ICON = {
        menu: 'fa-list', respuesta: 'fa-comment', pregunta: 'fa-circle-question',
        http: 'fa-cloud', funcion: 'fa-gear', condicional: 'fa-code-branch',
        set_variable: 'fa-equals', cta_url: 'fa-link', ubicacion: 'fa-location-dot',
        handoff: 'fa-headset', agenda_turno: 'fa-calendar-check', loop: 'fa-rotate',
        fin: 'fa-flag-checkered'
    };

    var TIPO_COLOR = {
        menu: '#8b5cf6', respuesta: '#16a34a', pregunta: '#f59e0b', http: '#3b82f6',
        funcion: '#5b21b6', condicional: '#ec4899', set_variable: '#06b6d4',
        cta_url: '#2563eb', ubicacion: '#6b21a8', handoff: '#f97316',
        agenda_turno: '#0d9488', loop: '#d97706', fin: '#64748b'
    };

    var TIPO_AYUDA = {
        menu: 'Botones interactive. Las opciones salen de los nodos hijos, de la tabla inline o de una variable (opciones_fuente).',
        respuesta: 'Envía un texto al cliente. Puede anexar un botón CTA con URL externa.',
        pregunta: 'Pide un dato y lo guarda en la variable destino. Soporta validación y reintentos.',
        http: 'Llama una API: endpoint + método + path. Extrae datos de la respuesta a variables. Salidas ok / error.',
        funcion: 'Ejecuta una función Python interna (funcion_codigo) sin saltos de red. Salidas ok / error.',
        condicional: 'Evalúa condiciones sobre las variables y ramifica por las aristas true / false.',
        set_variable: 'Asigna una lista de variable = expresión y avanza por la salida default.',
        cta_url: 'Mensaje con un único botón que abre una URL externa (pago, formulario, web).',
        ubicacion: 'Envía una ubicación (lat/lng) que el cliente abre en su mapa.',
        handoff: 'Deriva la conversación a un asesor humano.',
        agenda_turno: 'Reservar, cancelar o reagendar un turno usando la agenda de la sesión (grupo_agenda).',
        loop: 'Itera N veces. Salida body en cada vuelta, done al terminar. El índice queda en {{variables.i}}.',
        fin: 'Cierra la conversación.'
    };

    function escapeHtml(s) {
        return (s || '').replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    var NODE_W = 250;
    var NODE_H = 120;

    if (!G.nodos || !G.nodos.length) {
        if (emptyEl) {
            emptyEl.hidden = false;
        }
        bindNuevoPasoBtn(null);
        return;
    }

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
        var accion = n.accion
            ? '<div class="dpc-node-accion"><i class="fa fa-bolt"></i> ' + escapeHtml(n.accion) + '</div>'
            : '';
        var flags = (n.flags && n.flags.length)
            ? '<div class="dpc-node-flags">' + n.flags.map(function (f) {
                  return '<span class="dpc-node-flag">' + escapeHtml(f) + '</span>';
              }).join('') + '</div>'
            : '';
        return '' +
            '<div class="dpc-node tipo-' + n.tipo + '" data-nodo-id="' + n.id + '" data-tipo="' + n.tipo + '">' +
            '  <div class="dpc-node-head">' +
            '    <i class="fa ' + icon + '"></i>' +
            '    <span class="dpc-node-tipo">' + escapeHtml(n.tipo_label) + '</span>' +
            inicio +
            '  </div>' +
            '  <div class="dpc-node-name">' + escapeHtml(n.nombre || '(sin nombre)') + '</div>' +
            accion +
            flags +
            resp +
            '  <div class="dpc-node-actions">' +
            '    <button type="button" class="dpc-node-act" data-act="edit" data-nodo-id="' + n.id + '" title="Editar">' +
            '      <i class="fa fa-pen"></i>' +
            '    </button>' +
            '    <button type="button" class="dpc-node-act" data-act="ficha" data-nodo-id="' + n.id + '" title="Ver detalle y traza">' +
            '      <i class="fa fa-circle-info"></i>' +
            '    </button>' +
            '    <button type="button" class="dpc-node-act dpc-node-act-danger" data-act="del" data-nodo-id="' + n.id + '" title="Eliminar">' +
            '      <i class="fa fa-trash"></i>' +
            '    </button>' +
            '  </div>' +
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

    container.addEventListener('mousedown', function (e) {
        if (e.target.closest('.dpc-node-act')) {
            e.stopPropagation();
        }
    }, true);

    container.addEventListener('click', function (e) {
        var btn = e.target.closest('.dpc-node-act');
        if (!btn) {
            return;
        }
        e.stopPropagation();
        e.preventDefault();
        var act = btn.dataset.act;
        var nodoId = parseInt(btn.dataset.nodoId, 10);
        if (act === 'edit') {
            abrirFormNodo(nodoId);
        } else if (act === 'ficha') {
            abrirFicha(nodoId);
        } else if (act === 'del') {
            eliminarNodo(nodoId);
        }
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

    function applyPanTransform() {
        if (!editor.precanvas) {
            return;
        }
        editor.precanvas.style.transform =
            'translate(' + editor.pos_x + 'px, ' + editor.pos_y + 'px) scale(' + editor.zoom + ')';
        editor.precanvas.style.transformOrigin = '0 0';
        updateScrollbars();
    }

    container.addEventListener('wheel', function (e) {
        e.preventDefault();
        if (e.ctrlKey || e.metaKey) {
            if (e.deltaY < 0) {
                editor.zoom_in();
            } else if (e.deltaY > 0) {
                editor.zoom_out();
            }
            setTimeout(updateScrollbars, 0);
            return;
        }
        if (e.shiftKey) {
            editor.pos_x -= e.deltaY;
        } else {
            editor.pos_y -= e.deltaY;
            editor.pos_x -= e.deltaX;
        }
        applyPanTransform();
    }, { passive: false });

    var stage = document.querySelector('.dpc-stage');
    var handBtn = document.getElementById('dpcBtnHand');
    var panMode = false;
    var dragging = false;
    var startX = 0;
    var startY = 0;
    var startPosX = 0;
    var startPosY = 0;

    function setPanMode(active) {
        panMode = !!active;
        if (stage) {
            stage.classList.toggle('dpc-pan-mode', panMode);
        }
        if (handBtn) {
            handBtn.classList.toggle('is-active', panMode);
        }
    }

    if (handBtn) {
        handBtn.addEventListener('click', function () { setPanMode(!panMode); });
    }

    container.addEventListener('mousedown', function (e) {
        if (!panMode) { return; }
        if (e.target.closest('.dpc-node-act')) { return; }
        e.preventDefault();
        e.stopPropagation();
        dragging = true;
        startX = e.clientX;
        startY = e.clientY;
        startPosX = editor.pos_x;
        startPosY = editor.pos_y;
        if (stage) { stage.classList.add('dpc-grabbing'); }
    }, true);

    document.addEventListener('mousemove', function (e) {
        if (!dragging) { return; }
        editor.pos_x = startPosX + (e.clientX - startX);
        editor.pos_y = startPosY + (e.clientY - startY);
        applyPanTransform();
    });

    document.addEventListener('mouseup', function () {
        if (!dragging) { return; }
        dragging = false;
        if (stage) { stage.classList.remove('dpc-grabbing'); }
    });

    var scrollH = document.getElementById('dpcScrollH');
    var scrollV = document.getElementById('dpcScrollV');
    var thumbH = document.getElementById('dpcScrollHThumb');
    var thumbV = document.getElementById('dpcScrollVThumb');

    function getBBox() {
        var nodes = container.querySelectorAll('.drawflow-node');
        if (!nodes.length) { return null; }
        var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        Array.prototype.forEach.call(nodes, function (el) {
            var x = parseFloat(el.style.left) || 0;
            var y = parseFloat(el.style.top) || 0;
            var w = el.offsetWidth || NODE_W;
            var h = el.offsetHeight || NODE_H;
            if (x < minX) { minX = x; }
            if (y < minY) { minY = y; }
            if (x + w > maxX) { maxX = x + w; }
            if (y + h > maxY) { maxY = y + h; }
        });
        var pad = 200;
        return {
            x: minX - pad,
            y: minY - pad,
            w: (maxX - minX) + 2 * pad,
            h: (maxY - minY) + 2 * pad
        };
    }

    function updateScrollbars() {
        if (!scrollH || !scrollV || !thumbH || !thumbV) { return; }
        var rect = container.getBoundingClientRect();
        var bbox = getBBox();
        if (!bbox) {
            scrollH.style.display = 'none';
            scrollV.style.display = 'none';
            return;
        }
        var z = editor.zoom || 1;
        var contentW = bbox.w * z;
        var contentH = bbox.h * z;
        var viewportW = rect.width;
        var viewportH = rect.height;

        if (contentW <= viewportW) {
            scrollH.style.display = 'none';
        } else {
            scrollH.style.display = 'block';
            var trackW = scrollH.clientWidth;
            var thumbW = Math.max(40, trackW * (viewportW / contentW));
            var origenVistaX = -(editor.pos_x + bbox.x * z);
            var maxScrollX = contentW - viewportW;
            var ratioX = maxScrollX > 0 ? Math.max(0, Math.min(1, origenVistaX / maxScrollX)) : 0;
            thumbH.style.width = thumbW + 'px';
            thumbH.style.left = ((trackW - thumbW) * ratioX) + 'px';
        }

        if (contentH <= viewportH) {
            scrollV.style.display = 'none';
        } else {
            scrollV.style.display = 'block';
            var trackH = scrollV.clientHeight;
            var thumbHh = Math.max(40, trackH * (viewportH / contentH));
            var origenVistaY = -(editor.pos_y + bbox.y * z);
            var maxScrollY = contentH - viewportH;
            var ratioY = maxScrollY > 0 ? Math.max(0, Math.min(1, origenVistaY / maxScrollY)) : 0;
            thumbV.style.height = thumbHh + 'px';
            thumbV.style.top = ((trackH - thumbHh) * ratioY) + 'px';
        }
    }

    function bindScrollDrag(track, thumb, eje) {
        if (!track || !thumb) { return; }
        var draggingThumb = false;
        var offset = 0;
        thumb.addEventListener('mousedown', function (e) {
            e.preventDefault();
            e.stopPropagation();
            draggingThumb = true;
            offset = (eje === 'x' ? e.clientX - thumb.getBoundingClientRect().left
                                  : e.clientY - thumb.getBoundingClientRect().top);
        });
        document.addEventListener('mousemove', function (e) {
            if (!draggingThumb) { return; }
            var rect = track.getBoundingClientRect();
            var bbox = getBBox();
            if (!bbox) { return; }
            var z = editor.zoom || 1;
            if (eje === 'x') {
                var trackW = rect.width;
                var thumbW = thumb.offsetWidth;
                var posInTrack = e.clientX - rect.left - offset;
                posInTrack = Math.max(0, Math.min(trackW - thumbW, posInTrack));
                var ratio = (trackW - thumbW) > 0 ? posInTrack / (trackW - thumbW) : 0;
                var contentW = bbox.w * z;
                var viewportW = container.getBoundingClientRect().width;
                var maxScroll = contentW - viewportW;
                editor.pos_x = -(ratio * maxScroll) - bbox.x * z;
            } else {
                var trackH = rect.height;
                var thumbH = thumb.offsetHeight;
                var posInTrackY = e.clientY - rect.top - offset;
                posInTrackY = Math.max(0, Math.min(trackH - thumbH, posInTrackY));
                var ratioY = (trackH - thumbH) > 0 ? posInTrackY / (trackH - thumbH) : 0;
                var contentH = bbox.h * z;
                var viewportH = container.getBoundingClientRect().height;
                var maxScrollY = contentH - viewportH;
                editor.pos_y = -(ratioY * maxScrollY) - bbox.y * z;
            }
            applyPanTransform();
        });
        document.addEventListener('mouseup', function () { draggingThumb = false; });
    }

    bindScrollDrag(scrollH, thumbH, 'x');
    bindScrollDrag(scrollV, thumbV, 'y');

    setTimeout(updateScrollbars, 50);
    window.addEventListener('resize', updateScrollbars);

    var origRemoveNode = editor.removeNodeId.bind(editor);
    editor.removeNodeId = function (id) {
        var domNode = document.getElementById(id);
        var dbId = null;
        if (domNode) {
            var inner = domNode.querySelector('.dpc-node');
            if (inner && inner.dataset.nodoId) {
                dbId = parseInt(inner.dataset.nodoId, 10);
            }
        }
        if (dbId) {
            eliminarNodo(dbId, true, id);
        } else {
            confirmar('¿Eliminar este paso?', 'Se quitará del flujo.')
                .then(function (ok) { if (ok) { origRemoveNode(id); } });
        }
    };

    var origRemoveConnection = editor.removeConnection.bind(editor);
    editor.removeConnection = function () {
        confirmar('¿Eliminar esta conexión?',
            'Se quitará el vínculo entre los dos pasos. La eliminación persistente estará disponible al editar el nodo origen.'
        ).then(function (ok) {
            if (ok) {
                origRemoveConnection();
            }
        });
    };

    bindNuevoPasoBtn(editor);

    function bindNuevoPasoBtn(_editor) {
        var btn = document.getElementById('dpcBtnNuevo');
        if (!btn) {
            return;
        }
        btn.addEventListener('click', function () {
            abrirFormNodo(0);
        });
    }

    function abrirFormNodo(nodoId) {
        var titleEl = document.getElementById('dpcFormTitle');
        var bodyEl = document.getElementById('dpcFormBody');
        var modalEl = document.getElementById('dpcFormModal');
        if (!modalEl || !bodyEl) { return; }
        titleEl.innerHTML = nodoId
            ? '<i class="fa fa-pen me-1 text-primary"></i> Editar paso'
            : '<i class="fa fa-plus me-1 text-primary"></i> Nuevo paso';
        bodyEl.innerHTML = '<div class="text-center text-muted py-4"><i class="fa fa-spinner fa-spin me-2"></i>Cargando…</div>';
        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
        var url = BASE_URL + '?action=editar_opcion&id=' + nodoId +
                  '&departamento_id=' + DEPTO_ID + '&full=1';
        fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.result && d.data) {
                    bodyEl.innerHTML = d.data;
                } else {
                    bodyEl.innerHTML = '<div class="alert alert-danger">' +
                        escapeHtml(d && d.message ? d.message : 'No se pudo cargar el formulario.') +
                        '</div>';
                }
            })
            .catch(function () {
                bodyEl.innerHTML = '<div class="alert alert-danger">Error de red al cargar el formulario.</div>';
            });
    }

    function abrirFicha(nodoId) {
        var bodyEl = document.getElementById('dpcFichaBody');
        var modalEl = document.getElementById('dpcFichaModal');
        if (!modalEl || !bodyEl) { return; }
        bodyEl.innerHTML = '<div class="text-center text-muted py-4"><i class="fa fa-spinner fa-spin me-2"></i>Cargando…</div>';
        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
        var url = BASE_URL + '?action=ficha_opcion&id=' + nodoId;
        fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.result && d.data) {
                    bodyEl.innerHTML = d.data;
                } else {
                    bodyEl.innerHTML = '<div class="alert alert-danger">' +
                        escapeHtml(d && d.message ? d.message : 'No se pudo cargar la ficha.') +
                        '</div>';
                }
            })
            .catch(function () {
                bodyEl.innerHTML = '<div class="alert alert-danger">Error de red al cargar la ficha.</div>';
            });
    }

    function eliminarNodo(nodoId, suprimirConfirmExterno, dfNodoId) {
        confirmar('¿Eliminar este paso?',
            'Se eliminará el nodo y sus descendientes directos. Esta acción se persiste en el servidor (soft-delete).'
        ).then(function (ok) {
            if (!ok) { return; }
            var fd = new FormData();
            fd.append('action', 'eliminar_opcion');
            fd.append('opcion_id', String(nodoId));
            fd.append('csrfmiddlewaretoken', getCsrf());
            fetch(BASE_URL, {
                method: 'POST', body: fd, credentials: 'same-origin',
                headers: { 'X-CSRFToken': getCsrf() }
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d && (d.ok === true || d.result === true)) {
                      window.location.reload();
                  } else {
                      notifyError((d && (d.error || d.message)) || 'No se pudo eliminar.');
                  }
              }).catch(function () {
                  notifyError('Error de red al eliminar.');
              });
        });
    }

    setupLeyendaYFiltros();

    function setupLeyendaYFiltros() {
        var tipos = (G.tipos || []).filter(function (t) { return true; });
        var labelByTipo = {};
        tipos.forEach(function (t) { labelByTipo[t.value] = t.label; });

        var legendBody = document.getElementById('dpcLegendBody');
        if (legendBody) {
            legendBody.innerHTML = tipos.map(function (t) {
                var color = TIPO_COLOR[t.value] || '#94a3b8';
                var icon = TIPO_ICON[t.value] || 'fa-circle';
                var ayuda = TIPO_AYUDA[t.value] || '';
                return '<div class="dpc-legend-item">' +
                    '<span class="dpc-legend-swatch" style="background:' + color + '"></span>' +
                    '<div class="dpc-legend-text">' +
                    '<span class="dpc-legend-tipo"><i class="fa ' + icon + '"></i> ' + escapeHtml(t.label) + '</span>' +
                    '<span class="dpc-legend-ayuda">' + escapeHtml(ayuda) + '</span>' +
                    '</div></div>';
            }).join('');
        }

        var legend = document.getElementById('dpcLegend');
        var btnLeyenda = document.getElementById('dpcBtnLeyenda');
        var btnClose = document.getElementById('dpcLegendClose');
        if (btnLeyenda && legend) {
            btnLeyenda.addEventListener('click', function () {
                legend.hidden = !legend.hidden;
                btnLeyenda.classList.toggle('is-active', !legend.hidden);
            });
        }
        if (btnClose && legend) {
            btnClose.addEventListener('click', function () {
                legend.hidden = true;
                if (btnLeyenda) { btnLeyenda.classList.remove('is-active'); }
            });
        }

        var filtros = document.getElementById('dpcFiltros');
        if (!filtros) { return; }
        var presentes = [];
        var vistos = {};
        (G.nodos || []).forEach(function (n) {
            if (!vistos[n.tipo]) { vistos[n.tipo] = true; presentes.push(n.tipo); }
        });
        if (presentes.length < 2) { return; }

        var chips = ['<button type="button" class="dpc-chip is-active" data-tipo="">Todos</button>'];
        presentes.forEach(function (tp) {
            var color = TIPO_COLOR[tp] || '#94a3b8';
            chips.push('<button type="button" class="dpc-chip" data-tipo="' + tp + '">' +
                '<span class="dpc-chip-dot" style="background:' + color + '"></span>' +
                escapeHtml(labelByTipo[tp] || tp) + '</button>');
        });
        filtros.innerHTML = chips.join('');

        filtros.addEventListener('click', function (e) {
            var chip = e.target.closest('.dpc-chip');
            if (!chip) { return; }
            var tipo = chip.getAttribute('data-tipo') || '';
            Array.prototype.forEach.call(filtros.querySelectorAll('.dpc-chip'), function (c) {
                c.classList.toggle('is-active', c === chip);
            });
            aplicarFiltro(tipo);
        });
    }

    function aplicarFiltro(tipo) {
        var nodes = container.querySelectorAll('.drawflow-node');
        Array.prototype.forEach.call(nodes, function (el) {
            var inner = el.querySelector('.dpc-node');
            var t = inner ? inner.getAttribute('data-tipo') : '';
            var match = !tipo || t === tipo;
            el.classList.toggle('dpc-dim', !match);
        });
    }

    var formEl = document.getElementById('dpcFormNodo');
    if (formEl) {
        formEl.addEventListener('submit', function (ev) {
            ev.preventDefault();
            var submitBtn = formEl.querySelector('button[type="submit"]');
            if (submitBtn) { submitBtn.disabled = true; }
            var fd = new FormData(formEl);
            if (!fd.get('csrfmiddlewaretoken')) {
                fd.append('csrfmiddlewaretoken', getCsrf());
            }
            fetch(BASE_URL, {
                method: 'POST', body: fd, credentials: 'same-origin',
                headers: { 'X-CSRFToken': getCsrf() }
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d && (d.ok === true || d.result === true || d.error === false)) {
                      window.location.reload();
                  } else {
                      if (submitBtn) { submitBtn.disabled = false; }
                      notifyError((d && (d.message || d.error)) || 'No se pudo guardar.');
                  }
              }).catch(function () {
                  if (submitBtn) { submitBtn.disabled = false; }
                  notifyError('Error de red al guardar.');
              });
        });
    }
})();
