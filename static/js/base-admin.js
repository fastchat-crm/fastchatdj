function converToAscii(str) {
    return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
}
const searchGroups = $('#searchGroups');
$(document).ready(function () {
    searchGroups.keyup(function () {
        var searchText = converToAscii($(this).val());
        $('.groups > li').each(function () {
            var currentLiText = converToAscii($(this).text().toUpperCase()),
                showCurrentLi = currentLiText.indexOf(searchText.toUpperCase()) !== -1;
            $(this).toggle(showCurrentLi);
        });
        $('.groups > li > ul > li').each(function () {
            var currentLiText = converToAscii($(this).text().toUpperCase()),
                showCurrentLi = currentLiText.indexOf(searchText.toUpperCase()) !== -1;
            $(this).toggle(showCurrentLi);
            $('.has-sub').addClass('active');
        });
    });
    searchGroups.on("search", function () {
        var searchText = converToAscii($(this).val());
        $('.groups > li').each(function () {
            var currentLiText = converToAscii($(this).text().toUpperCase()),
                showCurrentLi = currentLiText.indexOf(searchText.toUpperCase()) !== -1;
            $(this).toggle(showCurrentLi);
        });
        $('.groups > li > ul > li').each(function () {
            var currentLiText = converToAscii($(this).text().toUpperCase()),
                showCurrentLi = currentLiText.indexOf(searchText.toUpperCase()) !== -1;
            $(this).toggle(showCurrentLi);
            $('.has-sub').addClass('active');
        });
    });
});

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
    /**
     * @return {boolean}
     */
    Mac: function() {
        return platform.includes('mac');
    },
    Opera: function() {
        return navigator.userAgent.match(/Opera Mini/i);
    },
    /**
     * @return {boolean}
     */
    Windows: function() {
        return platform.includes('win');
    },
    /**
     * @return {boolean}
     */
    Linux: function() {
        return /linux/.test(platform);
    },
    any: function() {
        return (isMobile.Android() || isMobile.BlackBerry() || isMobile.iOS() || isMobile.Opera() || isMobile.Windows());
    }
};