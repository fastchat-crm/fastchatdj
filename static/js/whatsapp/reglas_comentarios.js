(function () {
    const modalEl = document.getElementById('modalRegla');
    const modal = new bootstrap.Modal(modalEl);
    const form = document.getElementById('formRegla');
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;

    document.querySelectorAll('.btn-edit').forEach(btn => btn.addEventListener('click', () => {
        form.reset();
        form.action.value = 'change';
        form.pk.value = btn.dataset.id;
        form.nombre.value = btn.dataset.nombre;
        form.keywords.value = btn.dataset.keywords;
        form.media_id.value = btn.dataset.media;
        form.respuesta_publica.value = btn.dataset.publica;
        form.mensaje_dm.value = btn.dataset.dm;
        form.etiqueta_id.value = btn.dataset.etiqueta;
        form.sesion_id.value = btn.dataset.sesion;
        form.sesion_id.disabled = true;
        form.orden.value = btn.dataset.orden;
        form.querySelector('#chkReglaActiva').checked = btn.dataset.activa === '1';
        modalEl.querySelector('.modal-title').textContent = 'Editar regla';
        modal.show();
    }));

    modalEl.addEventListener('show.bs.modal', (e) => {
        if (!e.relatedTarget) return;
        form.reset();
        form.action.value = 'add';
        form.pk.value = '';
        form.sesion_id.disabled = false;
        form.querySelector('#chkReglaActiva').checked = true;
        modalEl.querySelector('.modal-title').textContent = 'Nueva regla';
    });

    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        form.sesion_id.disabled = false;
        const fd = new FormData(form);
        const r = await fetch('', {method: 'POST', body: fd, headers: {'X-Requested-With': 'XMLHttpRequest'}});
        const j = await r.json();
        if (j.error) {
            alert(j.message || 'Error');
            return;
        }
        if (j.reload) location.reload();
    });

    document.querySelectorAll('.btn-del').forEach(btn => btn.addEventListener('click', async () => {
        if (!confirm(`¿Eliminar la regla "${btn.dataset.nombre}"?`)) return;
        const fd = new FormData();
        fd.append('action', 'delete');
        fd.append('id', btn.dataset.id);
        fd.append('csrfmiddlewaretoken', csrf);
        const r = await fetch('', {method: 'POST', body: fd});
        const j = await r.json();
        if (!j.error) location.reload(); else alert(j.message || 'Error');
    }));

    document.querySelectorAll('.btn-toggle').forEach(btn => btn.addEventListener('click', async () => {
        const fd = new FormData();
        fd.append('action', 'toggle_activa');
        fd.append('id', btn.dataset.id);
        fd.append('csrfmiddlewaretoken', csrf);
        const r = await fetch('', {method: 'POST', body: fd});
        const j = await r.json();
        if (!j.error) location.reload(); else alert(j.message || 'Error');
    }));
})();
