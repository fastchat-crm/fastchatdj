$(function () {
    function notificar(icono, titulo, texto, alCerrar) {
        if (typeof Swal !== 'undefined' && Swal.fire) {
            Swal.fire({ icon: icono, title: titulo, text: texto }).then(function () {
                if (typeof alCerrar === 'function') { alCerrar(); }
            });
        } else {
            window.alert(titulo + ': ' + texto);
            if (typeof alCerrar === 'function') { alCerrar(); }
        }
    }

    $('#btn-guardar-parametros').on('click', function () {
        var $btn = $(this);
        if ($('#form-parametros-ia').length === 0) { return; }
        var datos = $('#form-parametros-ia').serialize() + '&action=guardar';
        $btn.prop('disabled', true);
        $.post(window.location.pathname, datos)
            .done(function (resp) {
                var item = Array.isArray(resp) ? resp[0] : resp;
                if (item && item.error === false) {
                    notificar('success', 'Guardado', 'Parámetros IA actualizados correctamente.', function () {
                        window.location.href = item.to || window.location.pathname;
                    });
                } else {
                    notificar('error', 'No se guardó', (item && item.message) || 'Revisa los valores ingresados.');
                    $btn.prop('disabled', false);
                }
            })
            .fail(function () {
                notificar('error', 'Error', 'No se pudo conectar. Intenta nuevamente.');
                $btn.prop('disabled', false);
            });
    });
});
