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
        return '' +
            '<div class="dpc-node tipo-' + n.tipo + '" data-nodo-id="' + n.id + '">' +
            '  <div class="dpc-node-head">' +
            '    <i class="fa ' + icon + '"></i>' +
            '    <span class="dpc-node-tipo">' + escapeHtml(n.tipo_label) + '</span>' +
            inicio +
            '  </div>' +
            '  <div class="dpc-node-name">' + escapeHtml(n.nombre || '(sin nombre)') + '</div>' +
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
    }

    container.addEventListener('wheel', function (e) {
        e.preventDefault();
        if (e.ctrlKey || e.metaKey) {
            if (e.deltaY < 0) {
                editor.zoom_in();
            } else if (e.deltaY > 0) {
                editor.zoom_out();
            }
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
