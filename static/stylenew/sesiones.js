/* =============================================================
   Módulo Conexiones — lógica del tablero + modal + kebab menu.
   Usa jQuery + SweetAlert del base.html cuando está disponible
   (funciones globales: eliminarajax, Swal, pantallaespera).
   ============================================================= */
(function () {
    'use strict';

    // ---------- CSRF ----------
    function getCookie(name) {
        var m = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]+)'));
        return m ? decodeURIComponent(m[1]) : '';
    }

    function csrfToken() {
        var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return (input && input.value) || getCookie('csrftoken');
    }

    function postAccion(data) {
        var body = new URLSearchParams();
        body.append('csrfmiddlewaretoken', csrfToken());
        Object.keys(data).forEach(function (k) {
            body.append(k, data[k]);
        });
        return fetch(window.CONEX_URL, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken(),
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
            body: body,
        }).then(function (r) {
            return r.json();
        });
    }

    function fetchPartial(accion, pk) {
        var url = window.CONEX_URL + '?action=' + accion + '&pk=' + encodeURIComponent(pk);
        return fetch(url, {
            headers: {'X-Requested-With': 'XMLHttpRequest'},
            credentials: 'same-origin',
        }).then(function (r) {
            return r.json();
        });
    }

    // ---------- Refresco de cards sin recargar la página ----------
    // El endpoint sesiones?partial=card&id=X devuelve {error, estado, html}.
    // Si la card ya está en el grid, la reemplazamos; si es nueva (Meta connect /
    // OAuth recién creado), la insertamos arriba para evitar el location.reload.
    function htmlAElemento(html) {
        var t = document.createElement('template');
        t.innerHTML = (html || '').trim();
        return t.content.firstElementChild;
    }

    // Helper expuesto globalmente para que partials inyectados (modales) puedan
    // refrescar la card sin necesidad de location.reload.
    window.refrescarCardSesion = function (sesionId) {
        return refrescarCard(sesionId);
    };

    function refrescarCard(sesionId) {
        if (!sesionId) return Promise.resolve(null);
        var url = '/whatsapp/sesiones/?partial=card&id=' + encodeURIComponent(sesionId);
        return fetch(url, {
            headers: {'X-Requested-With': 'XMLHttpRequest'},
            credentials: 'same-origin',
        }).then(function (r) {
            return r.json();
        }).then(function (data) {
            if (!data || data.error || !data.html) return null;
            var nueva = htmlAElemento(data.html);
            if (!nueva) return null;
            var grid = document.getElementById('conex-grid');
            var existente = document.querySelector('.conex-card[data-sesion-id="' + sesionId + '"]');
            if (existente) {
                existente.replaceWith(nueva);
            } else if (grid) {
                // Si el grid estaba vacío, sacamos el placeholder antes de insertar.
                var empty = grid.querySelector('.conex-empty');
                if (empty) empty.remove();
                grid.insertBefore(nueva, grid.firstChild);
            }
            return nueva;
        }).catch(function () {
            return null;
        });
    }

    // ---------- Toast helper ----------
    function mostrarToast(msg, tipo) {
        if (window.Swal && Swal.fire) {
            var icon = tipo === 'ok' ? 'success' : tipo === 'err' ? 'error' : 'info';
            Swal.fire({
                type: icon,
                title: msg,
                timer: 2400,
                showConfirmButton: false,
                toast: true,
                position: 'top-end'
            });
            return;
        }
        var t = document.createElement('div');
        t.textContent = msg;
        t.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:2000;padding:.75rem 1.1rem;'
            + 'border-radius:10px;font-size:.9rem;box-shadow:0 6px 20px rgba(0,0,0,.15);max-width:420px;'
            + (tipo === 'ok' ? 'background:#d4f5e3;color:#15803d'
                : tipo === 'err' ? 'background:#fee2e2;color:#b91c1c'
                    : 'background:#e0f2fe;color:#0369a1');
        document.body.appendChild(t);
        setTimeout(function () {
            t.remove();
        }, 2800);
    }

    // ---------- Modal principal (Agregar conexión) ----------
    var modal = document.getElementById('conex-modal');

    function abrirModal(canalInicial) {
        if (!modal) return;
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        cambiarPanel(canalInicial || 'whatsapp');
    }

    function cerrarModal() {
        if (!modal) return;
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
    }

    var btnAbrir = document.getElementById('btn-abrir-modal');
    if (btnAbrir) btnAbrir.addEventListener('click', function () {
        abrirModal();
    });
    var btnCerrar = document.getElementById('btn-cerrar-modal');
    if (btnCerrar) btnCerrar.addEventListener('click', cerrarModal);
    document.querySelectorAll('[data-cerrar]').forEach(function (b) {
        b.addEventListener('click', cerrarModal);
    });
    if (modal) modal.addEventListener('click', function (e) {
        if (e.target === modal) cerrarModal();
    });

    function cambiarPanel(canal) {
        document.querySelectorAll('.conex-canal').forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-canal') === canal);
        });
        document.querySelectorAll('.pane').forEach(function (p) {
            p.classList.toggle('pane-hidden', p.getAttribute('data-pane') !== canal);
        });
    }

    document.querySelectorAll('.conex-canal').forEach(function (b) {
        b.addEventListener('click', function () {
            cambiarPanel(b.getAttribute('data-canal'));
        });
    });

    // ---------- Checkbox WhatsApp / botón Continuar (modo OAuth) ----------
    var chkWa = document.getElementById('chk-wa-requisitos');
    var btnCont = document.getElementById('btn-wa-continuar');
    var formManual = document.getElementById('form-wa-manual');
    var btnValManual = document.getElementById('btn-wa-validar-manual');
    var btnSaveManual = document.getElementById('btn-wa-guardar-manual');

    function setManualEnabled(enabled) {
        if (btnValManual) btnValManual.disabled = !enabled;
        if (btnSaveManual) btnSaveManual.disabled = !enabled;
        if (formManual) {
            formManual.querySelectorAll('input').forEach(function (i) {
                i.disabled = !enabled;
            });
        }
    }

    if (chkWa) {
        if (btnCont) {
            var continuarYaHabilitado = !btnCont.hasAttribute('disabled');
            if (!continuarYaHabilitado) {
                btnCont.disabled = true;
                chkWa.disabled = true;
            } else {
                btnCont.disabled = true;
            }
        }
        if (formManual) setManualEnabled(false);
        chkWa.addEventListener('change', function () {
            if (btnCont && !btnCont.hasAttribute('data-locked-out')) btnCont.disabled = !chkWa.checked;
            if (formManual) setManualEnabled(chkWa.checked);
        });
    }
    if (btnCont) {
        btnCont.addEventListener('click', function () {
            if (btnCont.disabled) return;
            var w = 600, h = 720;
            var left = (window.screen.width / 2) - (w / 2);
            var top = (window.screen.height / 2) - (h / 2);
            var popup = window.open(window.META_OAUTH_START_URL, 'meta_oauth',
                'width=' + w + ',height=' + h + ',left=' + left + ',top=' + top);
            if (!popup) mostrarToast('Tu navegador bloqueó el popup. Permite ventanas emergentes.', 'err');
        });
    }

    // ---------- Panel guía colapsable (modo manual) ----------
    var manHelpToggle = document.getElementById('man-help-toggle');
    var manHelpPanel = document.getElementById('man-help-panel');
    if (manHelpToggle && manHelpPanel) {
        manHelpToggle.addEventListener('click', function () {
            var open = manHelpPanel.hasAttribute('hidden') === false;
            if (open) {
                manHelpPanel.setAttribute('hidden', '');
                manHelpToggle.setAttribute('aria-expanded', 'false');
            } else {
                manHelpPanel.removeAttribute('hidden');
                manHelpToggle.setAttribute('aria-expanded', 'true');
            }
        });
    }
    // Links "¿de dónde?" → abre panel y resalta el paso correspondiente
    document.querySelectorAll('.man-help-link').forEach(function (link) {
        link.addEventListener('click', function (ev) {
            ev.preventDefault();
            if (!manHelpPanel || !manHelpToggle) return;
            if (manHelpPanel.hasAttribute('hidden')) {
                manHelpPanel.removeAttribute('hidden');
                manHelpToggle.setAttribute('aria-expanded', 'true');
            }
            var target = link.getAttribute('data-help-jump');
            var item = manHelpPanel.querySelector('li[data-target="' + target + '"]');
            if (!item) return;
            manHelpPanel.querySelectorAll('li.is-highlight').forEach(function (el) {
                el.classList.remove('is-highlight');
            });
            item.classList.add('is-highlight');
            item.scrollIntoView({behavior: 'smooth', block: 'nearest'});
            setTimeout(function () {
                item.classList.remove('is-highlight');
            }, 2200);
        });
    });

    // ---------- Toggle ojo password (modo manual) ----------
    var manTokenEye = document.getElementById('man-token-eye');
    var manTokenInp = document.getElementById('man-token');
    if (manTokenEye && manTokenInp) {
        manTokenEye.addEventListener('click', function () {
            var isPwd = manTokenInp.type === 'password';
            manTokenInp.type = isPwd ? 'text' : 'password';
            var icon = manTokenEye.querySelector('i');
            if (icon) icon.className = isPwd ? 'fa fa-eye-slash' : 'fa fa-eye';
        });
    }

    // ---------- Modo manual: validar + conectar ----------
    function fmGetCsrf() {
        var i = formManual && formManual.querySelector('input[name=csrfmiddlewaretoken]');
        return i ? i.value : '';
    }

    function fmGetData() {
        var d = new FormData(formManual);
        return d;
    }

    function fmShowResult(html, type) {
        var box = document.getElementById('man-resultado');
        if (!box) return;
        box.classList.remove('d-none', 'alert-success', 'alert-danger', 'alert-info', 'alert-warning');
        box.classList.add('alert-' + type);
        box.innerHTML = html;
    }

    function fmPost(url, formData, onDone) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', url, true);
        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
        xhr.setRequestHeader('X-CSRFToken', fmGetCsrf());
        xhr.onload = function () {
            var data = {};
            try {
                data = JSON.parse(xhr.responseText) || {};
            } catch (e) {
            }
            onDone(data, xhr.status);
        };
        xhr.onerror = function () {
            onDone({ok: false, error: 'Error de red.'}, 0);
        };
        xhr.send(formData);
    }

    // Modal de validación
    var valModal = document.getElementById('man-val-modal');
    var valBody = document.getElementById('man-val-body');
    var valTitle = document.getElementById('man-val-title');
    var valStatusDot = document.getElementById('man-val-status-dot');
    var valConectar = document.getElementById('man-val-conectar');
    var valClose = document.getElementById('man-val-close');
    var valCerrar2 = document.getElementById('man-val-cerrar2');

    function valOpen() {
        if (!valModal) return;
        valModal.classList.add('open');
        valModal.setAttribute('aria-hidden', 'false');
        if (valBody) {
            valBody.innerHTML = '<div class="man-val-loader"><i class="fa fa-spinner fa-spin"></i><p>Consultando Graph API...</p></div>';
        }
        if (valStatusDot) valStatusDot.className = 'man-val-status-dot is-loading';
        if (valTitle) valTitle.textContent = 'Validando credenciales en Meta...';
        if (valConectar) {
            valConectar.disabled = true;
            valConectar.style.display = '';  // Reset al estado por defecto del modo manual
        }
    }

    function valClose_() {
        if (!valModal) return;
        valModal.classList.remove('open');
        valModal.setAttribute('aria-hidden', 'true');
    }

    if (valClose) valClose.addEventListener('click', valClose_);
    if (valCerrar2) valCerrar2.addEventListener('click', valClose_);
    if (valModal) {
        valModal.addEventListener('click', function (e) {
            if (e.target === valModal) valClose_();
        });
    }
    if (valConectar) {
        valConectar.addEventListener('click', function () {
            valClose_();
            // Disparar submit del form (mismo flujo que el botón Conectar de abajo)
            if (formManual) formManual.dispatchEvent(new Event('submit', {cancelable: true}));
        });
    }
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && valModal && valModal.classList.contains('open')) valClose_();
    });

    function valRenderError(msg) {
        if (valStatusDot) valStatusDot.className = 'man-val-status-dot is-error';
        if (valTitle) valTitle.textContent = 'Meta rechazó las credenciales';
        if (valBody) {
            valBody.innerHTML =
                '<div class="man-val-msg is-error">' +
                '<i class="fa fa-circle-xmark"></i>' +
                '<div><b>No pudimos validar.</b><p>' + (msg || 'Error desconocido.') + '</p></div>' +
                '</div>' +
                '<div class="man-val-hint"><i class="fa fa-lightbulb"></i> Verificá: el Phone Number ID NO es el número telefónico, el token tiene los scopes correctos, y la WABA está asignada al System User.</div>';
        }
        if (valConectar) valConectar.disabled = true;
    }

    function valRenderOk(data, modo) {
        var esRevalidar = modo === 'revalidar';
        if (valStatusDot) valStatusDot.className = 'man-val-status-dot is-ok';
        if (valTitle) valTitle.textContent = esRevalidar ? 'Credenciales revalidadas' : 'Credenciales válidas';

        var qrColor = (data.quality_rating || 'UNKNOWN').toLowerCase();
        var qrBadge = qrColor === 'green' ? 'is-green'
            : qrColor === 'yellow' ? 'is-yellow'
                : qrColor === 'red' ? 'is-red'
                    : 'is-gray';

        var rows = '';
        if (data.waba_name) {
            rows += '<div class="man-val-row"><span class="man-val-key"><i class="fa fa-id-card"></i> WABA</span><span class="man-val-val">' + data.waba_name + '</span></div>';
        }
        if (data.verified_name) {
            rows += '<div class="man-val-row"><span class="man-val-key"><i class="fa fa-circle-check"></i> Nombre verificado</span><span class="man-val-val">' + data.verified_name + '</span></div>';
        }
        if (data.display_phone_number) {
            rows += '<div class="man-val-row"><span class="man-val-key"><i class="fa fa-phone"></i> Número</span><span class="man-val-val"><code>' + data.display_phone_number + '</code></span></div>';
        }
        if (data.quality_rating) {
            rows += '<div class="man-val-row"><span class="man-val-key"><i class="fa fa-star"></i> Quality rating</span><span class="man-val-val"><span class="man-val-pill ' + qrBadge + '">' + data.quality_rating + '</span></span></div>';
        }

        var hint = esRevalidar
            ? '<div class="man-val-hint"><i class="fa fa-circle-check"></i> Los datos quedaron sincronizados con Meta. Podés cerrar esta ventana.</div>'
            : '<div class="man-val-hint"><i class="fa fa-lightbulb"></i> Pulsá <b>Conectar sesión</b> para guardar y empezar a recibir mensajes.</div>';
        if (valBody) {
            valBody.innerHTML =
                '<div class="man-val-msg is-ok">' +
                '<i class="fa fa-circle-check"></i>' +
                '<div><b>Meta confirmó los IDs y el token.</b><p>Lo que detectamos:</p></div>' +
                '</div>' +
                '<div class="man-val-grid">' + rows + '</div>' +
                hint;
        }
        if (valConectar && !esRevalidar) valConectar.disabled = false;

        // Autocompletar el "Número visible" del form si el campo está vacío.
        if (data.display_phone_number) {
            var disp = document.getElementById('man-display');
            if (disp && !disp.value) disp.value = data.display_phone_number;
        }
    }

    if (btnValManual && formManual) {
        btnValManual.addEventListener('click', function () {
            if (btnValManual.disabled) return;
            valOpen();
            var orig = btnValManual.innerHTML;
            btnValManual.disabled = true;
            btnValManual.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Validando...';
            fmPost(window.META_MANUAL_VALIDAR_URL || '/whatsapp/meta/manual/validar/', fmGetData(), function (data) {
                btnValManual.disabled = false;
                btnValManual.innerHTML = orig;
                if (!data.ok) {
                    valRenderError(data.error || 'Meta rechazó las credenciales.');
                } else {
                    valRenderOk(data);
                }
            });
        });
    }
    if (formManual) {
        formManual.addEventListener('submit', function (ev) {
            ev.preventDefault();
            if (btnSaveManual && btnSaveManual.disabled) return;
            var orig = btnSaveManual ? btnSaveManual.innerHTML : '';
            if (btnSaveManual) {
                btnSaveManual.disabled = true;
                btnSaveManual.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Conectando...';
            }
            fmPost(window.META_MANUAL_CONECTAR_URL || '/whatsapp/meta/manual/conectar/', fmGetData(), function (data) {
                if (btnSaveManual) {
                    btnSaveManual.disabled = false;
                    btnSaveManual.innerHTML = orig;
                }
                if (!data.ok) {
                    fmShowResult('<i class="fa fa-circle-xmark me-2"></i>' + (data.error || 'No se pudo conectar la sesión.'), 'danger');
                    return;
                }
                fmShowResult('<i class="fa fa-circle-check me-2"></i>Sesión <b>' + (data.nombre || '') + '</b> conectada.', 'success');
                cerrarModal();
                mostrarToast('WhatsApp conectado manualmente: ' + (data.display_phone_number || data.nombre || ''), 'ok');
                refrescarCard(data.sesion_id);
            });
        });
    }

    // ---------- postMessage del popup OAuth ----------
    window.addEventListener('message', function (ev) {
        var data = ev.data || {};
        if (data.source !== 'meta_oauth') return;
        var p = data.payload || {};
        if (p.ok) {
            cerrarModal();
            mostrarToast('WhatsApp enlazado: ' + (p.numero || p.nombre || ''), 'ok');
            refrescarCard(p.sesion_id);
        } else {
            mostrarToast(p.error || 'Meta no permitió completar la conexión.', 'err');
        }
    });

    // ---------- Modal secundario (detail) ----------
    var detailBackdrop = document.getElementById('conex-detail-modal');
    var detailContent = document.getElementById('conex-detail-content');

    function abrirDetail(html) {
        if (!detailBackdrop) return;
        detailContent.innerHTML = html;
        detailContent.querySelectorAll('script').forEach(function (old) {
            var s = document.createElement('script');
            for (var i = 0; i < old.attributes.length; i++) {
                s.setAttribute(old.attributes[i].name, old.attributes[i].value);
            }
            s.text = old.textContent;
            old.parentNode.replaceChild(s, old);
        });
        detailBackdrop.classList.add('open');
        detailBackdrop.setAttribute('aria-hidden', 'false');
        rebindFormsJs();
    }

    function escaparHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function renderCambiarNombre(nombreActual, metaUrl) {
        var linkMeta = metaUrl
            ? '<a href="' + escaparHtml(metaUrl) + '" target="_blank" rel="noopener" class="cn-meta-link">' +
              '<i class="fa fa-up-right-from-square"></i> Validar / ver estado del nombre en Meta</a>'
            : '';
        return '<div class="detail-wrap">' +
            '<div class="detail-head">' +
                '<div><h5><i class="fa fa-signature me-1 text-primary"></i> Cambiar nombre del número</h5>' +
                '<p class="muted">Display Name que ven los clientes en WhatsApp</p></div>' +
                '<button type="button" class="detail-close" data-cerrar-detail><i class="fa fa-times"></i></button>' +
            '</div>' +
            '<div class="detail-body">' +
                '<p class="cn-help">Meta lo revisa (minutos a días) y debe reflejar tu marca/negocio — nombres ' +
                'genéricos o de rol suelen rechazarse. El número sigue operando con el nombre actual durante la revisión.</p>' +
                '<div class="conex-data-block">' +
                    '<label class="cn-label" for="cn-input">Nuevo nombre para mostrar</label>' +
                    '<input type="text" id="cn-input" class="form-control" maxlength="60" autocomplete="off" ' +
                    'value="' + escaparHtml(nombreActual || '') + '">' +
                    '<button type="button" class="conex-btn conex-btn-primary valcx-cta" id="cn-enviar">' +
                    '<i class="fa fa-paper-plane"></i> Enviar a revisión de Meta</button>' +
                    linkMeta +
                    '<div id="cn-result" class="valcx-verdict" hidden></div>' +
                '</div>' +
            '</div>' +
        '</div>';
    }

    function renderValidacionConexion(data) {
        var filas = (data.pasos || []).map(function (p) {
            var icono, clase;
            if (p.ok === true) { icono = 'fa-circle-check'; clase = 'is-ok'; }
            else if (p.ok === false) { icono = 'fa-circle-xmark'; clase = 'is-bad'; }
            else { icono = 'fa-circle-question'; clase = 'is-warn'; }
            return '<li class="valcx-step ' + clase + '">' +
                '<i class="fa ' + icono + '"></i>' +
                '<div class="valcx-step-body"><span class="valcx-step-label">' + escaparHtml(p.label) + '</span>' +
                '<span class="valcx-step-detail">' + escaparHtml(p.detalle) + '</span></div>' +
                '</li>';
        }).join('');

        var verdClase = data.falla ? (data.waba_mal ? 'is-warn' : 'is-bad') : 'is-ok';
        var verdIcono = data.falla ? 'fa-triangle-exclamation' : 'fa-circle-check';

        var accionBtn = '';
        if (data.falla) {
            accionBtn = '<a class="conex-btn conex-btn-primary valcx-cta" href="' +
                escaparHtml(data.diagnostico_url) + '"><i class="fa fa-wrench"></i> ' +
                'Ir al diagnóstico a ejecutar correcciones</a>';
        } else {
            accionBtn = '<a class="conex-btn conex-btn-ghost valcx-cta" href="' +
                escaparHtml(data.diagnostico_url) + '"><i class="fa fa-stethoscope"></i> Ver diagnóstico</a>';
        }

        return '<div class="detail-wrap">' +
            '<div class="detail-head">' +
                '<div><h5><i class="fa fa-clipboard-check me-1 text-primary"></i> Validación de conexión</h5>' +
                '<p class="muted">Sesión <b>' + escaparHtml(data.sesion_nombre) + '</b> · chequeos contra Meta</p></div>' +
                '<button type="button" class="detail-close" data-cerrar-detail><i class="fa fa-times"></i></button>' +
            '</div>' +
            '<div class="detail-body">' +
                '<ul class="valcx-steps">' + filas + '</ul>' +
                '<div class="valcx-verdict ' + verdClase + '"><i class="fa ' + verdIcono + '"></i> ' +
                    escaparHtml(data.verdicto) + '</div>' +
                accionBtn +
            '</div>' +
        '</div>';
    }

    // ---------- Re-attach forms.js (handler global de POST + AJAX) ----------
    // forms.js bindea `$('form:not(...)').submit(...)` al cargar — los forms
    // dentro de partials AJAX no estaban presentes en ese momento. Quitamos
    // el flag `formsJsValidator` y reinyectamos el script para que vuelva
    // a barrer el DOM y bindee al form recién insertado.
    function rebindFormsJs() {
        var meta = document.querySelector('meta[name=formsJsValidator]');
        if (meta) meta.remove();
        var s = document.createElement('script');
        s.src = '/static/js/forms.js?v=' + Date.now();
        s.async = false;
        document.body.appendChild(s);
    }

    function cerrarDetail() {
        if (!detailBackdrop) return;
        detailBackdrop.classList.remove('open');
        detailBackdrop.setAttribute('aria-hidden', 'true');
        detailContent.innerHTML = '';
    }

    if (detailBackdrop) detailBackdrop.addEventListener('click', function (e) {
        if (e.target === detailBackdrop) cerrarDetail();
    });

    // Click en cualquier [data-cerrar-detail] dentro del modal secundario
    document.addEventListener('click', function (e) {
        if (e.target.closest('[data-cerrar-detail]')) cerrarDetail();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (detailBackdrop && detailBackdrop.classList.contains('open')) return cerrarDetail();
        if (modal && modal.classList.contains('open')) return cerrarModal();
    });

    // ---------- Offcanvas lateral de acciones ----------
    function abrirAccionesOffcanvas(card) {
        var oc = document.getElementById('acc-offcanvas');
        var bd = document.getElementById('acc-offcanvas-backdrop');
        var body = document.getElementById('acc-offcanvas-body');
        var title = document.getElementById('acc-offcanvas-title');
        var menu = card ? card.querySelector('[data-kebab-menu]') : null;
        if (!oc || !body || !menu) return;
        oc.setAttribute('data-sesion-id', card.getAttribute('data-sesion-id') || '');
        oc.setAttribute('data-sesion-nombre', card.getAttribute('data-sesion-nombre') || '');
        oc.setAttribute('data-sesion-numero', card.getAttribute('data-sesion-numero') || '');
        oc.setAttribute('data-meta-url', card.getAttribute('data-meta-url') || '');
        if (title) title.textContent = card.getAttribute('data-sesion-nombre') || 'Acciones';
        body.innerHTML = menu.innerHTML;
        oc.classList.add('open');
        oc.setAttribute('aria-hidden', 'false');
        if (bd) { bd.classList.add('open'); bd.setAttribute('aria-hidden', 'false'); }
    }

    function cerrarAccionesOffcanvas() {
        var oc = document.getElementById('acc-offcanvas');
        var bd = document.getElementById('acc-offcanvas-backdrop');
        if (oc) { oc.classList.remove('open'); oc.setAttribute('aria-hidden', 'true'); }
        if (bd) { bd.classList.remove('open'); bd.setAttribute('aria-hidden', 'true'); }
    }

    document.addEventListener('click', function (e) {
        var toggle = e.target.closest('[data-kebab-toggle]');
        if (toggle) {
            var card = toggle.closest('.conex-card');
            if (card) abrirAccionesOffcanvas(card);
            e.stopPropagation();
            return;
        }
        if (e.target.closest('#acc-offcanvas-close') || e.target.closest('#acc-offcanvas-backdrop')) {
            cerrarAccionesOffcanvas();
        }
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') cerrarAccionesOffcanvas();
    });

    // ---------- Baileys QR ----------
    var baileysSesionId = null;
    var baileysPoll = null;
    var btnBaileysStart = document.getElementById('btn-baileys-start');
    if (btnBaileysStart) {
        btnBaileysStart.addEventListener('click', function () {
            btnBaileysStart.disabled = true;
            btnBaileysStart.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Generando...';
            var data = {action: 'baileys_start'};
            if (baileysSesionId) data.session_id = baileysSesionId;
            postAccion(data).then(function (res) {
                btnBaileysStart.disabled = false;
                btnBaileysStart.innerHTML = '<i class="fa fa-rotate me-1"></i> Regenerar código';
                if (res.error) return mostrarToast(res.message || 'Error generando QR', 'err');
                baileysSesionId = res.sesion_id;
                mostrarQR(res.qr);
                iniciarPollBaileys();
            }).catch(function (ex) {
                btnBaileysStart.disabled = false;
                btnBaileysStart.innerHTML = '<i class="fa fa-qrcode me-1"></i> Generar código QR';
                mostrarToast('Error de red: ' + ex, 'err');
            });
        });
    }

    function mostrarQR(qr) {
        var img = document.getElementById('qr-img');
        var ph = document.getElementById('qr-placeholder');
        var ok = document.getElementById('qr-success');
        if (ph) ph.style.display = 'none';
        if (ok) ok.style.display = 'none';
        if (img) {
            img.style.display = qr ? 'block' : 'none';
            img.src = qr || '';
        }
    }

    function mostrarConectado(num) {
        var img = document.getElementById('qr-img');
        var ph = document.getElementById('qr-placeholder');
        var ok = document.getElementById('qr-success');
        var n = document.getElementById('qr-success-num');
        if (ph) ph.style.display = 'none';
        if (img) img.style.display = 'none';
        if (ok) ok.style.display = 'block';
        if (n) n.textContent = num ? '+' + num : '';
    }

    function iniciarPollBaileys() {
        if (baileysPoll) clearInterval(baileysPoll);
        baileysPoll = setInterval(function () {
            if (!baileysSesionId) {
                clearInterval(baileysPoll);
                return;
            }
            postAccion({action: 'baileys_status', sesion_id: baileysSesionId}).then(function (res) {
                if (res.error) return;
                if (res.estado === 'conectado') {
                    clearInterval(baileysPoll);
                    baileysPoll = null;
                    mostrarConectado(res.numero);
                    refrescarCard(baileysSesionId);
                } else if (res.qr) {
                    var img = document.getElementById('qr-img');
                    if (img && img.src !== res.qr) mostrarQR(res.qr);
                }
            });
        }, 3000);
    }

    // ---------- Búsqueda live ----------
    var searchInput = document.getElementById('conex-search-input');
    if (searchInput) {
        var debounce = null;
        searchInput.addEventListener('input', function () {
            clearTimeout(debounce);
            debounce = setTimeout(function () {
                var q = encodeURIComponent(searchInput.value.trim());
                window.location.href = window.CONEX_URL + (q ? ('?criterio=' + q) : '');
            }, 400);
        });
    }

    function _updateBulkCount() {
        var n = document.querySelectorAll('.conex-card .conex-bulk-cb:checked').length;
        var elN = document.getElementById('conex-bulk-count');
        var btn = document.getElementById('conex-bulk-delete');
        if (elN) elN.textContent = String(n);
        if (btn) btn.disabled = (n === 0);
    }

    function _ensureBulkCheckbox(card) {
        if (card.querySelector('.conex-bulk-cb-wrap')) return;
        var wrap = document.createElement('label');
        wrap.className = 'conex-bulk-cb-wrap';
        wrap.title = 'Select for bulk delete';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'conex-bulk-cb';
        cb.setAttribute('data-sesion-id', card.getAttribute('data-sesion-id') || '');
        cb.addEventListener('click', function (e) { e.stopPropagation(); });
        cb.addEventListener('change', _updateBulkCount);
        wrap.appendChild(cb);
        card.appendChild(wrap);
    }

    function _setBulkMode(on) {
        var bar = document.getElementById('conex-bulk-bar');
        if (bar) bar.classList.toggle('d-none', !on);
        document.querySelectorAll('.conex-card').forEach(function (card) {
            if (on) {
                _ensureBulkCheckbox(card);
                card.classList.add('conex-card-bulk-mode');
            } else {
                card.classList.remove('conex-card-bulk-mode');
                var cb = card.querySelector('.conex-bulk-cb');
                if (cb) cb.checked = false;
            }
        });
        _updateBulkCount();
    }

    document.querySelectorAll('.conex-chip').forEach(function (chip) {
        chip.addEventListener('click', function () {
            document.querySelectorAll('.conex-chip').forEach(function (c) {
                c.classList.remove('active');
            });
            chip.classList.add('active');
            var f = chip.getAttribute('data-filtro');
            var attr = chip.getAttribute('data-attr');
            var val = chip.getAttribute('data-val');
            document.querySelectorAll('.conex-card').forEach(function (card) {
                var show;
                if (f === 'todas') {
                    show = true;
                } else if (attr) {
                    show = card.getAttribute('data-' + attr) === val;
                } else {
                    show = card.getAttribute('data-estado') === f;
                }
                card.style.display = show ? '' : 'none';
            });
            _setBulkMode(f === 'pausadas');
        });
    });

    var bulkSelectAll = document.getElementById('conex-bulk-select-all');
    if (bulkSelectAll) bulkSelectAll.addEventListener('click', function () {
        document.querySelectorAll('.conex-card').forEach(function (card) {
            if (card.style.display === 'none') return;
            var cb = card.querySelector('.conex-bulk-cb');
            if (cb) cb.checked = true;
        });
        _updateBulkCount();
    });

    var bulkClear = document.getElementById('conex-bulk-clear');
    if (bulkClear) bulkClear.addEventListener('click', function () {
        document.querySelectorAll('.conex-card .conex-bulk-cb').forEach(function (cb) {
            cb.checked = false;
        });
        _updateBulkCount();
    });

    var bulkDelete = document.getElementById('conex-bulk-delete');
    if (bulkDelete) bulkDelete.addEventListener('click', function () {
        var ids = Array.from(document.querySelectorAll('.conex-card .conex-bulk-cb:checked'))
            .map(function (cb) { return cb.getAttribute('data-sesion-id'); })
            .filter(function (x) { return !!x; });
        if (!ids.length) return;
        var msg = 'Soft-delete ' + ids.length + ' session(s)? They will be marked status=False.';
        if (typeof Swal === 'undefined') {
            if (!confirm(msg)) return;
            _doBulkDelete(ids);
        } else {
            Swal.fire({
                title: msg,
                text: 'This action sets status=False (recoverable manually in DB).',
                type: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#d33',
                cancelButtonColor: '#3085d6',
                confirmButtonText: 'Yes, delete',
                cancelButtonText: 'Cancel'
            }).then(function (r) { if (r.value) _doBulkDelete(ids); });
        }
    });

    function _doBulkDelete(ids) {
        postAccion({ action: 'delete_bulk', ids: ids.join(',') }).then(function (r) {
            if (r && r.error) {
                mostrarToast(r.message || 'Bulk delete failed.', 'err');
                return;
            }
            mostrarToast((r && r.message) || 'Deleted.', 'ok');
            setTimeout(function () { window.location.reload(); }, 600);
        });
    }

    var bulkDeleteOrphans = document.getElementById('conex-bulk-delete-orphans');
    if (bulkDeleteOrphans) bulkDeleteOrphans.addEventListener('click', function () {
        var msg = 'Soft-delete ALL paused orphan sessions (no contacts)?';
        if (typeof Swal === 'undefined') {
            if (!confirm(msg)) return;
            _doBulkOrphan();
        } else {
            Swal.fire({
                title: msg,
                text: 'Removes every paused session that has zero contacts.',
                type: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#d33',
                cancelButtonColor: '#3085d6',
                confirmButtonText: 'Yes, clean up',
                cancelButtonText: 'Cancel'
            }).then(function (r) { if (r.value) _doBulkOrphan(); });
        }
    });

    function _doBulkOrphan() {
        postAccion({ action: 'delete_pausadas_huerfanas' }).then(function (r) {
            if (r && r.error) {
                mostrarToast(r.message || 'Cleanup failed.', 'err');
                return;
            }
            mostrarToast((r && r.message) || 'Cleanup done.', 'ok');
            setTimeout(function () { window.location.reload(); }, 600);
        });
    }

    // ---------- Modal: Eco / Test envío (Meta) ----------
    var ecoModal = document.getElementById('eco-modal');
    var ecoFromLabel = document.getElementById('eco-from-label');
    var ecoNumero = document.getElementById('eco-numero');
    var ecoMensaje = document.getElementById('eco-mensaje');
    var ecoResultado = document.getElementById('eco-resultado');
    var ecoEnviar = document.getElementById('eco-enviar');
    var ecoSesionId = null;

    function cerrarEcoModal() {
        if (!ecoModal) return;
        ecoModal.classList.remove('open');
        ecoModal.setAttribute('aria-hidden', 'true');
    }

    document.querySelectorAll('[data-eco-close]').forEach(function (b) {
        b.addEventListener('click', cerrarEcoModal);
    });
    if (ecoModal) {
        ecoModal.addEventListener('click', function (e) {
            if (e.target === ecoModal) cerrarEcoModal();
        });
    }
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && ecoModal && ecoModal.classList.contains('open')) cerrarEcoModal();
    });

    function ecoShowResult(html, type) {
        if (!ecoResultado) return;
        ecoResultado.classList.remove('d-none', 'alert-success', 'alert-danger', 'alert-info');
        ecoResultado.classList.add('alert-' + type);
        ecoResultado.innerHTML = html;
    }

    function abrirEco(sesionId, nombre, numero) {
        ecoSesionId = sesionId;
        if (ecoFromLabel) {
            var etiqueta = nombre || ('sesión #' + sesionId);
            if (numero) etiqueta += ' (' + numero + ')';
            ecoFromLabel.textContent = etiqueta;
        }
        if (ecoNumero) ecoNumero.value = '';
        if (ecoMensaje) ecoMensaje.value = 'Hola! Este es un mensaje de prueba desde el CRM. Si lo recibís, la conexión funciona.';
        if (ecoResultado) ecoResultado.classList.add('d-none');
        if (ecoModal) {
            ecoModal.classList.add('open');
            ecoModal.setAttribute('aria-hidden', 'false');
        }
        setTimeout(function () {
            if (ecoNumero) ecoNumero.focus();
        }, 100);
    }

    if (ecoEnviar) {
        ecoEnviar.addEventListener('click', function () {
            if (!ecoSesionId) return;
            var num = (ecoNumero && ecoNumero.value || '').trim();
            var msg = (ecoMensaje && ecoMensaje.value || '').trim();
            if (!num || !msg) {
                ecoShowResult('<i class="fa fa-circle-xmark"></i> Completá número y mensaje.', 'danger');
                return;
            }
            var orig = ecoEnviar.innerHTML;
            ecoEnviar.disabled = true;
            ecoEnviar.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Enviando...';

            var fd = new FormData();
            fd.append('numero', num);
            fd.append('mensaje', msg);
            var csrf = document.querySelector('input[name=csrfmiddlewaretoken]');
            fd.append('csrfmiddlewaretoken', csrf ? csrf.value : '');

            fetch('/whatsapp/meta/test-message/' + ecoSesionId + '/', {
                method: 'POST',
                body: fd,
                headers: {'X-CSRFToken': csrf ? csrf.value : '', 'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
            })
                .then(function (r) {
                    return r.json();
                })
                .then(function (data) {
                    ecoEnviar.disabled = false;
                    ecoEnviar.innerHTML = orig;
                    if (!data.ok) {
                        ecoShowResult('<i class="fa fa-circle-xmark"></i> <b>Meta rechazó:</b> ' + (data.error || 'Error desconocido'), 'danger');
                        return;
                    }
                    ecoShowResult(
                        '<i class="fa fa-circle-check"></i> <b>Mensaje enviado.</b> ' +
                        'Meta devolvió ID <code>' + (data.message_id || '—') + '</code>. ' +
                        'Revisá el WhatsApp del número <code>' + (data.numero || '') + '</code>.',
                        'success'
                    );
                })
                .catch(function () {
                    ecoEnviar.disabled = false;
                    ecoEnviar.innerHTML = orig;
                    ecoShowResult('<i class="fa fa-circle-xmark"></i> Error de red.', 'danger');
                });
        });
    }

    // ---------- Cambiar foto de perfil (Meta) ----------
    // Reutiliza el detail modal (#conex-detail-content) inyectando un panel
    // con un input.dropify (preview/drag-drop nativo de dropify, ya cargado
    // globalmente vía form-controls-init.js). Submit vía fetch al endpoint
    // /whatsapp/sesiones/<id>/profile-picture/. En éxito refresca la card.
    function abrirCambiarFoto(sesionId, nombre) {
        var safeNombre = (nombre || ('sesión #' + sesionId)).replace(/[<>&"]/g, function (c) {
            return {'<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;'}[c];
        });
        var html =
            '<div class="detail-wrap">' +
              '<div class="detail-head">' +
                '<div>' +
                  '<h5><i class="fa fa-image me-1 text-primary"></i> Cambiar foto de perfil</h5>' +
                  '<p class="muted">Sesión <b>' + safeNombre + '</b> · JPG/PNG, mín. 192×192, máx. 5 MB.</p>' +
                '</div>' +
                '<button type="button" class="detail-close" data-cerrar-detail><i class="fa fa-times"></i></button>' +
              '</div>' +
              '<div class="detail-body">' +
                '<input type="file" id="foto-upload-input" class="dropify" ' +
                       'accept="image/jpeg,image/png" ' +
                       'data-allowed-file-extensions="jpg jpeg png" ' +
                       'data-max-file-size="5M">' +
                '<div id="foto-upload-result" class="conex-data-warn d-none foto-upload-result"></div>' +
                '<div class="detail-actions foto-upload-actions">' +
                  '<button type="button" class="conex-btn conex-btn-secondary" data-cerrar-detail>Cancelar</button>' +
                  '<button type="button" class="conex-btn conex-btn-primary" id="foto-upload-submit" disabled>' +
                    '<i class="fa fa-upload me-1"></i> Subir a Meta' +
                  '</button>' +
                '</div>' +
              '</div>' +
            '</div>';
        abrirDetail(html);

        var input  = document.getElementById('foto-upload-input');
        var submit = document.getElementById('foto-upload-submit');
        var result = document.getElementById('foto-upload-result');

        // Inicializar Dropify manualmente — el detail modal no es un
        // Bootstrap modal, así que no lo agarra el listener global.
        var $input = window.jQuery && jQuery(input);
        if ($input && $input.dropify) {
            $input.dropify({
                messages: {
                    default: 'Arrastrá una imagen acá o hacé click',
                    replace: 'Arrastrá o hacé click para reemplazar',
                    remove:  'Quitar',
                    error:   'Algo salió mal',
                },
                error: {
                    fileSize: 'Demasiado grande (máx. 5 MB).',
                    fileExtension: 'Solo JPG o PNG.',
                },
            });
        }

        function showResult(msg, tipo) {
            if (!result) return;
            result.classList.remove('d-none');
            result.textContent = msg;
            result.classList.toggle('is-err', tipo === 'err');
            result.classList.toggle('is-ok',  tipo !== 'err');
        }

        if (input) {
            input.addEventListener('change', function () {
                var ok = input.files && input.files[0]
                         && /^image\/(jpeg|png)$/.test(input.files[0].type)
                         && input.files[0].size <= 5 * 1024 * 1024;
                submit.disabled = !ok;
                if (ok && result) result.classList.add('d-none');
            });
        }

        if (submit) {
            submit.addEventListener('click', function () {
                var file = input && input.files && input.files[0];
                if (!file) return;
                submit.disabled = true;
                var orig = submit.innerHTML;
                submit.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i> Subiendo...';
                var fd = new FormData();
                fd.append('foto', file);
                fd.append('csrfmiddlewaretoken', csrfToken());
                fetch('/whatsapp/sesiones/' + sesionId + '/profile-picture/', {
                    method: 'POST',
                    headers: {'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'},
                    credentials: 'same-origin',
                    body: fd,
                })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        submit.disabled = false;
                        submit.innerHTML = orig;
                        if (!data.success) {
                            showResult(data.message || 'No se pudo actualizar la foto.', 'err');
                            return;
                        }
                        mostrarToast('Foto actualizada en Meta.', 'ok');
                        refrescarCard(sesionId);
                        cerrarDetail();
                    })
                    .catch(function () {
                        submit.disabled = false;
                        submit.innerHTML = orig;
                        showResult('Error de red al subir la foto.', 'err');
                    });
            });
        }
    }

    // ---------- Toggle Activa/Pausada (corta procesamiento + consumo API) ----------
    document.addEventListener('change', function (e) {
        var input = e.target;
        if (!input.matches || !input.matches('[data-action="toggle-activo"]')) return;
        var card = input.closest('.conex-card');
        if (!card) return;
        var sesionId = card.getAttribute('data-sesion-id');
        var nombre = card.getAttribute('data-sesion-nombre') || '';
        var nuevoEstado = input.checked; // true = activar, false = pausar
        var prevChecked = !nuevoEstado;

        var confirmar = function (cb) {
            if (!nuevoEstado && window.Swal) {
                Swal.fire({
                    title: '¿Pausar ' + nombre + '?',
                    text: 'La sesión dejará de procesar mensajes y de consumir API/IA. ' +
                          'El socket sigue conectado; podés reactivarla cuando quieras.',
                    type: 'warning', showCancelButton: true, allowOutsideClick: false,
                    confirmButtonText: 'Sí, pausar', cancelButtonText: 'Cancelar',
                    confirmButtonColor: '#d97706',
                }).then(function (res) {
                    if (!res.value) {
                        input.checked = prevChecked;
                        return;
                    }
                    cb();
                });
            } else {
                cb();
            }
        };

        confirmar(function () {
            input.disabled = true;
            postAccion({action: 'toggle_activo', id: sesionId}).then(function (r) {
                input.disabled = false;
                if (r.error) {
                    input.checked = prevChecked;
                    return mostrarToast(r.message || 'No se pudo cambiar el estado.', 'err');
                }
                mostrarToast(r.message, 'ok');
                refrescarCard(sesionId);
            }).catch(function () {
                input.disabled = false;
                input.checked = prevChecked;
                mostrarToast('Error de red al cambiar el estado.', 'err');
            });
        });
    });

    // ---------- Acciones del kebab y botones rápidos ----------
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-action]');
        if (!btn) return;
        // Ignorar el toggle activa/pausa — lo maneja el listener `change`.
        if (btn.getAttribute('data-action') === 'toggle-activo') return;
        // El contexto puede venir de la card o del offcanvas lateral (donde
        // se clonan las acciones). Tomamos el que aplique.
        var ctx = btn.closest('.conex-card') || btn.closest('#acc-offcanvas');
        if (!ctx) return;
        var card = ctx;
        var sesionId = ctx.getAttribute('data-sesion-id');
        var nombre = ctx.getAttribute('data-sesion-nombre') || '';
        var numero = ctx.getAttribute('data-sesion-numero') || '';
        var action = btn.getAttribute('data-action');

        // Cerrar el offcanvas de acciones al elegir una.
        cerrarAccionesOffcanvas();

        if (action === 'editar') {
            fetchPartial('editar_modal', sesionId).then(function (r) {
                if (!r.ok) return mostrarToast(r.message || 'No se pudo abrir el editor.', 'err');
                abrirDetail(r.html);
            });
        } else if (action === 'usuarios') {
            if (typeof formModal === 'function') {
                formModal(sesionId, '<i class="fa fa-users me-1"></i> Usuarios asignables — ' + nombre, 'usuarios');
            } else {
                mostrarToast('formModal no disponible.', 'err');
            }
        } else if (action === 'historial') {
            fetchPartial('historial_modal', sesionId).then(function (r) {
                if (!r.ok) return mostrarToast(r.message || 'No se pudo cargar el historial.', 'err');
                abrirDetail(r.html);
            });
        } else if (action === 'resumen') {
            fetchPartial('resumen_modal', sesionId).then(function (r) {
                if (!r.ok) return mostrarToast(r.message || 'No se pudo cargar el resumen.', 'err');
                abrirDetail(r.html);
            });
        } else if (action === 'post-conexion') {
            if (typeof formModal === 'function') {
                formModal(sesionId, '<i class="fa fa-list-check me-1"></i> Configurar en Facebook — ' + nombre, 'post-conexion');
            } else {
                mostrarToast('formModal no disponible.', 'err');
            }
        } else if (action === 'plantilla-prueba') {
            fetchPartial('plantilla_modal', sesionId).then(function (r) {
                if (!r.ok) return mostrarToast(r.message || 'No se pudo abrir la plantilla.', 'err');
                abrirDetail(r.html);
            });
        } else if (action === 'meta-validar') {
            // Abrir modal de validación con loader; conectar oculto, sólo info
            valOpen();
            // Override título para revalidación
            var valTitleEl = document.getElementById('man-val-title');
            if (valTitleEl) valTitleEl.textContent = 'Revalidando con Meta...';
            var valConectarBtn = document.getElementById('man-val-conectar');
            if (valConectarBtn) valConectarBtn.style.display = 'none';
            postAccion({action: 'meta_validar', id: sesionId}).then(function (r) {
                if (r.error) {
                    valRenderError(r.message || 'Meta rechazó la validación.');
                } else {
                    // Modal "OK" reutilizado — además agregamos extras (limit tier, última sync)
                    valRenderOk({
                        waba_name: nombre,
                        verified_name: r.verified_name,
                        display_phone_number: r.display_phone_number,
                        quality_rating: r.quality_rating,
                    }, 'revalidar');
                    // Inyectar info extra abajo
                    var body = document.getElementById('man-val-body');
                    if (body && (r.messaging_limit_tier || r.ultima_sincronizacion)) {
                        var extras = [];
                        if (r.messaging_limit_tier) extras.push('<b>Tier mensajería:</b> ' + r.messaging_limit_tier);
                        if (r.ultima_sincronizacion) {
                            var fecha = new Date(r.ultima_sincronizacion).toLocaleString();
                            extras.push('<b>Última sync:</b> ' + fecha);
                        }
                        if (extras.length) {
                            var div = document.createElement('div');
                            div.className = 'man-val-hint';
                            div.style.background = '#eff6ff';
                            div.style.borderColor = '#bfdbfe';
                            div.style.color = '#1e3a8a';
                            div.innerHTML = '<i class="fa fa-info-circle" style="color:#2563eb"></i> ' + extras.join(' · ');
                            body.appendChild(div);
                        }
                    }
                }
            });
        } else if (action === 'validar-conexion') {
            abrirDetail('<div class="valcx-wrap"><div class="valcx-loading">' +
                '<i class="fa fa-spinner fa-spin"></i> Validando conexión con Meta...</div></div>');
            fetch('/whatsapp/sesiones/' + sesionId + '/validar-conexion/', {
                method: 'GET',
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!data.ok) {
                        abrirDetail('<div class="valcx-wrap"><div class="valcx-verdict is-bad">' +
                            '<i class="fa fa-circle-xmark"></i> ' + (data.error || 'No se pudo validar.') +
                            '</div></div>');
                        return;
                    }
                    abrirDetail(renderValidacionConexion(data));
                })
                .catch(function () {
                    abrirDetail('<div class="valcx-wrap"><div class="valcx-verdict is-bad">' +
                        '<i class="fa fa-circle-xmark"></i> Error de red al validar.</div></div>');
                });
        } else if (action === 'cambiar-nombre') {
            abrirDetail(renderCambiarNombre(nombre, card.getAttribute('data-meta-url') || ''));
            var cnBtn = document.getElementById('cn-enviar');
            var cnInput = document.getElementById('cn-input');
            var cnResult = document.getElementById('cn-result');
            if (cnInput) cnInput.focus();
            if (cnBtn) cnBtn.addEventListener('click', function () {
                if (cnBtn.disabled) return;
                var nuevo = (cnInput.value || '').trim();
                if (nuevo.length < 3) {
                    cnResult.hidden = false;
                    cnResult.className = 'valcx-verdict is-bad';
                    cnResult.innerHTML = '<i class="fa fa-circle-xmark"></i> El nombre debe tener al menos 3 caracteres.';
                    return;
                }
                var orig = cnBtn.innerHTML;
                cnBtn.disabled = true;
                cnBtn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Enviando a Meta...';
                cnResult.hidden = true;
                var csrf = document.querySelector('input[name=csrfmiddlewaretoken]');
                var fd = new FormData();
                fd.append('csrfmiddlewaretoken', csrf ? csrf.value : '');
                fd.append('nombre', nuevo);
                fetch('/whatsapp/sesiones/' + sesionId + '/cambiar-nombre/', {
                    method: 'POST',
                    body: fd,
                    headers: {'X-CSRFToken': csrf ? csrf.value : '', 'X-Requested-With': 'XMLHttpRequest'},
                    credentials: 'same-origin',
                })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        cnBtn.disabled = false;
                        cnBtn.innerHTML = orig;
                        var linkHtml = data.meta_url
                            ? '<br><br><a href="' + escaparHtml(data.meta_url) + '" target="_blank" rel="noopener" ' +
                              'class="conex-btn conex-btn-primary" style="text-decoration:none">' +
                              '<i class="fa fa-up-right-from-square"></i> Validar/ver estado en Meta</a>'
                            : '';
                        if (window.Swal && Swal.fire) {
                            Swal.fire({
                                type: data.ok ? 'success' : 'error',
                                title: data.ok ? 'Enviado a revisión de Meta' : 'No se pudo cambiar',
                                html: escaparHtml(data.ok ? data.message : (data.error || 'Error.')) + linkHtml,
                                confirmButtonText: 'Entendido',
                            });
                        } else {
                            cnResult.hidden = false;
                            cnResult.className = 'valcx-verdict ' + (data.ok ? 'is-ok' : 'is-bad');
                            cnResult.innerHTML = (data.ok ? '<i class="fa fa-circle-check"></i> ' : '<i class="fa fa-circle-xmark"></i> ') +
                                escaparHtml(data.ok ? data.message : (data.error || 'Error.')) + linkHtml;
                        }
                    })
                    .catch(function () {
                        cnBtn.disabled = false;
                        cnBtn.innerHTML = orig;
                        if (window.Swal && Swal.fire) {
                            Swal.fire({type: 'error', title: 'Error de red', confirmButtonText: 'Cerrar'});
                        } else {
                            cnResult.hidden = false;
                            cnResult.className = 'valcx-verdict is-bad';
                            cnResult.innerHTML = '<i class="fa fa-circle-xmark"></i> Error de red.';
                        }
                    });
            });
        } else if (action === 'datos-transporte') {
            fetchPartial('datos_transporte_modal', sesionId).then(function (r) {
                if (!r.ok) return mostrarToast(r.message || 'No se pudo abrir.', 'err');
                abrirDetail(r.html);
            });
        } else if (action === 'respuestas-rapidas') {
            fetchPartial('respuestas_rapidas_modal', sesionId).then(function (r) {
                if (!r.ok) return mostrarToast(r.message || 'No se pudo abrir.', 'err');
                abrirDetail(r.html);
            });
        } else if (action === 'menus-rapidos') {
            fetchPartial('menus_rapidos_modal', sesionId).then(function (r) {
                if (!r.ok) return mostrarToast(r.message || 'No se pudo abrir.', 'err');
                abrirDetail(r.html);
            });
        } else if (action === 'ads-config') {
            fetchPartial('ads_config_modal', sesionId).then(function (r) {
                if (!r.ok) return mostrarToast(r.message || 'No se pudo abrir.', 'err');
                abrirDetail(r.html);
            });
        } else if (action === 'test-eco') {
            abrirEco(sesionId, nombre, numero);
        } else if (action === 'cambiar-foto') {
            abrirCambiarFoto(sesionId, nombre);
        } else if (action === 'baileys-verificar') {
            postAccion({action: 'baileys_verificar', id: sesionId}).then(function (r) {
                if (r.error) return mostrarToast(r.message || 'No respondió.', 'err');
                mostrarToast(r.message, r.connected ? 'ok' : 'err');
                refrescarCard(sesionId);
            });
        } else if (action === 'baileys-reconnect') {
            baileysSesionId = sesionId;
            abrirModal('baileys');
            if (btnBaileysStart) btnBaileysStart.click();
        } else if (action === 'disconnect') {
            if (window.Swal) {
                Swal.fire({
                    title: '¿Desconectar ' + nombre + '?',
                    text: 'La sesión dejará de recibir y enviar mensajes hasta que la reconectes.',
                    type: 'warning', showCancelButton: true, allowOutsideClick: false,
                    confirmButtonText: 'Sí, desconectar', cancelButtonText: 'Cancelar',
                    confirmButtonColor: '#d97706',
                }).then(function (res) {
                    if (!res.value) return;
                    postAccion({action: 'disconnect', id: sesionId}).then(function (r) {
                        if (r.error) return mostrarToast(r.message, 'err');
                        mostrarToast('Sesión desconectada.', 'ok');
                        refrescarCard(sesionId);
                    });
                });
            }
        } else if (action === 'eliminar') {
            // Usa la función global del base.html — Swal + POST + reload.
            if (typeof window.eliminarajax === 'function') {
                window.eliminarajax(sesionId, nombre, 'delete');
            } else {
                mostrarToast('No se encontró el helper eliminarajax en base.html.', 'err');
            }
        }
    });

    // ---------- Submit form "Plantilla prueba" (en detail modal) ----------
    // El form #form-editar-sesion ahora lo maneja static/js/forms.js
    // (re-inyectado al cargar el partial). Acá solo dejamos los formularios
    // que NO siguen ese patrón estándar.
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (form.id === 'form-plantilla-prueba') {
            e.preventDefault();
            var fd2 = new FormData(form);
            var obj2 = {};
            fd2.forEach(function (v, k) {
                obj2[k] = v;
            });
            postAccion(obj2).then(function (r) {
                if (r.error) return mostrarToast(r.message, 'err');
                mostrarToast(r.message || 'Plantilla enviada.', 'ok');
                cerrarDetail();
            });
        }
    });

    window.marcarPresetMinSesion = function () {
        var inp = document.getElementById('inp-min-sesion');
        var box = document.getElementById('min-sesion-presets');
        if (!inp || !box) return;
        var val = String(inp.value || '').trim();
        box.querySelectorAll('button[data-min]').forEach(function (b) {
            var on = b.getAttribute('data-min') === val;
            b.classList.toggle('conex-btn-primary', on);
            b.classList.toggle('conex-btn-light', !on);
        });
    };

    window.setMinSesion = function (v) {
        var inp = document.getElementById('inp-min-sesion');
        if (!inp) return;
        inp.value = v;
        window.marcarPresetMinSesion();
    };

})();
