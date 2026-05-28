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

    menu.addEventListener('click', function (ev) {
        var item = ev.target.closest('.wa-sesion-item');
        if (!item) {
            return;
        }
        ev.preventDefault();
        var sid = item.dataset.sesionId;
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
    });
})();
