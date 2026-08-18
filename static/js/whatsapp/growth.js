(function () {
    const modalEl = document.getElementById('modalEnlace');
    const modal = new bootstrap.Modal(modalEl);
    const form = document.getElementById('formEnlace');
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;

    document.querySelectorAll('.btn-copiar').forEach(btn => btn.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(btn.dataset.url);
            btn.innerHTML = '<i class="fa fa-check"></i>';
            setTimeout(() => { btn.innerHTML = '<i class="fa fa-copy"></i>'; }, 1500);
        } catch (e) {
            prompt('Copia el link:', btn.dataset.url);
        }
    }));

    const modalQrEl = document.getElementById('modalQr');
    const modalQr = new bootstrap.Modal(modalQrEl);
    document.querySelectorAll('.btn-qr').forEach(btn => btn.addEventListener('click', () => {
        const urlQr = `https://api.qrserver.com/v1/create-qr-code/?size=440x440&data=${encodeURIComponent(btn.dataset.url)}`;
        document.getElementById('imgQr').src = urlQr;
        document.getElementById('linkDescargarQr').href = urlQr.replace('440x440', '1000x1000');
        modalQrEl.querySelector('.modal-title').textContent = `QR — ${btn.dataset.nombre}`;
        modalQr.show();
    }));

    document.querySelectorAll('.btn-edit').forEach(btn => btn.addEventListener('click', () => {
        form.reset();
        form.action.value = 'change';
        form.pk.value = btn.dataset.id;
        form.nombre.value = btn.dataset.nombre;
        form.descripcion.value = btn.dataset.desc;
        form.texto_prellenado.value = btn.dataset.texto;
        form.mensaje_respuesta.value = btn.dataset.respuesta;
        form.etiqueta_id.value = btn.dataset.etiqueta;
        form.secuencia_id.value = btn.dataset.secuencia;
        form.sesion_id.value = btn.dataset.sesion;
        form.sesion_id.disabled = true;
        form.querySelector('#chkEnlaceActivo').checked = btn.dataset.activo === '1';
        modalEl.querySelector('.modal-title').textContent = 'Editar enlace';
        modal.show();
    }));

    modalEl.addEventListener('show.bs.modal', (e) => {
        if (!e.relatedTarget) return;
        form.reset();
        form.action.value = 'add';
        form.pk.value = '';
        form.sesion_id.disabled = false;
        form.querySelector('#chkEnlaceActivo').checked = true;
        modalEl.querySelector('.modal-title').textContent = 'Nuevo enlace';
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
        if (!confirm(`¿Eliminar el enlace "${btn.dataset.nombre}"?`)) return;
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
        fd.append('action', 'toggle_activo');
        fd.append('id', btn.dataset.id);
        fd.append('csrfmiddlewaretoken', csrf);
        const r = await fetch('', {method: 'POST', body: fd});
        const j = await r.json();
        if (!j.error) location.reload(); else alert(j.message || 'Error');
    }));
})();
