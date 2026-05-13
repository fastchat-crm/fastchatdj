(function() {
    let _historialCache = null;
    let _activeConvId = null;

    function rutaActual() {
        return window.location.pathname;
    }

    function escHtml(s) {
        return (s == null ? '' : String(s))
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    window.cargarHistorialCliente = function(conversacionId) {
        _activeConvId = parseInt(conversacionId, 10) || null;
        _historialCache = null;
        $('#historial-chips').addClass('d-none').empty();
        if (!_activeConvId) return;
        $.ajax({
            url: rutaActual() + '?action=historial_cliente&pk=' + _activeConvId,
            type: 'GET',
            success: function(r) {
                if (!r || r.error) return;
                _historialCache = r;
                if (r.conversaciones && r.conversaciones.length > 1) {
                    renderChips(r.conversaciones);
                }
            }
        });
    };

    window.resetHistorialCliente = function() {
        _activeConvId = null;
        _historialCache = null;
        $('#historial-chips').addClass('d-none').empty();
    };

    function renderChips(items) {
        const $strip = $('#historial-chips');
        $strip.empty();
        items.forEach(function(c) {
            const cls = c.es_actual ? 'is-current' : (c.finalizada ? 'is-ended' : 'is-active');
            const icon = c.finalizada ? 'fa-check-circle' : 'fa-circle-dot';
            let label = c.fecha_inicio_corta || '';
            if (c.total_mensajes) label += ' · ' + c.total_mensajes;
            $strip.append(
                '<button type="button" class="hc-chip ' + cls + '" data-id="' + c.id + '" title="' + escHtml(c.fecha_inicio) + '">' +
                '<i class="fa ' + icon + ' me-1"></i>' + escHtml(label) + '</button>'
            );
        });
        $strip.removeClass('d-none');
    }

    function abrirModal(focusConvId) {
        const id = parseInt(focusConvId, 10) || _activeConvId;
        if (!_historialCache) {
            if (!id) return;
            $.ajax({
                url: rutaActual() + '?action=historial_cliente&pk=' + id,
                type: 'GET',
                success: function(r) {
                    if (!r || r.error) return;
                    _historialCache = r;
                    abrirModalInterno(id);
                }
            });
            return;
        }
        abrirModalInterno(id);
    }

    function abrirModalInterno(focusConvId) {
        if (!_historialCache) return;
        $('#hc-contact-name').text(_historialCache.contacto_nombre || '');
        $('#hc-contact-sub').text(_historialCache.contacto_numero || '');
        $('#hc-total').text((_historialCache.conversaciones || []).length + ' conversations');
        renderListaModal(_historialCache.conversaciones, focusConvId);
        const el = document.getElementById('modalHistorialCliente');
        const inst = bootstrap.Modal.getInstance(el) || new bootstrap.Modal(el);
        inst.show();
        if (focusConvId) cargarMensajesHistorial(focusConvId);
    }

    function renderListaModal(items, activoId) {
        const $list = $('#hc-list');
        $list.empty();
        if (!items || !items.length) {
            $list.html('<div class="hc-empty"><i class="fa fa-folder-open d-block"></i>No history</div>');
            return;
        }
        items.forEach(function(c) {
            let cls = '';
            if (c.id === activoId) cls += 'active ';
            if (c.es_actual) cls += 'is-current ';
            const stateIcon = c.finalizada ? 'fa-check-circle text-success' : 'fa-circle-dot text-primary';
            const stateLabel = c.finalizada ? 'Finalized' : 'Active';
            const currentBadge = c.es_actual ? '<span class="hc-li-badge">Current</span>' : '';
            const clasBadge = c.clasificacion ? '<span class="hc-li-clas">' + escHtml(c.clasificacion) + '</span>' : '';
            const msgs = c.total_mensajes ? '<div class="hc-li-msgs"><i class="fa fa-comments me-1"></i>' + c.total_mensajes + ' messages</div>' : '';
            $list.append(
                '<button type="button" class="hc-list-item ' + cls.trim() + '" data-id="' + c.id + '">' +
                  '<div class="hc-li-date">' + escHtml(c.fecha_inicio) + '</div>' +
                  '<div class="hc-li-meta">' +
                    '<span class="hc-li-state"><i class="fa ' + stateIcon + ' me-1"></i>' + stateLabel + '</span>' +
                    currentBadge + clasBadge +
                  '</div>' +
                  msgs +
                '</button>'
            );
        });
    }

    function cargarMensajesHistorial(convId) {
        const id = parseInt(convId, 10);
        if (!id) return;
        $('#hc-messages-container').html('<div class="hc-empty"><i class="fa fa-spinner fa-spin d-block"></i>Loading messages...</div>');
        $('#hc-meta-line').text('');
        $('#hc-resumen').addClass('d-none').empty();
        $('.hc-list-item').removeClass('active');
        $('.hc-list-item[data-id="' + id + '"]').addClass('active');
        $.ajax({
            url: rutaActual() + '?action=historial_mensajes&pk=' + id,
            type: 'GET',
            success: function(r) {
                if (!r || r.error) {
                    $('#hc-messages-container').html('<div class="hc-empty text-danger"><i class="fa fa-exclamation-circle d-block"></i>' + escHtml((r && r.message) || 'Error') + '</div>');
                    return;
                }
                $('#hc-messages-container').html(r.html || '<div class="hc-empty">No messages</div>');
                let meta = '';
                if (r.fecha_inicio) meta += '<i class="fa fa-calendar me-1"></i>' + escHtml(r.fecha_inicio);
                if (r.fecha_fin) meta += ' &rarr; ' + escHtml(r.fecha_fin);
                meta += ' &middot; <i class="fa fa-comments me-1"></i>' + (r.total_mensajes || 0) + ' messages';
                meta += ' &middot; ' + (r.finalizada
                    ? '<span class="text-success"><i class="fa fa-check-circle me-1"></i>Finalized</span>'
                    : '<span class="text-primary"><i class="fa fa-circle-dot me-1"></i>Active</span>');
                if (r.clasificacion) meta += ' &middot; <span class="hc-li-clas">' + escHtml(r.clasificacion) + '</span>';
                $('#hc-meta-line').html(meta);
                if (r.resumen) {
                    $('#hc-resumen').removeClass('d-none').html('<i class="fa fa-lightbulb me-1"></i><b>Summary:</b> ' + escHtml(r.resumen));
                }
                const wrap = document.getElementById('hc-messages-wrap');
                if (wrap) wrap.scrollTop = wrap.scrollHeight;
            },
            error: function() {
                $('#hc-messages-container').html('<div class="hc-empty text-danger"><i class="fa fa-exclamation-circle d-block"></i>Network error</div>');
            }
        });
    }

    $(document).on('click', '#ver-historial-cliente', function(e) {
        e.preventDefault();
        abrirModal(_activeConvId);
    });

    $(document).on('click', '.hc-chip', function() {
        const id = parseInt($(this).data('id'), 10);
        abrirModal(id);
    });

    $(document).on('click', '.hc-list-item', function() {
        const id = parseInt($(this).data('id'), 10);
        cargarMensajesHistorial(id);
    });
})();
