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

    var modalFicha = null;
    function getFichaModal() {
        if (!modalFicha) modalFicha = new bootstrap.Modal($('#dpModalFichaNodo'));
        return modalFicha;
    }

    function openFichaModal(opcionId) {
        if (!opcionId) return;
        $('#dpModalFichaNodoBody').innerHTML =
            '<div class="text-center text-muted py-4"><i class="fa fa-spinner fa-spin"></i> Cargando…</div>';
        getFichaModal().show();
        getJson({
            action: 'ficha_opcion',
            id: opcionId,
            full: 1,
        }).then(function (resp) {
            if (!resp.result) {
                $('#dpModalFichaNodoBody').innerHTML =
                    '<div class="alert alert-danger">' + (resp.message || 'Error') + '</div>';
                return;
            }
            $('#dpModalFichaNodoBody').innerHTML = resp.data;
        }).catch(function (err) {
            $('#dpModalFichaNodoBody').innerHTML =
                '<div class="alert alert-danger">Error de conexión: ' + err.message + '</div>';
        });
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
            wireTipoNodoToggle();
            wireProbarHttp();
        }).catch(function (err) {
            $('#dpModalNodoBody').innerHTML =
                '<div class="alert alert-danger">Error de conexión: ' + err.message + '</div>';
        });
    }

    function wireProbarHttp() {
        var btn = document.getElementById('dpBtnProbarHttp');
        if (!btn) return;
        btn.addEventListener('click', function () {
            var form = document.getElementById('dpFormNodo') || btn.closest('form');
            if (!form) return;
            var resultado = document.getElementById('dpProbarResultado');
            if (resultado) {
                resultado.style.display = 'block';
                resultado.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Ejecutando…';
            }
            var orig = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Probando…';

            var fd = new FormData();
            fd.append('action', 'probar_http');
            fd.append('csrfmiddlewaretoken',
                form.querySelector('input[name="csrfmiddlewaretoken"]').value);
            fd.append('endpoint_id', (form.querySelector('[name="http_endpoint_id"]') || {}).value || '');
            fd.append('metodo',     (form.querySelector('[name="http_metodo"]')      || {}).value || 'GET');
            fd.append('path',       (form.querySelector('[name="http_path"]')        || {}).value || '');
            fd.append('query_json', (form.querySelector('[name="http_query_json"]')  || {}).value || '');
            fd.append('body_json',  (form.querySelector('[name="http_body_json"]')   || {}).value || '');
            fd.append('headers_json', (form.querySelector('[name="http_headers_json"]') || {}).value || '');
            fd.append('variables_test_json', (document.getElementById('dpVarsTest') || {}).value || '');

            fetch(STATE.postUrl, {
                method: 'POST', body: fd, credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            }).then(function (r) { return r.json(); }).then(function (resp) {
                btn.disabled = false;
                btn.innerHTML = orig;
                if (!resultado) return;
                if (!resp.ok) {
                    resultado.innerHTML = '<div class="text-danger"><i class="fa fa-times-circle me-1"></i>'
                        + escHtml(resp.error || 'Error desconocido') + '</div>';
                    return;
                }
                var iconStatus = (resp.etiqueta === 'ok') ? '✅' : '⚠️';
                var html = ''
                    + '<div><strong>' + iconStatus + ' ' + escHtml(resp.metodo) + '</strong> '
                    + '<code>' + escHtml(resp.url) + '</code></div>'
                    + '<div class="mt-1">'
                    + '<span class="badge bg-' + (resp.etiqueta === 'ok' ? 'success' : 'danger') + '">'
                    + 'HTTP ' + (resp.status || 'sin respuesta') + '</span> '
                    + '<span class="badge bg-secondary">' + (resp.duracion_ms || 0) + ' ms</span> '
                    + (resp.error ? '<span class="text-danger">' + escHtml(resp.error) + '</span>' : '')
                    + '</div>';
                if (resp.body !== null && resp.body !== undefined) {
                    var bodyStr;
                    try { bodyStr = JSON.stringify(resp.body, null, 2); }
                    catch (e) { bodyStr = String(resp.body); }
                    html += '<details class="mt-2"><summary>Body de la respuesta</summary>'
                         + '<pre class="mb-0 mt-1" style="white-space:pre-wrap;max-height:240px;overflow:auto;">'
                         + escHtml(bodyStr) + '</pre></details>';
                }
                resultado.innerHTML = html;
            }).catch(function (err) {
                btn.disabled = false;
                btn.innerHTML = orig;
                if (resultado) {
                    resultado.innerHTML = '<div class="text-danger">Error de red: '
                        + escHtml(err.message || err) + '</div>';
                }
            });
        });
    }

    function escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // Arma la "ficha resumida" desde el snapshot del flujo. Pinta cabecera,
    // estadísticas, endpoints, y cada nodo con sus campos relevantes.
    function renderFicha(data) {
        var d = data.departamento || {};
        var s = data.estadisticas || {};
        var html = '';
        html += '<div class="dp-ficha-section">'
             +    '<h6 class="dp-ficha-h"><i class="fa fa-folder-tree me-1"></i>'
             +        ' Departamento</h6>'
             +    '<div class="row g-2">'
             +      ficha_kv('Nombre', d.nombre)
             +      ficha_kv('ID', d.id)
             +      ficha_kv('Color', '<span class="dp-ficha-color" style="background:'
                                    + escHtml(d.color || '#888') + '"></span> ' + escHtml(d.color || '—'))
             +      ficha_kv('Es default', d.es_default ? '✅ Sí' : '—')
             +      ficha_kv('Activo (tradicional)', d.activo_tradicional ? '✅ Sí' : '—')
             +    '</div>'
             +    '<div class="dp-ficha-saludo mt-2">'
             +      '<strong>Saludo:</strong> ' + escHtml(d.mensaje_saludo || '—')
             +    '</div>';
        if ((d.palabras_clave || []).length) {
            html += '<div class="mt-1"><strong>Keywords:</strong> '
                  + d.palabras_clave.map(function (k) {
                        return '<code class="dp-ficha-tag">' + escHtml(k) + '</code>';
                    }).join(' ') + '</div>';
        }
        html += '</div>';

        // Estadísticas
        html += '<div class="dp-ficha-section">'
             +   '<h6 class="dp-ficha-h"><i class="fa fa-chart-pie me-1"></i> Estadísticas</h6>'
             +   '<div class="row g-2">'
             +     ficha_kv('Nodos', s.total_nodos)
             +     ficha_kv('Conexiones', s.total_conexiones)
             +     ficha_kv('Endpoints usados', s.endpoints_usados)
             +     ficha_kv('Credenciales', s.credenciales_usadas)
             +   '</div>';
        if (s.nodo_inicio) {
            html += '<div class="mt-1"><strong>Nodo inicial:</strong> '
                  + '<span class="badge bg-success">'
                  + escHtml(s.nodo_inicio.tipo) + '</span> '
                  + escHtml(s.nodo_inicio.nombre) + ' #' + s.nodo_inicio.id + '</div>';
        }
        if (s.nodos_por_tipo) {
            html += '<div class="mt-1"><strong>Por tipo:</strong> '
                  + Object.keys(s.nodos_por_tipo).map(function (k) {
                        return '<code class="dp-ficha-tag">' + escHtml(k)
                             + ': ' + s.nodos_por_tipo[k] + '</code>';
                    }).join(' ') + '</div>';
        }
        if ((s.nodos_huerfanos || []).length) {
            html += '<div class="mt-1 text-warning"><strong>⚠️ Huérfanos (sin conexión entrante):</strong> '
                  + s.nodos_huerfanos.map(function (n) {
                        return '<code class="dp-ficha-tag">#' + n.id
                             + ' ' + escHtml(n.nombre) + '</code>';
                    }).join(' ') + '</div>';
        }
        html += '</div>';

        // Endpoints
        if ((data.endpoints || []).length) {
            html += '<div class="dp-ficha-section">'
                 +   '<h6 class="dp-ficha-h"><i class="fa fa-globe me-1"></i> Endpoints</h6>';
            data.endpoints.forEach(function (ep) {
                var cred = (data.credenciales || []).find(function (c) { return c.id === ep.credencial_id; });
                html += '<div class="dp-ficha-endpoint">'
                     +   '<strong>' + escHtml(ep.nombre) + '</strong> '
                     +   '<small class="text-muted">#' + ep.id + ' · timeout '
                     +   ep.timeout_seg + 's</small><br>'
                     +   '<code>' + escHtml(ep.base_url) + '</code><br>'
                     +   '<small>Auth: '
                     +   (cred ? escHtml(cred.nombre) + ' (' + escHtml(cred.tipo_display) + ')'
                              : '<em>— sin credencial —</em>')
                     +   '</small>'
                     + '</div>';
            });
            html += '</div>';
        }

        // Nodos (lista compacta)
        html += '<div class="dp-ficha-section">'
             +   '<h6 class="dp-ficha-h"><i class="fa fa-list-ol me-1"></i> Nodos ('
             +   (data.nodos || []).length + ')</h6>'
             +   '<div class="dp-ficha-nodos">';
        (data.nodos || []).forEach(function (n) {
            html += renderFichaNodo(n, data);
        });
        html += '</div></div>';
        return html;
    }

    function ficha_kv(k, v) {
        return '<div class="col-6 col-md-4 dp-ficha-kv">'
             +   '<div class="text-muted small">' + escHtml(k) + '</div>'
             +   '<div class="dp-ficha-v">' + (v == null ? '—' : v) + '</div>'
             + '</div>';
    }

    function renderFichaNodo(n, data) {
        var cfg = n.config || {};
        var html = '<div class="dp-ficha-nodo dp-ficha-tipo-' + escHtml(n.tipo_nodo) + '">'
                 +   '<div class="dp-ficha-nodo-head">'
                 +     '<span class="badge dp-ficha-badge-' + escHtml(n.tipo_nodo) + '">'
                 +       escHtml(n.tipo_nodo) + '</span> '
                 +     (n.es_inicio ? '<i class="fa fa-play text-success me-1" title="Inicio"></i>' : '')
                 +     '<strong>' + escHtml(n.nombre || '(sin nombre)') + '</strong> '
                 +     '<small class="text-muted">#' + n.id + ' · orden ' + n.orden + '</small>';
        if (n.boton_id) {
            html += ' <code class="dp-ficha-tag">' + escHtml(n.boton_id) + '</code>';
        }
        html += '</div>';

        if (n.tipo_nodo === 'http') {
            var ep = (data.endpoints || []).find(function (e) { return e.id === n.endpoint_id; });
            html += '<div class="dp-ficha-nodo-body">'
                  +   '<div><span class="badge bg-primary">' + escHtml(cfg.metodo || 'GET')
                  +     '</span> <code>' + escHtml((ep ? ep.base_url : '?')
                  +     (cfg.path || '')) + '</code></div>';
            if (cfg.query) {
                html += '<div><strong>query:</strong> <code>' + escHtml(JSON.stringify(cfg.query)) + '</code></div>';
            }
            if (cfg.body) {
                html += '<div><strong>body:</strong> <code>' + escHtml(JSON.stringify(cfg.body)) + '</code></div>';
            }
            if ((cfg.extraer || []).length) {
                html += '<div><strong>extrae:</strong> '
                     + cfg.extraer.map(function (e) {
                            return '<code class="dp-ficha-tag">$' + escHtml(e.variable)
                                 + ' ← ' + escHtml(e.jsonpath) + '</code>';
                        }).join(' ') + '</div>';
            }
            if (cfg.plantilla_respuesta) {
                html += '<div class="dp-ficha-plantilla">'
                     + '<strong>plantilla:</strong> ' + escHtml(cfg.plantilla_respuesta) + '</div>';
            }
            html += '</div>';
        } else if (n.tipo_nodo === 'pregunta') {
            html += '<div class="dp-ficha-nodo-body">'
                 +   '<div>' + escHtml(cfg.pregunta || n.respuesta || '—') + '</div>'
                 +   '<div><strong>captura:</strong> <code>$' + escHtml(n.variable_destino) + '</code>'
                 +   ' · <strong>valida:</strong> ' + escHtml(n.validacion_tipo) + '</div>'
                 + '</div>';
        } else if (n.tipo_nodo === 'menu') {
            html += '<div class="dp-ficha-nodo-body">';
            if (cfg.mensaje) html += '<div>' + escHtml(cfg.mensaje) + '</div>';
            html += '<div><strong>opciones (' + ((cfg.opciones || []).length) + '):</strong></div>';
            (cfg.opciones || []).forEach(function (opt) {
                html += '<div class="ms-2">• <strong>' + escHtml(opt.etiqueta || opt.valor)
                      + '</strong> → <code>' + escHtml(opt.salida || '') + '</code></div>';
            });
            html += '</div>';
        } else if (n.tipo_nodo === 'condicional') {
            html += '<div class="dp-ficha-nodo-body">'
                 +   '<div><strong>' + escHtml((cfg.operador || 'and').toUpperCase())
                 +   '</strong></div>';
            (cfg.condiciones || []).forEach(function (c) {
                html += '<div class="ms-2">• <code>' + escHtml(c.izq) + '</code> '
                      + '<strong>' + escHtml(c.op) + '</strong> '
                      + '<code>' + escHtml(c.der || '""') + '</code></div>';
            });
            html += '</div>';
        } else if (n.tipo_nodo === 'set_variable') {
            html += '<div class="dp-ficha-nodo-body">';
            (cfg.asignaciones || []).forEach(function (a) {
                html += '<div class="ms-2">• <code>$' + escHtml(a.variable)
                      + '</code> ← <code>' + escHtml(a.expresion || '""') + '</code></div>';
            });
            html += '</div>';
        } else if (cfg.mensaje || n.respuesta) {
            html += '<div class="dp-ficha-nodo-body">'
                 +   '<div>' + escHtml(cfg.mensaje || n.respuesta) + '</div>'
                 + '</div>';
        }

        // Conexiones salientes
        var salidas = (data.conexiones || []).filter(function (c) { return c.origen_id === n.id; });
        if (salidas.length) {
            html += '<div class="dp-ficha-nodo-body dp-ficha-salidas">'
                 +   '<strong>→ salidas:</strong> '
                 + salidas.map(function (c) {
                        return '<code class="dp-ficha-tag">'
                             + (c.etiqueta ? escHtml(c.etiqueta) + '→' : '')
                             + '#' + c.destino_id + ' ' + escHtml(c.destino_nombre)
                             + '</code>';
                    }).join(' ') + '</div>';
        }
        html += '</div>';
        return html;
    }

    function wireTipoNodoToggle() {
        var tipoSel = document.getElementById('dpFormTipo');
        if (!tipoSel) return;
        var bloques = document.querySelectorAll('.dp-tipo-block');
        function aplicar() {
            var t = tipoSel.value;
            bloques.forEach(function (b) {
                var when = b.getAttribute('data-show-when');
                b.style.display = (when === t) ? '' : 'none';
            });
        }
        tipoSel.addEventListener('change', aplicar);
        aplicar();
    }

    function wireSalidasEditor() {
        // Editor de "Salidas / Siguientes" del modal del nodo. Delegamos
        // todos los clicks porque el modal-body se reemplaza por AJAX cada
        // vez que abrís un nodo (el editor se re-renderiza).
        document.addEventListener('click', function (ev) {
            // Agregar nueva fila clonando el <template>.
            if (ev.target.closest('#dp-salida-add')) {
                ev.preventDefault();
                var tpl = document.getElementById('dp-salida-row-tpl');
                var body = document.getElementById('dp-salidas-body');
                if (tpl && body) {
                    body.appendChild(tpl.content.cloneNode(true));
                }
                return;
            }
            // Borrar fila.
            var delBtn = ev.target.closest('[data-act="dp-salida-del"]');
            if (delBtn) {
                ev.preventDefault();
                var tr = delBtn.closest('tr');
                if (tr) tr.remove();
                return;
            }
            // Agregar fila al editor inline de opciones de menú.
            if (ev.target.closest('[data-act="dp-menu-opcion-add"]')) {
                ev.preventDefault();
                var tbodyOpc = document.getElementById('menuOpcionesBody');
                if (!tbodyOpc) return;
                var trOpc = document.createElement('tr');
                trOpc.innerHTML =
                    '<td><input type="text" class="form-control form-control-sm" name="menu_opt_etiqueta[]" placeholder="🙋 Solo para mí"></td>' +
                    '<td><input type="text" class="form-control form-control-sm" name="menu_opt_valor[]" placeholder="solo"></td>' +
                    '<td><input type="text" class="form-control form-control-sm" name="menu_opt_salida[]" placeholder="solo"></td>' +
                    '<td><button type="button" class="btn btn-sm btn-outline-danger" data-act="dp-menu-opcion-del" title="Eliminar"><i class="fa fa-times"></i></button></td>';
                tbodyOpc.appendChild(trOpc);
                return;
            }
            // Borrar fila del editor inline de opciones de menú.
            var delOpc = ev.target.closest('[data-act="dp-menu-opcion-del"]');
            if (delOpc) {
                ev.preventDefault();
                var trDel = delOpc.closest('tr');
                if (trDel) trDel.remove();
                return;
            }
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

            // Serializar editor de salidas (ConexionNodoChatbot) si está
            // presente — antes del FormData, así viaja como `salidas_json`.
            var salidasBody = form.querySelector('#dp-salidas-body');
            var salidasInput = form.querySelector('#dp-salidas-json');
            if (salidasBody && salidasInput) {
                var rows = salidasBody.querySelectorAll('tr');
                var lista = [];
                rows.forEach(function (tr) {
                    var dst = parseInt(tr.querySelector('.dp-salida-dst').value || '0', 10);
                    if (!dst) return;
                    var etq = (tr.querySelector('.dp-salida-etq').value || '').trim();
                    var descEl = tr.querySelector('.dp-salida-desc');
                    var desc = descEl ? (descEl.value || '').trim() : '';
                    var cid = tr.getAttribute('data-conex-id') || '';
                    lista.push({
                        id: cid ? parseInt(cid, 10) : null,
                        etiqueta: etq,
                        descripcion: desc,
                        destino_id: dst,
                    });
                });
                salidasInput.value = JSON.stringify(lista);
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
            if (act === 'view') {
                openFichaModal(parseInt(btn.getAttribute('data-id'), 10));
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
            if (act === 'ver-json' || act === 'ver-ficha') {
                if (STATE.departamentoId === 0) {
                    alert('Primero guardá el departamento (cabecera) para generar la ficha.');
                    return;
                }
                var esJson = (act === 'ver-json');
                var modalEl = esJson ? $('#dpModalJson') : $('#dpModalFicha');
                var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                var jsonPre  = esJson ? $('#dp-meta-json-pre') : null;
                var fichaBox = esJson ? null : $('#dp-ficha-content');
                if (jsonPre)  jsonPre.textContent = 'Cargando…';
                if (fichaBox) fichaBox.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Cargando…';
                modal.show();

                console.log('[dpchat] solicitando exportar_flujo_json id=' + STATE.departamentoId);
                getJson({ action: 'exportar_flujo_json', id: STATE.departamentoId })
                    .then(function (resp) {
                        console.log('[dpchat] resp exportar_flujo_json:', resp);
                        if (!resp || typeof resp !== 'object') {
                            var raw = JSON.stringify(resp);
                            if (jsonPre)  jsonPre.textContent = 'Respuesta inesperada: ' + raw;
                            if (fichaBox) fichaBox.innerHTML =
                                '<div class="alert alert-warning">Respuesta inesperada del servidor.</div>';
                            return;
                        }
                        if (!resp.result) {
                            var msg = resp.message || 'Sin detalle';
                            if (jsonPre)  jsonPre.textContent = 'Error: ' + msg;
                            if (fichaBox) fichaBox.innerHTML =
                                '<div class="alert alert-danger"><strong>No se pudo cargar:</strong> '
                                + escHtml(msg) + '</div>';
                            return;
                        }
                        if (jsonPre) {
                            try { jsonPre.textContent = JSON.stringify(resp.data, null, 2); }
                            catch (e) { jsonPre.textContent = 'Error formateando JSON: ' + e.message; }
                        }
                        if (fichaBox) {
                            try {
                                fichaBox.innerHTML = renderFicha(resp.data);
                            } catch (e) {
                                console.error('renderFicha falló:', e);
                                fichaBox.innerHTML =
                                    '<div class="alert alert-warning small">'
                                    + '<strong>Ficha no se pudo armar:</strong> ' + escHtml(e.message)
                                    + '. Mirá el botón <em>JSON</em> para ver los datos crudos.'
                                    + '</div>';
                            }
                        }
                    })
                    .catch(function (err) {
                        var msg = 'Error de red: ' + (err.message || err);
                        if (jsonPre)  jsonPre.textContent = msg;
                        if (fichaBox) fichaBox.innerHTML =
                            '<div class="alert alert-danger">' + escHtml(msg) + '</div>';
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

    /* ────────────── Sortable (reordenar + cambiar padre por drop) ────────────── */
    function wireSortable() {
        var container = $('#dp-tree');
        if (!container) return;
        if (typeof Sortable === 'undefined') return;
        if (container._sortable) return;

        function snapshotSiblings(parent) {
            return $$('.dp-node-card[data-padre="' + (parent || '') + '"]', container)
                .map(function (c) {
                    return {
                        id: parseInt(c.getAttribute('data-id'), 10) || 0,
                        nombre: ((c.querySelector('.dp-node-title') || {}).textContent || '').trim(),
                    };
                });
        }

        function buildDiffHtml(antes, ahora, movedId) {
            function row(s) {
                var hi = (s.id === movedId) ? 'background:#fef9c3;font-weight:600;' : '';
                return '<li style="' + hi + '">' +
                       '<span>' + (s.nombre || '(sin nombre)') + '</span> ' +
                       '<small style="color:#94a3b8;">#' + s.id + '</small></li>';
            }
            return '' +
                '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;text-align:left;">' +
                  '<div>' +
                    '<div style="color:#64748b;font-size:.85rem;margin-bottom:.25rem;">' +
                      '<i class="fa fa-clock-rotate-left"></i> Antes' +
                    '</div>' +
                    '<ol style="padding-left:1.2rem;margin:0;font-size:.85rem;">' +
                      antes.map(row).join('') +
                    '</ol>' +
                  '</div>' +
                  '<div>' +
                    '<div style="color:#16a34a;font-size:.85rem;margin-bottom:.25rem;">' +
                      '<i class="fa fa-check"></i> Ahora' +
                    '</div>' +
                    '<ol style="padding-left:1.2rem;margin:0;font-size:.85rem;">' +
                      ahora.map(row).join('') +
                    '</ol>' +
                  '</div>' +
                '</div>';
        }

        function revertirDom(moved, oldNextSibling) {
            // Vuelve el item a su posición original. oldNextSibling puede ser
            // null si el item estaba al final; en ese caso lo apendeamos.
            if (oldNextSibling && oldNextSibling.parentNode === container) {
                container.insertBefore(moved, oldNextSibling);
            } else {
                container.appendChild(moved);
            }
        }

        container._sortable = new Sortable(container, {
            handle: '.dp-drag-handle',
            animation: 140,
            // Permitimos drops en cualquier posición; el padre se infiere por
            // la card anterior tras el drop (ver onEnd). El backend valida ciclos.
            onStart: function (evt) {
                // Snapshot DOM ANTES del drop para poder revertir si el operador cancela.
                var moved = evt.item;
                moved._dragSnap = {
                    oldParent: moved.getAttribute('data-padre') || '',
                    oldNextSibling: moved.nextElementSibling,
                    siblingsAntes: snapshotSiblings(moved.getAttribute('data-padre') || ''),
                };
            },
            onEnd: function (evt) {
                var moved = evt.item;
                var movedId = parseInt(moved.getAttribute('data-id'), 10);
                if (!movedId) return;

                var snap = moved._dragSnap || { oldParent: '', oldNextSibling: null, siblingsAntes: [] };

                // Nuevo padre = padre de la card anterior (ya que tras el drop,
                // el nodo movido se inserta como sibling del que lo precede).
                // Si no hay anterior, el nodo queda en raíz.
                var prev = moved.previousElementSibling;
                while (prev && !prev.classList.contains('dp-node-card')) {
                    prev = prev.previousElementSibling;
                }
                var newParent = prev ? (prev.getAttribute('data-padre') || '') : '';
                var oldParent = snap.oldParent;
                // Provisionalmente actualizamos data-padre para que snapshot
                // post-drop refleje el nuevo grupo. Si el operador cancela,
                // lo revertimos junto con el DOM.
                moved.setAttribute('data-padre', newParent);

                var hermanos = $$('.dp-node-card[data-padre="' + (newParent || '') + '"]', container);
                var newOrden = hermanos.indexOf(moved);
                var siblingsAhora = snapshotSiblings(newParent);

                var movioPadre = oldParent !== newParent;
                var movioOrden = (newOrden !== hermanos.length ? true : false) || (
                    JSON.stringify(snap.siblingsAntes.map(function (s) { return s.id; })) !==
                    JSON.stringify(siblingsAhora.map(function (s) { return s.id; }))
                );

                if (!movioPadre && JSON.stringify(snap.siblingsAntes) === JSON.stringify(siblingsAhora)) {
                    // No hubo cambio efectivo (drop en la misma posición).
                    return;
                }

                var titulo = movioPadre
                    ? '¿Confirmar cambio de padre?'
                    : '¿Confirmar nuevo orden?';
                var subtitulo = movioPadre
                    ? 'El nodo cambiará de padre. Verificá la trazabilidad.'
                    : 'Reordenamiento dentro del mismo grupo de hermanos.';

                if (typeof Swal === 'undefined') {
                    // Fallback sin SweetAlert: confirm nativo, sin trazabilidad rica.
                    if (!confirm(titulo + '\n' + subtitulo)) {
                        moved.setAttribute('data-padre', oldParent);
                        revertirDom(moved, snap.oldNextSibling);
                        return;
                    }
                    enviarMover(moved, movedId, newParent, newOrden, oldParent, hermanos, '');
                    return;
                }

                Swal.fire({
                    title: titulo,
                    html: '<div style="color:#475569;margin-bottom:.75rem;font-size:.9rem;">' + subtitulo + '</div>' +
                          buildDiffHtml(snap.siblingsAntes, siblingsAhora, movedId) +
                          '<div style="margin-top:1rem;text-align:left;">' +
                          '<label style="font-size:.85rem;color:#64748b;">Motivo (opcional)</label>' +
                          '<input id="dp-mover-motivo" class="swal2-input" placeholder="Ej: agrupar por catálogo"' +
                          ' style="margin:.25rem 0 0;width:100%;font-size:.9rem;">' +
                          '</div>',
                    icon: movioPadre ? 'warning' : 'question',
                    showCancelButton: true,
                    confirmButtonText: '<i class="fa fa-check me-1"></i> Confirmar',
                    cancelButtonText: 'Cancelar',
                    confirmButtonColor: '#16a34a',
                    cancelButtonColor: '#64748b',
                    width: 720,
                    focusConfirm: false,
                    preConfirm: function () {
                        var inp = document.getElementById('dp-mover-motivo');
                        return (inp && inp.value || '').trim();
                    },
                }).then(function (res) {
                    if (!res.isConfirmed) {
                        moved.setAttribute('data-padre', oldParent);
                        revertirDom(moved, snap.oldNextSibling);
                        return;
                    }
                    enviarMover(moved, movedId, newParent, newOrden, oldParent, hermanos, res.value || '');
                });
            },
        });

        function enviarMover(moved, movedId, newParent, newOrden, oldParent, hermanos, motivo) {
            postAction('mover_opcion', {
                opcion_id: movedId,
                parent_id: newParent || 0,
                orden: newOrden,
                motivo: motivo || '',
            }).then(function (resp) {
                if (!resp || !resp.ok) {
                    moved.setAttribute('data-padre', oldParent);
                    if (window.mensajeWarning) {
                        mensajeWarning((resp && resp.error) || 'No se pudo mover el nodo.');
                    } else if (typeof Swal !== 'undefined') {
                        Swal.fire('Error', (resp && resp.error) || 'No se pudo mover el nodo.', 'error');
                    } else {
                        alert((resp && resp.error) || 'No se pudo mover el nodo.');
                    }
                    location.reload();
                    return;
                }
                if (oldParent !== newParent) {
                    location.reload();
                } else {
                    hermanos.forEach(function (c, idx) {
                        var hid = parseInt(c.getAttribute('data-id'), 10);
                        if (!hid || hid === movedId) return;
                        postAction('mover_opcion', {
                            opcion_id: hid, parent_id: newParent || 0, orden: idx,
                        });
                    });
                }
            });
        }

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
        var ftEl = $('#dp-filter-fulltext');
        var tipoEl = $('#dp-filter-tipo');
        if (!qEl || !tipoEl) return;
        var q = (qEl.value || '').toLowerCase().trim();
        var qFull = (ftEl && ftEl.value || '').toLowerCase().trim();
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
            // Full-text: coincidencia en CUALQUIER texto renderizado de la card
            // (URL, body, headers, predecesores, salidas, tags, lo que sea).
            // Cacheamos el textContent en un atributo para no leer DOM en cada keystroke.
            var matchFull = true;
            if (qFull) {
                var hay = c._fullTextLower;
                if (hay === undefined) {
                    hay = (c.textContent || '').toLowerCase();
                    c._fullTextLower = hay;
                }
                matchFull = hay.indexOf(qFull) >= 0;
            }
            var ok = matchTipo && matchTexto && matchFull;
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

    function refrescarLegendCounts() {
        // Cuenta nodos por tipo (todos, no solo visibles) y actualiza los chips
        // del semáforo. Resalta el chip activo según el valor del select.
        var counts = {};
        $$('.dp-node-card').forEach(function (c) {
            var t = c.getAttribute('data-tipo') || '';
            counts[t] = (counts[t] || 0) + 1;
        });
        var tipoEl = $('#dp-filter-tipo');
        var tipoActivo = (tipoEl && tipoEl.value) || '';
        $$('.dp-legend-chip').forEach(function (chip) {
            var t = chip.getAttribute('data-tipo') || '';
            var n = counts[t] || 0;
            var label = chip.querySelector('.dp-legend-count');
            if (label) label.textContent = n;
            chip.setAttribute('data-count', String(n));
            chip.classList.toggle('dp-legend-active', tipoActivo === t);
        });
    }

    function wireFiltros() {
        var q = $('#dp-filter-q');
        var ft = $('#dp-filter-fulltext');
        var tipo = $('#dp-filter-tipo');
        var clear = $('#dp-filter-clear');
        if (q) q.addEventListener('input', aplicarFiltros);
        if (ft) ft.addEventListener('input', aplicarFiltros);
        if (tipo) tipo.addEventListener('change', function () {
            aplicarFiltros();
            refrescarLegendCounts();
        });
        if (clear) clear.addEventListener('click', function () {
            if (q) q.value = '';
            if (ft) ft.value = '';
            if (tipo) tipo.value = '';
            aplicarFiltros();
            refrescarLegendCounts();
        });
        // Click en chip del semáforo → setea el filtro de tipo (toggle).
        $$('.dp-legend-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                var t = chip.getAttribute('data-tipo') || '';
                if (!tipo) return;
                tipo.value = (tipo.value === t) ? '' : t;
                aplicarFiltros();
                refrescarLegendCounts();
            });
        });
        aplicarFiltros();
        refrescarLegendCounts();
    }

    /* ────────────── Catálogo de funciones registradas ────────────── */
    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function wireBotonFunciones() {
        var btn = $('#dp-btn-funciones');
        var modalEl = document.getElementById('dpModalFunciones');
        var content = $('#dp-funciones-content');
        if (!btn || !modalEl || !content) return;
        btn.addEventListener('click', function () {
            var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
            content.innerHTML = '<div class="text-center text-muted py-4"><i class="fa fa-spinner fa-spin"></i> Cargando…</div>';
            getJson({ action: 'funciones_disponibles', id: STATE.departamentoId }).then(function (resp) {
                if (!resp || !resp.result) {
                    content.innerHTML = '<div class="alert alert-danger">' +
                        ((resp && resp.message) || 'Error al cargar funciones.') + '</div>';
                    return;
                }
                var lista = resp.funciones || [];
                if (!lista.length) {
                    content.innerHTML = '<div class="alert alert-light border text-center">' +
                        'Sin funciones registradas. Crealas con ' +
                        '<code>@registrar_funcion(...)</code> en ' +
                        '<code>crm/funciones_chatbot.py</code>.</div>';
                    return;
                }
                content.innerHTML = lista.map(renderFuncionItem).join('');
                // Botones "copiar código"
                $$('.dp-fn-copy', content).forEach(function (b) {
                    b.addEventListener('click', function () {
                        var txt = b.getAttribute('data-codigo') || '';
                        if (navigator.clipboard) navigator.clipboard.writeText(txt);
                        b.innerHTML = '<i class="fa fa-check"></i> Copiado';
                        setTimeout(function () {
                            b.innerHTML = '<i class="fa fa-copy"></i> Copiar código';
                        }, 1200);
                    });
                });
                $$('.dp-fn-copy-body', content).forEach(function (b) {
                    b.addEventListener('click', function () {
                        var txt = b.getAttribute('data-body') || '';
                        if (navigator.clipboard) navigator.clipboard.writeText(txt);
                        b.innerHTML = '<i class="fa fa-check"></i> Copiado';
                        setTimeout(function () {
                            b.innerHTML = '<i class="fa fa-copy"></i> Copiar body ejemplo';
                        }, 1200);
                    });
                });
            });
        });
    }

    function renderFuncionItem(fn) {
        var params = '';
        var entradas = Object.entries(fn.parametros || {});
        if (entradas.length) {
            params = '<div class="mt-2"><strong class="small">Parámetros esperados:</strong>' +
                '<ul class="small mb-0 mt-1" style="font-size:.8rem;">' +
                entradas.map(function (e) {
                    return '<li><code>' + escapeHtml(e[0]) + '</code> — ' + escapeHtml(e[1]) + '</li>';
                }).join('') + '</ul></div>';
        }
        var ejemplo = '';
        if (fn.ejemplo_body && Object.keys(fn.ejemplo_body).length) {
            var bodyStr = JSON.stringify(fn.ejemplo_body, null, 2);
            ejemplo = '<div class="mt-2"><strong class="small">Ejemplo body:</strong>' +
                '<pre class="mb-1 mt-1" style="background:#1f2937;color:#e5e7eb;padding:.5rem;border-radius:5px;font-size:.72rem;max-height:200px;overflow:auto;">' +
                escapeHtml(bodyStr) + '</pre>' +
                '<button type="button" class="btn btn-xs btn-outline-secondary dp-fn-copy-body" data-body=\'' +
                bodyStr.replace(/'/g, '&#39;') + '\'>' +
                '<i class="fa fa-copy"></i> Copiar body ejemplo</button></div>';
        }
        var endpointBadge = fn.requiere_endpoint
            ? '<span class="badge bg-warning text-dark ms-1" title="Esta función requiere un EndpointApiChatbot asociado">' +
              '<i class="fa fa-link me-1"></i>Endpoint requerido</span>'
            : '<span class="badge bg-light text-muted border ms-1">Endpoint opcional</span>';

        return '<div class="dp-fn-item p-3 mb-3" style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;">' +
            '<div class="d-flex align-items-start gap-2 mb-2">' +
            '<span class="dp-tipo-pill tipo-funcion">FN</span>' +
            '<div class="flex-grow-1">' +
                '<strong>' + escapeHtml(fn.codigo) + '</strong>' + endpointBadge +
                '<div class="small text-muted mt-1">' + escapeHtml(fn.descripcion || '— sin descripción —') + '</div>' +
                '<div class="small text-muted mt-1" style="font-size:.7rem;">' +
                '<i class="fa fa-code me-1"></i>' + escapeHtml(fn.modulo || '') + '.' + escapeHtml(fn.nombre || '') +
                '</div>' +
            '</div>' +
            '<button type="button" class="btn btn-xs btn-outline-primary dp-fn-copy" data-codigo="' +
            escapeHtml(fn.codigo) + '">' +
            '<i class="fa fa-copy"></i> Copiar código</button>' +
            '</div>' +
            params +
            ejemplo +
            '</div>';
    }

    /* ────────────── Init ────────────── */
    function init() {
        wireMeta();
        wireSalidasEditor();
        wireModalSubmit();
        wireTreeActions();
        wireSortable();
        wireFiltros();
        wireBotonFunciones();
        setupBeforeUnload();
        manejarHashNodo();
        console.log('[dpchat_editor] init OK · dep_id=' + STATE.departamentoId);
    }

    // Si la URL tiene #nodo-<id> (ej. desde el botón "Editar" del diagrama),
    // scrollea al card, lo destaca y abre el modal de edición.
    function manejarHashNodo() {
        var hash = (window.location.hash || '').trim();
        var m = hash.match(/^#nodo-(\d+)$/);
        if (!m) return;
        var nodoId = parseInt(m[1], 10);
        if (!nodoId) return;

        var card = document.querySelector('.dp-node-card[data-id="' + nodoId + '"]');
        if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.classList.add('dp-highlight');
            setTimeout(function () { card.classList.remove('dp-highlight'); }, 4500);
        }
        // Abre el modal de edición tras un breve delay (espera scroll).
        setTimeout(function () {
            openNodeModal({ id: nodoId });
        }, 350);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
