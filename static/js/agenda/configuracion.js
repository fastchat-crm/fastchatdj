(function () {
    const cfgEl = document.querySelector('[data-agenda-cfg]');
    if (!cfgEl) return;
    const RUTA_AGENDA = cfgEl.dataset.ruta;
    const CSRF_AGENDA = cfgEl.dataset.csrf;
    const GRUPO_ID = cfgEl.dataset.grupoId || '';

    window.formModalAgenda = function (entity, id, text, action) {
        pantallaespera();
        const params = {entity: entity, action: action, id: id};
        if (GRUPO_ID) params.grupo_id = GRUPO_ID;
        $.ajax({
            type: 'GET',
            url: RUTA_AGENDA,
            data: params,
            dataType: 'json',
            success: function (data) {
                setTimeout($.unblockUI, 1);
                if (data.result === true) {
                    $('#modalAgendaNombre').html(text);
                    $('.detalleAgenda').html(data.data);
                    const modal = new bootstrap.Modal(document.getElementById('modalAgenda'));
                    modal.show();
                } else {
                    Swal.fire(data.message || 'Error', '', 'error');
                }
            },
            error: function () {
                setTimeout($.unblockUI, 1);
                Swal.fire('Error de conexión.', '', 'error');
            }
        });
    };

    window.eliminarAgenda = function (entity, pk, nombre) {
        Swal.fire({
            title: '¿Eliminar "' + nombre + '"?',
            text: 'Esta acción es irreversible.',
            type: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#3085d6',
            cancelButtonColor: '#d33',
            confirmButtonText: 'Sí, eliminar',
            cancelButtonText: 'Cancelar'
        }).then(function (result) {
            if (!result.value) return;
            pantallaespera();
            $.post(RUTA_AGENDA,
                {entity: entity, action: 'delete', id: pk, csrfmiddlewaretoken: CSRF_AGENDA},
                function (data) {
                    $.unblockUI();
                    const r = Array.isArray(data) ? data[0] : data;
                    if (!r.error) {
                        location.reload();
                    } else {
                        Swal.fire(r.message || 'Error', '', 'error');
                    }
                }, 'json');
        });
    };

    window.postAgendaEntity = function (payload) {
        const fd = new FormData();
        Object.entries(payload).forEach(function (kv) { fd.append(kv[0], kv[1]); });
        fd.append('csrfmiddlewaretoken', CSRF_AGENDA);
        return fetch(RUTA_AGENDA, {method: 'POST', body: fd}).then(function (r) { return r.json(); });
    };

    const recursosBody = document.getElementById('recursosBody');
    if (recursosBody && window.Sortable) {
        Sortable.create(recursosBody, {
            handle: '.drag-handle', animation: 150,
            onEnd: async function () {
                const ids = Array.from(recursosBody.querySelectorAll('tr[data-id]')).map(function (tr) { return tr.dataset.id; });
                const j = await window.postAgendaEntity({entity: 'recurso', action: 'reorder', ids: ids.join(',')});
                const r = Array.isArray(j) ? j[0] : j;
                if (r.error) Swal.fire(r.message || 'Falló el reordenamiento', '', 'error');
            }
        });
    }

    const serviciosBody = document.getElementById('serviciosBody');
    if (serviciosBody && window.Sortable) {
        Sortable.create(serviciosBody, {
            handle: '.drag-handle', animation: 150,
            onEnd: async function () {
                const ids = Array.from(serviciosBody.querySelectorAll('tr[data-id]')).map(function (tr) { return tr.dataset.id; });
                const j = await window.postAgendaEntity({entity: 'servicio', action: 'reorder', ids: ids.join(',')});
                const r = Array.isArray(j) ? j[0] : j;
                if (r.error) Swal.fire(r.message || 'Falló el reordenamiento', '', 'error');
            }
        });
    }
})();
