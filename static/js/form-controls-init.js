$(function () {
    // Inicializar Select2 globalmente para elementos fuera de modal
    if ($.fn.select2) {
        $.fn.select2.defaults.set('language', 'es');
        $('.select2-simple:not(.select2-initialized), .select2js:not(.select2-initialized), .jsselect2:not(.select2-initialized), .jselect2:not(.select2-initialized)').select2().addClass('select2-initialized');
    }

    // Inicializar Dropify globalmente
    if ($.fn.dropify) {
        $('.dropify:not(.dropify-rendered)').dropify({
            messages: {
                default: 'Arrastre y suelte un archivo o haga clic aquí.',
                replace: 'Arrastre y suelte un archivo o haga clic aquí.',
                remove: 'Eliminar',
            },
            imgFileExtensions: ["jpg", "jpeg", "png", "tiff", "jfif", "svg"]
        });
    }

    // Inicializar Select2 de forma dinámica para cualquier modal
    $(document).on('shown.bs.modal', '.modal', function() {
        var currentModal = $(this);

        // Inicializar Select2 dentro del modal actual
        if ($.fn.select2) {
            currentModal.find('.select2-simple, .select2js, .jsselect2, .jselect2').each(function() {
                // Verificar si este Select2 ya está inicializado
                if (!$(this).hasClass('select2-initialized')) {
                    $(this).select2({
                        dropdownParent: currentModal,
                        width: '100%'
                    }).addClass('select2-initialized');
                }
            });
        }

        // Inicializar Dropify si está presente
        if ($.fn.dropify) {
            currentModal.find('.dropify:not(.dropify-rendered)').dropify({
                messages: {
                    default: 'Arrastre y suelte un archivo o haga clic aquí.',
                    replace: 'Arrastre y suelte un archivo o haga clic aquí.',
                    remove: 'Eliminar',
                },
                imgFileExtensions: ["jpg", "jpeg", "png", "tiff", "jfif", "svg"]
            });
        }
    });
});