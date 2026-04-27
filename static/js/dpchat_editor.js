/* dpchat_editor.js — editor full-page de Departamento + ChatBot.
   Render del arbol es server-side (cards en el HTML). Aca solo:
   - Autosave debounced de la cabecera (nombre/color/saludo)
   - Click en "Editar" / "Agregar" → AJAX trae form, abre modal
   - Submit del modal → POST guardar_opcion → recarga pagina
   - Eliminar → confirm → POST eliminar_opcion → recarga
   - Drag/drop en el contenedor → POST mover_opcion (sin recargar) */

(function () {
    'use strict';

    var rootEl = document.querySelector('.dpchat-editor');
    if (!rootEl) return;

    var STATE = {
        departamentoId: parseInt(rootEl.getAttribute('data-departamento-id') || '0', 10),
        postUrl: rootEl.getAttribute('data-post-url'),
        csrf: rootEl.getAttribute('data-csrf'),
        metaStatus: 'idle',
    };

    var META_DEBOUNCE = 700;
    var SAVED_FLASH_MS = 1800;

    function $(sel, ctx) { return (ctx || document).querySelector(sel); }
    function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }

    function debounce(fn, ms) {
        var t = null;
        return function () {
            var args = arguments, ctx = this;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    function postAction(action, data) {
        var fd = new FormData();
        fd.append('csrfmiddlewaretoken', STATE.csrf);
        fd.append('action', action);
        Object.keys(data || {}).forEach(function (k) {
            var v = data[k];
            if (v === null || v === undefined) v = '';
            fd.append(k, v);
        });
        return fetch(STATE.postUrl, {
            method: 'POST', body: fd, credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (r) { return r.json(); });
    }

    function getJson(params) {
        var qs = Object.keys(params).map(function (k) {
            return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
        }).join('&');
        return fetch(STATE.postUrl + '?' + qs, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (r) { return r.json(); });
    }

    /* ────────────── Autosave cabecera ────────────── */
    function setMetaStatus(status) {
        STATE.metaStatus = status;
        var el = $('#dp-meta-status');
        if (!el) return;
        el.setAttribute('data-state', status);
        el.textContent = ({
            idle: 'Sin cambios',
            dirty: 'Editando…',
            saving: 'Guardando…',
            saved: '✓ Guardado',
            error: '⚠ Error al guardar',
        })[status] || status;
    }

    var saveMeta = debounce(function () {
        setMetaStatus('saving');
        postAction('guardar_meta', {
            pk: STATE.departamentoId,
            nombre: $('#dp-nombre').value,
            color: $('#dp-color').value,
            mensaje_saludo: $('#dp-saludo').value,
        }).then(function (resp) {
            if (!resp.ok) {
                setMetaStatus('error');
                console.warn('guardar_meta', resp.error);
                return;
            }
            if (resp.created) {
                STATE.departamentoId = resp.departamento_id;
                rootEl.setAttribute('data-departamento-id', resp.departamento_id);
                $('#dp-tree-card').style.display = '';
                $('#dp-needs-meta').style.display = 'none';
                try {
                    var u = new URL(window.location.href);
                    u.searchParams.set('action', 'change');
                    u.searchParams.set('id', resp.departamento_id);
                    u.searchParams.set('full', '1');
                    window.history.replaceState({}, '', u.toString());
                } catch (e) {}
            }
            setMetaStatus('saved');
            setTimeout(function () {
                if (STATE.metaStatus === 'saved') setMetaStatus('idle');
            }, SAVED_FLASH_MS);
        }).catch(function (err) {
            setMetaStatus('error');
            console.error(err);
        });
    }, META_DEBOUNCE);

    function wireMeta() {
        ['#dp-nombre', '#dp-color', '#dp-saludo'].forEach(function (sel) {
            var el = $(sel);
            if (!el) return;
            el.addEventListener('input', function () {
                setMetaStatus('dirty');
                saveMeta();
            });
        });
    }

    /* ────────────── Modal nodo ────────────── */
    var modalNodo = null;
    function getModal() {
        if (!modalNodo) modalNodo = new bootstrap.Modal($('#dpModalNodo'));
        return modalNodo;
    }

    function openNodeModal(opts) {
        // opts: { id?, parent_id? }. id=0 → crear nuevo
        var titulo = opts.id ? 'Editar nodo #' + opts.id : 'Nuevo nodo';
        if (!opts.id && opts.parent_id) titulo = 'Nueva sub-opción';
        $('#dpModalNodoTitulo').textContent = titulo;
        $('#dpModalNodoBody').innerHTML =
            '<div class="text-center text-muted py-4"><i class="fa fa-spinner fa-spin"></i> Cargando…</div>';
        getModal().show();
        getJson({
            action: 'editar_opcion',
            id: opts.id || 0,
            parent_id: opts.parent_id || 0,
            departamento_id: STATE.departamentoId,
            full: 1,
        }).then(function (resp) {
            if (!resp.result) {
                $('#dpModalNodoBody').innerHTML =
                    '<div class="alert alert-danger">' + (resp.message || 'Error') + '</div>';
                return;
            }
            $('#dpModalNodoBody').innerHTML = resp.data;
        }).catch(function (err) {
            $('#dpModalNodoBody').innerHTML =
                '<div class="alert alert-danger">Error de conexión: ' + err.message + '</div>';
        });
    }

    function wireModalSubmit() {
        var form = $('#dpFormNodo');
        if (!form) return;
        form.addEventListener('submit', function (ev) {
            ev.preventDefault();
            var btn = $('#dpBtnGuardarNodo');
            var origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Guardando…';

            // Validar config_json
            var cfgEl = form.querySelector('textarea[name="config_json"]');
            if (cfgEl && cfgEl.value.trim()) {
                try { JSON.parse(cfgEl.value); cfgEl.classList.remove('is-invalid'); }
                catch (e) {
                    cfgEl.classList.add('is-invalid');
                    btn.disabled = false;
                    btn.innerHTML = origHtml;
                    alert('Config JSON invalido: ' + e.message);
                    return;
                }
            }

            var fd = new FormData(form);
            fetch(STATE.postUrl, {
                method: 'POST', body: fd, credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            }).then(function (r) { return r.json(); }).then(function (resp) {
                btn.disabled = false;
                btn.innerHTML = origHtml;
                if (!resp.ok) {
                    alert('Error al guardar: ' + (resp.error || 'desconocido'));
                    return;
                }
                getModal().hide();
                window.location.reload();
            }).catch(function (err) {
                btn.disabled = false;
                btn.innerHTML = origHtml;
                alert('Error de conexión: ' + err.message);
            });
        });
    }

    /* ────────────── Acciones del árbol ────────────── */
    function wireTreeActions() {
        document.addEventListener('click', function (ev) {
            var btn = ev.target.closest('[data-act]');
            if (!btn) return;
            var act = btn.getAttribute('data-act');

            if (act === 'add-root') {
                if (STATE.departamentoId === 0) {
                    alert('Primero ponele nombre al departamento (cabecera arriba) para que se cree.');
                    return;
                }
                openNodeModal({ id: 0, parent_id: 0 });
                return;
            }
            if (act === 'add-child') {
                openNodeModal({ id: 0, parent_id: parseInt(btn.getAttribute('data-parent-id'), 10) });
                return;
            }
            if (act === 'edit') {
                openNodeModal({ id: parseInt(btn.getAttribute('data-id'), 10) });
                return;
            }
            if (act === 'delete') {
                var id = parseInt(btn.getAttribute('data-id'), 10);
                var nombre = btn.getAttribute('data-nombre') || '';
                if (!confirm('¿Eliminar "' + (nombre || 'este nodo') + '" y todos sus hijos?')) return;
                postAction('eliminar_opcion', { opcion_id: id }).then(function (resp) {
                    if (!resp.ok) {
                        alert('Error al eliminar: ' + (resp.error || 'desconocido'));
                        return;
                    }
                    window.location.reload();
                });
                return;
            }
            if (act === 'ver-diagrama') {
                if (STATE.departamentoId === 0) {
                    alert('Primero guardá el departamento (cabecera) para ver el diagrama.');
                    return;
                }
                var modalDiag = bootstrap.Modal.getOrCreateInstance($('#dpModalDiagrama'));
                modalDiag.show();
                return;
            }
            if (act === 'ver-meta-json') {
                if (STATE.departamentoId === 0) {
                    alert('Primero guardá el departamento (cabecera) para generar el payload.');
                    return;
                }
                var modalJson = bootstrap.Modal.getOrCreateInstance($('#dpModalMetaJson'));
                $('#dp-meta-json-pre').textContent = 'Cargando…';
                modalJson.show();
                getJson({
                    action: 'exportar_meta_payload',
                    id: STATE.departamentoId,
                }).then(function (resp) {
                    if (!resp.result) {
                        $('#dp-meta-json-pre').textContent = 'Error: ' + (resp.message || 'desconocido');
                        return;
                    }
                    $('#dp-meta-json-pre').textContent = JSON.stringify(resp.payload, null, 2);
                }).catch(function (err) {
                    $('#dp-meta-json-pre').textContent = 'Error de conexión: ' + err.message;
                });
                return;
            }
        });

        // Boton copiar JSON Meta
        var btnCopy = $('#dp-copy-json');
        if (btnCopy) {
            btnCopy.addEventListener('click', function () {
                var text = $('#dp-meta-json-pre').textContent || '';
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(function () {
                        btnCopy.innerHTML = '<i class="fa fa-check me-1"></i> Copiado';
                        setTimeout(function () {
                            btnCopy.innerHTML = '<i class="fa fa-copy me-1"></i> Copiar';
                        }, 1500);
                    });
                } else {
                    // fallback
                    var ta = document.createElement('textarea');
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    try { document.execCommand('copy'); } catch (e) {}
                    document.body.removeChild(ta);
                    btnCopy.innerHTML = '<i class="fa fa-check me-1"></i> Copiado';
                    setTimeout(function () {
                        btnCopy.innerHTML = '<i class="fa fa-copy me-1"></i> Copiar';
                    }, 1500);
                }
            });
        }
    }

    /* ────────────── Sortable (reordenar nodos del mismo padre) ────────────── */
    function wireSortable() {
        var container = $('#dp-tree');
        if (!container) return;
        if (typeof Sortable === 'undefined') return;
        if (container._sortable) return;
        container._sortable = new Sortable(container, {
            handle: '.dp-drag-handle',
            animation: 140,
            // Bloquea drops entre nodos de distinto padre — sólo reordenamos hermanos.
            // Para mover un nodo a otro padre, usar el modal "Editar" (TODO: campo padre).
            onMove: function (evt) {
                var dragged = evt.dragged;
                var related = evt.related;
                if (!related) return true;
                return dragged.getAttribute('data-padre') === related.getAttribute('data-padre');
            },
            onEnd: function () {
                // Recalcula orden por nodo (solo entre hermanos del mismo padre)
                // El render server-side mezcla profundidades; para reordenar seguro
                // solo aceptamos drops que mantengan el padre del nodo movido.
                var cards = $$('.dp-node-card', container);
                // Agrupar por padre
                var groups = {};
                cards.forEach(function (c) {
                    var p = c.getAttribute('data-padre') || 'root';
                    (groups[p] = groups[p] || []).push(c);
                });
                Object.keys(groups).forEach(function (k) {
                    groups[k].forEach(function (c, idx) {
                        var id = parseInt(c.getAttribute('data-id'), 10);
                        if (!id) return;
                        // Solo postear si el orden cambió respecto al inicial
                        var ordenActual = idx;
                        if (c._ordenInicial !== ordenActual) {
                            postAction('mover_opcion', {
                                opcion_id: id,
                                parent_id: c.getAttribute('data-padre') || 0,
                                orden: ordenActual,
                            });
                            c._ordenInicial = ordenActual;
                        }
                    });
                });
            },
        });
        // Guardar orden inicial
        $$('.dp-node-card', container).forEach(function (c, idx) {
            c._ordenInicial = idx;
        });
    }

    /* ────────────── beforeunload ────────────── */
    function setupBeforeUnload() {
        window.addEventListener('beforeunload', function (ev) {
            if (STATE.metaStatus === 'dirty' || STATE.metaStatus === 'saving') {
                ev.preventDefault();
                ev.returnValue = 'Tenés cambios sin guardar.';
                return ev.returnValue;
            }
        });
    }

    /* ────────────── Filtros (cliente) ────────────── */
    function aplicarFiltros() {
        var qEl = $('#dp-filter-q');
        var tipoEl = $('#dp-filter-tipo');
        if (!qEl || !tipoEl) return;
        var q = (qEl.value || '').toLowerCase().trim();
        var tipo = tipoEl.value || '';
        var cards = $$('.dp-node-card');
        var visibles = 0;
        cards.forEach(function (c) {
            var tipoNodo = c.getAttribute('data-tipo') || '';
            var nombre = (c.querySelector('.dp-node-title') || {}).textContent || '';
            var preview = (c.querySelector('.dp-node-preview') || {}).textContent || '';
            var matchTipo = !tipo || tipoNodo === tipo;
            var matchTexto = !q ||
                nombre.toLowerCase().indexOf(q) >= 0 ||
                preview.toLowerCase().indexOf(q) >= 0;
            var ok = matchTipo && matchTexto;
            c.classList.toggle('dp-hidden', !ok);
            if (ok) visibles++;
        });
        var resumen = $('#dp-filter-resumen');
        if (resumen) {
            resumen.textContent = (visibles === cards.length)
                ? cards.length + ' nodos'
                : visibles + ' de ' + cards.length + ' nodos';
        }
    }

    function wireFiltros() {
        var q = $('#dp-filter-q');
        var tipo = $('#dp-filter-tipo');
        var clear = $('#dp-filter-clear');
        if (q) q.addEventListener('input', aplicarFiltros);
        if (tipo) tipo.addEventListener('change', aplicarFiltros);
        if (clear) clear.addEventListener('click', function () {
            if (q) q.value = '';
            if (tipo) tipo.value = '';
            aplicarFiltros();
        });
        aplicarFiltros();
    }

    /* ────────────── Init ────────────── */
    function init() {
        wireMeta();
        wireModalSubmit();
        wireTreeActions();
        wireSortable();
        wireFiltros();
        setupBeforeUnload();
        console.log('[dpchat_editor] init OK · dep_id=' + STATE.departamentoId);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
