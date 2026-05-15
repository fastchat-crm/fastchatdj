(function () {
    const grid = document.getElementById('agendaGrid');
    if (!grid) return;
    const selRecurso = document.getElementById('horarioRecursoSelect');
    const dayStartInput = document.getElementById('dayStart');
    const dayEndInput = document.getElementById('dayEnd');
    const slotInput = document.getElementById('slotMin');
    const btnSave = document.getElementById('btnSaveHorario');
    const btnClear = document.getElementById('btnClearAllBlocks');
    const btnRebuild = document.getElementById('btnRebuildGrid');
    const modalEl = document.getElementById('modalBlockHorario');
    const modalBlock = new bootstrap.Modal(modalEl);
    const dayNames = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
    const STEP_MIN = 15;
    const PX_PER_MIN = 1.0;
    let dayStart = dayStartInput.value || '06:00';
    let dayEnd = dayEndInput.value || '22:00';
    let blocks = [];
    let nextTempId = -1;
    let editingId = null;
    let recursoActual = null;

    function sincronizarUrl() {
        const url = new URL(window.location.href);
        if (recursoActual) {
            url.searchParams.set('recurso', recursoActual);
        } else {
            url.searchParams.delete('recurso');
        }
        if (dayStartInput.value) url.searchParams.set('day_start', dayStartInput.value);
        if (dayEndInput.value) url.searchParams.set('day_end', dayEndInput.value);
        if (slotInput.value) url.searchParams.set('slot', slotInput.value);
        window.history.replaceState({}, '', url.toString());
    }

    dayStartInput.addEventListener('change', sincronizarUrl);
    dayEndInput.addEventListener('change', sincronizarUrl);
    slotInput.addEventListener('change', sincronizarUrl);

    const toMin = function (h) { const p = h.split(':').map(Number); return p[0] * 60 + p[1]; };
    const toHHMM = function (m) {
        const h = Math.floor(m / 60), x = m % 60;
        return String(h).padStart(2, '0') + ':' + String(x).padStart(2, '0');
    };
    const snap = function (m) { return Math.round(m / STEP_MIN) * STEP_MIN; };

    function buildGrid() {
        grid.innerHTML = '';
        if (!recursoActual) {
            grid.innerHTML = '<div class="text-center text-muted py-5"><i class="fa fa-arrow-up me-1"></i> Elegí un recurso para editar su horario.</div>';
            return;
        }
        const sM = toMin(dayStart), eM = toMin(dayEnd);
        if (eM - sM <= 0) return;
        const heightPx = (eM - sM) * PX_PER_MIN;
        const header = document.createElement('div');
        header.className = 'ag-header';
        header.appendChild(document.createElement('div'));
        dayNames.forEach(function (n) {
            const c = document.createElement('div');
            c.className = 'ag-day-head';
            c.textContent = n;
            header.appendChild(c);
        });
        grid.appendChild(header);
        const body = document.createElement('div');
        body.className = 'ag-body';
        const ruler = document.createElement('div');
        ruler.className = 'ag-ruler';
        ruler.style.height = heightPx + 'px';
        for (let m = sM; m <= eM; m += 60) {
            const t = document.createElement('div');
            t.className = 'ag-tick';
            t.style.top = ((m - sM) * PX_PER_MIN) + 'px';
            t.textContent = toHHMM(m);
            ruler.appendChild(t);
        }
        body.appendChild(ruler);
        for (let d = 0; d < 7; d++) {
            const col = document.createElement('div');
            col.className = 'ag-day-col';
            col.dataset.day = d;
            col.style.height = heightPx + 'px';
            for (let m = sM; m < eM; m += 60) {
                const hr = document.createElement('div');
                hr.className = 'ag-hour-line';
                hr.style.top = ((m - sM) * PX_PER_MIN) + 'px';
                col.appendChild(hr);
            }
            attachColEvents(col);
            body.appendChild(col);
        }
        grid.appendChild(body);
        renderBlocks();
    }

    function renderBlocks() {
        grid.querySelectorAll('.ag-block').forEach(function (el) { el.remove(); });
        if (!recursoActual) return;
        const sM = toMin(dayStart);
        blocks.forEach(function (b) {
            if (b._deleted) return;
            const col = grid.querySelector('.ag-day-col[data-day="' + b.day + '"]');
            if (!col) return;
            const top = (toMin(b.start) - sM) * PX_PER_MIN;
            const height = (toMin(b.end) - toMin(b.start)) * PX_PER_MIN;
            if (height <= 0) return;
            const el = document.createElement('div');
            el.className = 'ag-block';
            el.dataset.id = b.id || b._tempId;
            el.style.top = top + 'px';
            el.style.height = height + 'px';
            el.innerHTML = '<div class="ag-resize ag-resize-top"></div>'
                + '<div class="ag-block-body">'
                + '<div class="ag-block-time">' + b.start + ' – ' + b.end + '</div>'
                + '<div class="ag-block-slot">' + b.slot_min + ' min</div>'
                + '</div>'
                + '<div class="ag-resize ag-resize-bottom"></div>';
            attachBlockEvents(el, b);
            col.appendChild(el);
        });
    }

    function findBlock(id) {
        return blocks.find(function (b) { return String(b.id || b._tempId) === String(id); });
    }

    function attachColEvents(col) {
        let drag = null;
        col.addEventListener('mousedown', function (e) {
            if (e.target.closest('.ag-block')) return;
            if (e.button !== 0) return;
            const rect = col.getBoundingClientRect();
            const sM = toMin(dayStart);
            const m0 = snap(sM + (e.clientY - rect.top) / PX_PER_MIN);
            drag = {m0: m0, day: parseInt(col.dataset.day, 10), preview: null};
            e.preventDefault();
        });
        col.addEventListener('mousemove', function (e) {
            if (!drag) return;
            const rect = col.getBoundingClientRect();
            const sM = toMin(dayStart);
            const m1 = snap(sM + (e.clientY - rect.top) / PX_PER_MIN);
            const a = Math.min(drag.m0, m1), b = Math.max(drag.m0, m1);
            if (b - a < STEP_MIN) return;
            if (!drag.preview) {
                drag.preview = document.createElement('div');
                drag.preview.className = 'ag-block ag-preview';
                col.appendChild(drag.preview);
            }
            drag.preview.style.top = ((a - sM) * PX_PER_MIN) + 'px';
            drag.preview.style.height = ((b - a) * PX_PER_MIN) + 'px';
            drag.preview.textContent = toHHMM(a) + ' – ' + toHHMM(b);
            drag.range = [a, b];
        });
        document.addEventListener('mouseup', function () {
            if (!drag) return;
            if (drag.preview) drag.preview.remove();
            if (drag.range) {
                const a = drag.range[0], b = drag.range[1];
                const slot = parseInt(document.getElementById('slotMin').value || 30, 10);
                blocks.push({_tempId: nextTempId--, day: drag.day, start: toHHMM(a), end: toHHMM(b), slot_min: slot});
                renderBlocks();
            }
            drag = null;
        });
    }

    function attachBlockEvents(el, b) {
        let mode = null, startY = 0, oS = 0, oE = 0;
        el.addEventListener('mousedown', function (e) {
            e.stopPropagation();
            if (e.button !== 0) return;
            if (e.target.classList.contains('ag-resize-top')) mode = 'rt';
            else if (e.target.classList.contains('ag-resize-bottom')) mode = 'rb';
            else mode = 'mv';
            startY = e.clientY;
            oS = toMin(b.start);
            oE = toMin(b.end);
        });
        document.addEventListener('mousemove', function (e) {
            if (!mode) return;
            const dM = snap((e.clientY - startY) / PX_PER_MIN);
            if (mode === 'mv') {
                const len = oE - oS;
                let ns = oS + dM;
                ns = Math.max(toMin(dayStart), Math.min(toMin(dayEnd) - len, ns));
                b.start = toHHMM(ns);
                b.end = toHHMM(ns + len);
            } else if (mode === 'rt') {
                b.start = toHHMM(Math.max(toMin(dayStart), Math.min(oE - STEP_MIN, oS + dM)));
            } else if (mode === 'rb') {
                b.end = toHHMM(Math.max(oS + STEP_MIN, Math.min(toMin(dayEnd), oE + dM)));
            }
            renderBlocks();
        });
        document.addEventListener('mouseup', function () { mode = null; });
        el.addEventListener('dblclick', function (e) {
            e.stopPropagation();
            editingId = b.id || b._tempId;
            document.getElementById('blockDay').value = dayNames[b.day];
            document.getElementById('blockStart').value = b.start;
            document.getElementById('blockEnd').value = b.end;
            document.getElementById('blockSlot').value = b.slot_min;
            modalBlock.show();
        });
    }

    document.getElementById('btnApplyBlock').addEventListener('click', function () {
        const b = findBlock(editingId); if (!b) return;
        b.start = document.getElementById('blockStart').value;
        b.end = document.getElementById('blockEnd').value;
        b.slot_min = parseInt(document.getElementById('blockSlot').value || 30, 10);
        renderBlocks(); modalBlock.hide();
    });
    document.getElementById('btnDeleteBlock').addEventListener('click', function () {
        const b = findBlock(editingId); if (!b) return;
        if (b.id) b._deleted = true;
        else blocks = blocks.filter(function (x) { return x._tempId !== b._tempId; });
        renderBlocks(); modalBlock.hide();
    });

    btnClear.addEventListener('click', function () {
        if (!confirm('¿Borrar todos los bloques de este recurso?')) return;
        blocks.forEach(function (b) { if (b.id) b._deleted = true; });
        blocks = blocks.filter(function (b) { return b.id; });
        renderBlocks();
    });
    btnRebuild.addEventListener('click', function () {
        dayStart = document.getElementById('dayStart').value || '06:00';
        dayEnd = document.getElementById('dayEnd').value || '22:00';
        buildGrid();
    });

    async function cargarRecurso(rid) {
        recursoActual = rid || null;
        blocks = [];
        if (!recursoActual) {
            btnSave.disabled = true; btnClear.disabled = true;
            buildGrid();
            return;
        }
        pantallaespera();
        const j = await window.postAgendaEntity({entity: 'horario', action: 'load', recurso_id: recursoActual});
        $.unblockUI();
        if (j.error) {
            Swal.fire(j.message || 'Error', '', 'error');
            return;
        }
        blocks = (j.blocks || []).map(function (b) { return Object.assign({}, b); });
        document.getElementById('slotMin').value = j.default_slot_min || 30;
        btnSave.disabled = false; btnClear.disabled = false;
        buildGrid();
    }

    selRecurso.addEventListener('change', function () {
        cargarRecurso(selRecurso.value);
        sincronizarUrl();
    });

    btnSave.addEventListener('click', async function () {
        if (!recursoActual) return;
        btnSave.disabled = true;
        const payload = blocks.filter(function (b) { return !b._deleted; })
            .map(function (b) { return {day: b.day, start: b.start, end: b.end, slot_min: b.slot_min}; });
        const j = await window.postAgendaEntity({
            entity: 'horario', action: 'save', recurso_id: recursoActual,
            blocks: JSON.stringify(payload), slot_min: document.getElementById('slotMin').value || 30
        });
        btnSave.disabled = false;
        if (j.error) { Swal.fire(j.message || 'Error', '', 'error'); return; }
        Swal.fire('Horario guardado (' + j.count + ' bloques).', '', 'success');
    });

    buildGrid();
    const initial = selRecurso.dataset.initial;
    if (initial && selRecurso.value === initial) {
        cargarRecurso(initial);
    }
})();
