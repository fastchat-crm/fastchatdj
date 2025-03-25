function converToAscii(str) {
    return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
}

$(document).ready(function () {
    // Referencia al campo de búsqueda
    const searchInput = $('.top-search');

    searchInput.on('keyup search', function () {
        const searchText = converToAscii($(this).val());

        // Si el campo está vacío, colapsa todos los menús y muestra todos los elementos
        if (searchText === '') {
            // Cierra todos los menús colapsables
            $('.startbar-menu .collapse').removeClass('show');
            // Muestra todos los elementos de navegación
            $('.startbar-menu .nav-item').show();
            return;
        }

        // Busca en los elementos de navegación principales
        $('.startbar-menu .navbar-nav > li.nav-item').each(function () {
            const currentText = converToAscii($(this).text());
            const showItem = currentText.indexOf(searchText) !== -1;

            $(this).toggle(showItem);

            // Si coincide con el término de búsqueda, expande el submenú
            if (showItem && $(this).find('.collapse').length) {
                $(this).find('.collapse').addClass('show');
                $(this).find('.nav-link[data-bs-toggle="collapse"]').attr('aria-expanded', 'true');
            }
        });

        // Busca en los elementos de los submenús y expande los padres correspondientes
        $('.startbar-menu .collapse .nav-item').each(function () {
            const currentText = converToAscii($(this).text());
            const showItem = currentText.indexOf(searchText) !== -1;

            $(this).toggle(showItem);

            // Si el elemento del submenú coincide, asegúrate de que su menú padre esté visible y expandido
            if (showItem) {
                const parentCollapse = $(this).closest('.collapse');
                parentCollapse.addClass('show');

                // Asegúrate de que el elemento padre de navegación esté visible
                const parentNavItem = parentCollapse.closest('.nav-item');
                parentNavItem.show();

                // Asegúrate de que el enlace que controla el colapso esté marcado como expandido
                parentNavItem.find('.nav-link[data-bs-toggle="collapse"]').attr('aria-expanded', 'true');
            }
        });
    });

    // Otros elementos de tu código
    function alertasmoke(mensaje) {
        smoke.alert(mensaje, function(e){
        }, {
            ok: "Okey",
            classname: "custom-class"
        });
    }

    const platform = navigator.platform.toLowerCase(),
        iosPlatforms = ['iphone', 'ipad', 'ipod', 'ipod touch'];

    var isMobile = {
        Android: function() {
            return navigator.userAgent.toLowerCase().match(/android/i);
        },
        BlackBerry: function() {
            return navigator.userAgent.match(/BlackBerry/i);
        },
        iOS: function() {
            return iosPlatforms.includes(platform);
        },
        Mac: function() {
            return platform.includes('mac');
        },
        Opera: function() {
            return navigator.userAgent.match(/Opera Mini/i);
        },
        Windows: function() {
            return platform.includes('win');
        },
        Linux: function() {
            return /linux/.test(platform);
        },
        any: function() {
            return (isMobile.Android() || isMobile.BlackBerry() || isMobile.iOS() || isMobile.Opera() || isMobile.Windows());
        }
    };
});