/**
 * errors_meta.js — helper unificado para mostrar errores Meta con hint + CTA.
 *
 * Cualquier endpoint Meta (verify, register, send template, etc.) devuelve
 * shape:
 *   {
 *     error: true,
 *     message: "texto plano + ' Hint: ...' opcional",
 *     hint: "como resolverlo",
 *     hint_link: "https://...",
 *     hint_link_label: "Abrir...",
 *     raw: "JSON crudo de Meta"
 *   }
 *
 * Llamar:
 *   mostrarError("Validacion fallo", r);
 *
 * Si no hay Swal disponible, cae a window.alert. Si Swal v2 (con `type:`) o
 * v9+ (con `icon:`) detecta automaticamente.
 */
(function (global) {
    'use strict';

    function _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function _swalConfig(titulo, html) {
        // Compat Swal v2 + v9+
        var cfg = {
            title: titulo,
            html: html,
            showConfirmButton: true,
            confirmButtonText: 'Entendido',
            width: 620,
        };
        if (typeof Swal === 'undefined') return null;
        // v9+ usa icon, v2 usa type. Mandamos los 2 para robustez.
        cfg.icon = 'error';
        cfg.type = 'error';
        return cfg;
    }

    /**
     * @param {string} titulo  Titulo del modal/alert.
     * @param {object} r       Respuesta JSON del backend con error/message/hint/raw.
     */
    function mostrarError(titulo, r) {
        r = r || {};
        var msg = String(r.message || 'Error desconocido').split(' Hint:')[0];
        var hint = r.hint ? String(r.hint).replace(/^ *Hint: */, '') : '';
        var raw = r.raw ? String(r.raw) : '';
        var ctaHtml = r.hint_link
            ? '<a href="' + _esc(r.hint_link) + '" target="_blank" rel="noopener" class="btn btn-sm btn-warning mt-2">' +
                '<i class="fa fa-external-link-alt me-1"></i>' + _esc(r.hint_link_label || 'Abrir') +
              '</a>'
            : '';
        var html = '' +
            '<div class="text-start">' +
                '<div class="alert alert-danger py-2 mb-2 small">' + _esc(msg) + '</div>' +
                ((hint || ctaHtml)
                    ? '<div class="alert alert-warning py-2 mb-2 small">' +
                          '<i class="fa fa-lightbulb me-1"></i><strong>Como resolverlo:</strong>' +
                          (hint ? '<div class="mt-1">' + _esc(hint) + '</div>' : '') +
                          ctaHtml +
                      '</div>'
                    : '') +
                (raw
                    ? '<details class="small"><summary class="text-muted" style="cursor:pointer">Ver respuesta cruda</summary>' +
                          '<pre class="bg-light border rounded p-2 small mt-1" style="white-space:pre-wrap;word-break:break-all;max-height:180px;overflow:auto;">' +
                              _esc(raw) +
                          '</pre>' +
                      '</details>'
                    : '') +
            '</div>';
        var cfg = _swalConfig(titulo, html);
        if (cfg) {
            try { Swal.fire(cfg); return; } catch (e) { /* fallthrough */ }
        }
        window.alert(titulo + '\n\n' + msg + (hint ? '\n\n' + hint : ''));
    }

    /**
     * Helper para AJAX: si la respuesta tiene error true, muestra modal.
     * Si es OK ejecuta `onOk(r)`. Devuelve la promesa de $.post.
     */
    function postWithError(url, datos, onOk, titulo) {
        return $.post(url, datos)
            .done(function (r) {
                if (r && r.error === false) {
                    if (onOk) onOk(r);
                } else {
                    mostrarError(titulo || 'Error', r);
                }
            })
            .fail(function () {
                mostrarError(titulo || 'Error', { message: 'Error de conexion con el servidor.' });
            });
    }

    global.mostrarError = mostrarError;
    global.postWithError = postWithError;
    // Compat: las views Meta llaman mostrarErrorMeta — alias al nuevo helper
    if (!global.mostrarErrorMeta) global.mostrarErrorMeta = mostrarError;
})(window);
