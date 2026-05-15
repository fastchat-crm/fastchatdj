function _agendaConfig() {
    const el = document.querySelector('[data-agenda-cfg]');
    const ruta = (el && el.dataset.ruta) ? el.dataset.ruta : window.location.pathname;
    const grupoId = (el && el.dataset.grupoId) ? el.dataset.grupoId : '';
    let csrf = (el && el.dataset.csrf) ? el.dataset.csrf : '';
    if (!csrf) {
        const inp = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (inp) csrf = inp.value;
    }
    return {ruta: ruta, csrf: csrf, grupoId: grupoId};
}

function formModalAgenda(entity, id, text, action) {
    const cfg = _agendaConfig();
    pantallaespera();
    const params = {entity: entity, action: action, id: id};
    if (cfg.grupoId) params.grupo_id = cfg.grupoId;
    $.ajax({
        type: 'GET',
        url: cfg.ruta,
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
}

function eliminarAgenda(entity, pk, nombre) {
    const cfg = _agendaConfig();
    Swal.fire({
        title: 'Estas a punto de eliminar este registro ' + nombre,
        text: 'Esta acción es irreversible',
        type: 'warning',
        showCancelButton: true,
        allowOutsideClick: false,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#d33',
        confirmButtonText: 'Sí, deseo hacerlo!',
        cancelButtonText: 'Cancelar'
    }).then(function (result) {
        if (!result.value) return;
        pantallaespera();
        $.post(cfg.ruta, {
            entity: entity, action: 'delete', id: pk,
            csrfmiddlewaretoken: cfg.csrf
        }, function (data) {
            $.unblockUI();
            const r = Array.isArray(data) ? data[0] : data;
            if (!r.error) {
                location.reload();
            } else {
                Swal.fire(r.message || 'Error', '', 'error');
            }
        }, 'json');
    });
}

function postAgendaEntity(payload) {
    const cfg = _agendaConfig();
    const fd = new FormData();
    Object.entries(payload).forEach(function (kv) { fd.append(kv[0], kv[1]); });
    fd.append('csrfmiddlewaretoken', cfg.csrf);
    return fetch(cfg.ruta, {method: 'POST', body: fd}).then(function (r) { return r.json(); });
}

(function () {
    const recursosBody = document.getElementById('recursosBody');
    if (recursosBody && window.Sortable) {
        Sortable.create(recursosBody, {
            handle: '.drag-handle', animation: 150,
            onEnd: async function () {
                const ids = Array.from(recursosBody.querySelectorAll('tr[data-id]')).map(function (tr) { return tr.dataset.id; });
                const j = await postAgendaEntity({entity: 'recurso', action: 'reorder', ids: ids.join(',')});
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
                const j = await postAgendaEntity({entity: 'servicio', action: 'reorder', ids: ids.join(',')});
                const r = Array.isArray(j) ? j[0] : j;
                if (r.error) Swal.fire(r.message || 'Falló el reordenamiento', '', 'error');
            }
        });
    }
})();
