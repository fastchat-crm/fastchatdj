(function () {
    const modalEl = document.getElementById('modalSegmento');
    const modal = new bootstrap.Modal(modalEl);
    const form = document.getElementById('formSegmento');
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
    const contenedorReglas = document.getElementById('contenedorReglas');
    const tplRegla = document.getElementById('tplRegla');
    const previewBox = document.getElementById('previewBox');

    function agregarRegla(regla) {
        const nodo = tplRegla.content.firstElementChild.cloneNode(true);
        if (regla) {
            nodo.querySelector('.regla-campo').value = regla.campo_id;
            nodo.querySelector('.regla-operador').value = regla.operador || 'igual';
            nodo.querySelector('.regla-valor').value = regla.valor || '';
        }
        const sincronizarValor = () => {
            const op = nodo.querySelector('.regla-operador').value;
            nodo.querySelector('.regla-valor').disabled = (op === 'vacio' || op === 'no_vacio');
        };
        nodo.querySelector('.regla-operador').addEventListener('change', sincronizarValor);
        sincronizarValor();
        nodo.querySelector('.btn-quitar-regla').addEventListener('click', () => nodo.remove());
        contenedorReglas.appendChild(nodo);
    }

    document.getElementById('btnAgregarRegla').addEventListener('click', () => agregarRegla(null));

    function seleccionar(select, valores) {
        const set = new Set((valores || []).map(String));
        Array.from(select.options).forEach(o => { o.selected = set.has(o.value); });
    }

    function valoresSeleccionados(select) {
        return Array.from(select.selectedOptions).map(o => parseInt(o.value, 10));
    }

    function serializarCondiciones() {
        const cond = {};
        const etIn = valoresSeleccionados(document.getElementById('segEtiquetasIn'));
        const etOut = valoresSeleccionados(document.getElementById('segEtiquetasOut'));
        if (etIn.length) {
            cond.etiquetas_incluir = etIn;
            cond.modo_etiquetas = form.querySelector('[name=modo_etiquetas]:checked').value;
        }
        if (etOut.length) cond.etiquetas_excluir = etOut;
        const canales = Array.from(document.querySelectorAll('.seg-canal:checked')).map(c => c.value);
        if (canales.length) cond.canales = canales;
        const campos = [];
        contenedorReglas.querySelectorAll('.seg-regla-campo').forEach(row => {
            campos.push({
                campo_id: parseInt(row.querySelector('.regla-campo').value, 10),
                operador: row.querySelector('.regla-operador').value,
                valor: row.querySelector('.regla-valor').value.trim(),
            });
        });
        if (campos.length) cond.campos = campos;
        const tipoAct = document.getElementById('segActividadTipo').value;
        if (tipoAct) {
            cond.actividad = {
                tipo: tipoAct,
                dias: parseInt(document.getElementById('segActividadDias').value, 10) || 0,
            };
        }
        return cond;
    }

    function cargarCondiciones(cond) {
        cond = cond || {};
        seleccionar(document.getElementById('segEtiquetasIn'), cond.etiquetas_incluir);
        seleccionar(document.getElementById('segEtiquetasOut'), cond.etiquetas_excluir);
        const modo = cond.modo_etiquetas === 'all' ? 'all' : 'any';
        form.querySelector(`[name=modo_etiquetas][value=${modo}]`).checked = true;
        const canales = new Set(cond.canales || []);
        document.querySelectorAll('.seg-canal').forEach(c => { c.checked = canales.has(c.value); });
        contenedorReglas.innerHTML = '';
        (cond.campos || []).forEach(r => agregarRegla(r));
        const act = cond.actividad || {};
        document.getElementById('segActividadTipo').value = act.tipo || '';
        document.getElementById('segActividadDias').value = act.dias || 30;
        previewBox.innerHTML = '<small class="text-muted">Pulsa "Calcular audiencia" para ver cuántos contactos cumplen las condiciones.</small>';
    }

    document.getElementById('btnPreview').addEventListener('click', async () => {
        previewBox.innerHTML = '<small class="text-muted">Calculando…</small>';
        const fd = new FormData();
        fd.append('action', 'preview');
        fd.append('condiciones_json', JSON.stringify(serializarCondiciones()));
        fd.append('csrfmiddlewaretoken', csrf);
        const r = await fetch('', {method: 'POST', body: fd});
        const j = await r.json();
        if (j.error) {
            previewBox.innerHTML = `<span class="text-danger">${j.message || 'Error'}</span>`;
            return;
        }
        let html = `<strong>${j.total}</strong> contacto${j.total === 1 ? '' : 's'} cumplen las condiciones.`;
        if ((j.muestra || []).length) {
            html += '<ul class="mb-0 mt-2">';
            j.muestra.forEach(c => { html += `<li>${c.nombre} · ${c.numero}</li>`; });
            html += '</ul>';
        }
        previewBox.innerHTML = html;
    });

    document.querySelectorAll('.btn-edit').forEach(btn => btn.addEventListener('click', async () => {
        form.reset();
        form.action.value = 'change';
        form.pk.value = btn.dataset.id;
        form.nombre.value = btn.dataset.nombre;
        form.descripcion.value = btn.dataset.desc;
        modalEl.querySelector('.modal-title').textContent = 'Editar segmento';
        const r = await fetch(`?action=condiciones&id=${btn.dataset.id}`);
        const j = await r.json();
        cargarCondiciones(j.condiciones);
        modal.show();
    }));

    modalEl.addEventListener('show.bs.modal', (e) => {
        if (!e.relatedTarget) return;
        form.reset();
        form.action.value = 'add';
        form.pk.value = '';
        modalEl.querySelector('.modal-title').textContent = 'Nuevo segmento';
        cargarCondiciones({});
    });

    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        form.condiciones_json.value = JSON.stringify(serializarCondiciones());
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
        if (!confirm(`¿Eliminar el segmento "${btn.dataset.nombre}"?`)) return;
        const fd = new FormData();
        fd.append('action', 'delete');
        fd.append('id', btn.dataset.id);
        fd.append('csrfmiddlewaretoken', csrf);
        const r = await fetch('', {method: 'POST', body: fd});
        const j = await r.json();
        if (!j.error) location.reload(); else alert(j.message || 'Error');
    }));
})();
