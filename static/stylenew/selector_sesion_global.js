(function () {
    var btn = document.getElementById('wa-global-sesion');
    if (!btn) {
        return;
    }
    var menu = btn.parentElement.querySelector('.wa-sesion-menu');
    if (!menu) {
        return;
    }
    var csrf = btn.dataset.csrf || '';
    var url = btn.dataset.url || '/whatsapp/sesion-activa/';

    function cambiarSesion(item, sid) {
        var fd = new FormData();
        fd.append('sesion_id', sid);
        fd.append('csrfmiddlewaretoken', csrf);
        item.classList.add('is-loading');
        fetch(url, {
            method: 'POST',
            body: fd,
            headers: {'X-CSRFToken': csrf},
            credentials: 'same-origin'
        }).then(function (r) {
            return r.json();
        }).then(function (d) {
            if (d && d.result) {
                window.location.reload();
            } else {
                item.classList.remove('is-loading');
            }
        }).catch(function () {
            item.classList.remove('is-loading');
        });
    }

    function aplicarFiltroCanales() {
        var activos = {};
        menu.querySelectorAll('.wa-canal-chip').forEach(function (chip) {
            activos[chip.dataset.canal] = chip.classList.contains('active');
        });
        menu.querySelectorAll('li[data-canal]').forEach(function (li) {
            li.style.display = activos[li.dataset.canal] === false ? 'none' : '';
        });
    }

    menu.addEventListener('click', function (ev) {
        var chip = ev.target.closest('.wa-canal-chip');
        if (chip) {
            ev.preventDefault();
            ev.stopPropagation();
            chip.classList.toggle('active');
            aplicarFiltroCanales();
            return;
        }
        var item = ev.target.closest('.wa-sesion-item');
        if (!item) {
            return;
        }
        ev.preventDefault();
        if (item.classList.contains('is-active')) {
            return;
        }
        var sid = item.dataset.sesionId;
        var nameEl = item.querySelector('.wa-sesion-item-name');
        var nombre = nameEl ? nameEl.textContent.trim() : '';
        if (window.Swal && Swal.fire) {
            Swal.fire({
                title: 'Switch session?',
                text: nombre ? 'The page will reload showing "' + nombre + '".' : 'The page will reload with the selected session.',
                type: 'question', showCancelButton: true, allowOutsideClick: false,
                confirmButtonText: 'Yes, switch', cancelButtonText: 'Cancel',
            }).then(function (res) {
                if (res && res.value) {
                    cambiarSesion(item, sid);
                }
            });
        } else if (window.confirm('Switch session?')) {
            cambiarSesion(item, sid);
        }
    });
})();
