(function () {
    const modalEl = document.getElementById('modalSecuencia');
    const modal = new bootstrap.Modal(modalEl);
    const form = document.getElementById('formSecuencia');
    const contenedorPasos = document.getElementById('contenedorPasos');
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;

    function filaPaso(paso) {
        const div = document.createElement('div');
        div.className = 'seq-paso-row';
        div.dataset.pasoId = paso && paso.id ? paso.id : '';
        div.innerHTML = `
            <div class="row g-2 align-items-start">
                <div class="col-auto pt-1">
                    <span class="seq-paso-num"></span>
                </div>
                <div class="col-md-3">
                    <label class="form-label mb-1"><small>Espera (horas)</small></label>
                    <input type="number" class="form-control form-control-sm paso-espera" min="1"
                           value="${paso ? paso.espera_horas : 24}">
                </div>
                <div class="col">
                    <label class="form-label mb-1"><small>Mensaje</small></label>
                    <textarea class="form-control form-control-sm paso-mensaje" rows="2"
                              placeholder="Texto que recibirá el contacto"></textarea>
                </div>
                <div class="col-auto pt-4">
                    <button type="button" class="btn btn-sm btn-danger btn-quitar-paso">
                        <i class="fa fa-times"></i>
                    </button>
                </div>
            </div>`;
        div.querySelector('.paso-mensaje').value = paso ? paso.mensaje : '';
        div.querySelector('.btn-quitar-paso').addEventListener('click', () => {
            div.remove();
            renumerar();
        });
        return div;
    }

    function renumerar() {
        contenedorPasos.querySelectorAll('.seq-paso-num').forEach((el, idx) => {
            el.textContent = idx + 1;
        });
    }

    function agregarPaso(paso) {
        contenedorPasos.appendChild(filaPaso(paso));
        renumerar();
    }

    document.getElementById('btnAgregarPaso').addEventListener('click', () => agregarPaso(null));

    function serializarPasos() {
        const pasos = [];
        contenedorPasos.querySelectorAll('.seq-paso-row').forEach((row) => {
            pasos.push({
                id: row.dataset.pasoId || null,
                espera_horas: row.querySelector('.paso-espera').value,
                mensaje: row.querySelector('.paso-mensaje').value.trim(),
            });
        });
        return pasos;
    }

    document.querySelectorAll('.btn-edit').forEach(btn => btn.addEventListener('click', async () => {
        form.reset();
        contenedorPasos.innerHTML = '';
        form.action.value = 'change';
        form.pk.value = btn.dataset.id;
        form.nombre.value = btn.dataset.nombre;
        form.descripcion.value = btn.dataset.desc;
        form.etiqueta_disparadora.value = btn.dataset.etiqueta;
        form.querySelector('#chkActiva').checked = btn.dataset.activa === '1';
        form.querySelector('#chkSalir').checked = btn.dataset.salir === '1';
        modalEl.querySelector('.modal-title').textContent = 'Editar secuencia';
        const r = await fetch(`?action=pasos&id=${btn.dataset.id}`);
        const j = await r.json();
        (j.pasos || []).forEach(p => agregarPaso(p));
        if (!j.pasos || !j.pasos.length) agregarPaso(null);
        modal.show();
    }));

    modalEl.addEventListener('show.bs.modal', (e) => {
        if (!e.relatedTarget) return;
        form.reset();
        contenedorPasos.innerHTML = '';
        form.action.value = 'add';
        form.pk.value = '';
        form.querySelector('#chkActiva').checked = true;
        form.querySelector('#chkSalir').checked = true;
        modalEl.querySelector('.modal-title').textContent = 'Nueva secuencia';
        agregarPaso(null);
    });

    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        form.pasos_json.value = JSON.stringify(serializarPasos());
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
        if (!confirm(`¿Eliminar la secuencia "${btn.dataset.nombre}"? Las inscripciones activas se cancelarán.`)) return;
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

    const modalInscribirEl = document.getElementById('modalInscribir');
    const modalInscribir = new bootstrap.Modal(modalInscribirEl);
    const inputBuscar = document.getElementById('inputBuscarContacto');
    const resultados = document.getElementById('resultadosContacto');
    let timerBusqueda = null;

    document.querySelectorAll('.btn-inscribir').forEach(btn => btn.addEventListener('click', () => {
        document.getElementById('inscribirSecuenciaId').value = btn.dataset.id;
        modalInscribirEl.querySelector('.modal-title').textContent = `Inscribir contacto — ${btn.dataset.nombre}`;
        inputBuscar.value = '';
        resultados.innerHTML = '';
        modalInscribir.show();
    }));

    document.getElementById('btnInscribirSegmento').addEventListener('click', async () => {
        const segmentoId = document.getElementById('selectSegmentoInscribir').value;
        if (!segmentoId) {
            alert('Elige un segmento primero.');
            return;
        }
        const fd = new FormData();
        fd.append('action', 'inscribir_segmento');
        fd.append('secuencia_id', document.getElementById('inscribirSecuenciaId').value);
        fd.append('segmento_id', segmentoId);
        fd.append('csrfmiddlewaretoken', csrf);
        const r = await fetch('', {method: 'POST', body: fd});
        const j = await r.json();
        alert(j.message || (j.error ? 'Error' : 'Listo'));
        if (!j.error) modalInscribir.hide();
    });

    inputBuscar.addEventListener('input', () => {
        clearTimeout(timerBusqueda);
        timerBusqueda = setTimeout(async () => {
            const criterio = inputBuscar.value.trim();
            if (criterio.length < 3) {
                resultados.innerHTML = '';
                return;
            }
            const r = await fetch(`?action=buscar_contactos&criterio=${encodeURIComponent(criterio)}`);
            const j = await r.json();
            resultados.innerHTML = '';
            (j.contactos || []).forEach(c => {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'list-group-item list-group-item-action';
                item.innerHTML = `<strong>${c.nombre}</strong> · ${c.numero} <small class="text-muted">(${c.sesion})</small>`;
                item.addEventListener('click', async () => {
                    const fd = new FormData();
                    fd.append('action', 'inscribir');
                    fd.append('secuencia_id', document.getElementById('inscribirSecuenciaId').value);
                    fd.append('contacto_id', c.id);
                    fd.append('csrfmiddlewaretoken', csrf);
                    const resp = await fetch('', {method: 'POST', body: fd});
                    const jr = await resp.json();
                    alert(jr.message || (jr.error ? 'Error' : 'Inscrito'));
                    if (!jr.error) modalInscribir.hide();
                });
                resultados.appendChild(item);
            });
            if (!(j.contactos || []).length) {
                resultados.innerHTML = '<div class="list-group-item text-muted">Sin resultados</div>';
            }
        }, 350);
    });

    const modalInscripcionesEl = document.getElementById('modalInscripciones');
    const modalInscripciones = new bootstrap.Modal(modalInscripcionesEl);
    const tbody = document.getElementById('tbodyInscripciones');

    function badgeEstado(code, texto) {
        let cls = 'seq-badge-estado-otro';
        if (code === 'activa') cls = 'seq-badge-estado-activa';
        else if (code === 'completada') cls = 'seq-badge-estado-completada';
        else if (code === 'error') cls = 'seq-badge-estado-error';
        return `<span class="badge ${cls}">${texto}</span>`;
    }

    document.querySelectorAll('.btn-inscripciones').forEach(btn => btn.addEventListener('click', async () => {
        modalInscripcionesEl.querySelector('.modal-title').textContent = `Inscripciones — ${btn.dataset.nombre}`;
        tbody.innerHTML = '<tr><td colspan="6" class="text-muted">Cargando…</td></tr>';
        modalInscripciones.show();
        const r = await fetch(`?action=inscripciones&id=${btn.dataset.id}`);
        const j = await r.json();
        tbody.innerHTML = '';
        (j.inscripciones || []).forEach(i => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${i.contacto}</td>
                <td>${i.numero}</td>
                <td>${badgeEstado(i.estado_code, i.estado)}</td>
                <td>${i.paso_actual}</td>
                <td>${i.proximo_envio}</td>
                <td></td>`;
            if (i.estado_code === 'activa') {
                const b = document.createElement('button');
                b.className = 'btn btn-sm btn-danger';
                b.innerHTML = '<i class="fa fa-ban"></i>';
                b.title = 'Cancelar inscripción';
                b.addEventListener('click', async () => {
                    if (!confirm(`¿Cancelar la inscripción de ${i.contacto}?`)) return;
                    const fd = new FormData();
                    fd.append('action', 'cancelar_inscripcion');
                    fd.append('id', i.id);
                    fd.append('csrfmiddlewaretoken', csrf);
                    const resp = await fetch('', {method: 'POST', body: fd});
                    const jr = await resp.json();
                    if (!jr.error) tr.remove(); else alert(jr.message || 'Error');
                });
                tr.lastElementChild.appendChild(b);
            }
            tbody.appendChild(tr);
        });
        if (!(j.inscripciones || []).length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-muted">Sin inscripciones todavía</td></tr>';
        }
    }));
})();
