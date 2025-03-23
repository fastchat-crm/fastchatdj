const buscarIcono = $('#buscarIcono');
const modalIcons = $('#modalIcons');
const iconsContainer = $('#iconsContainer');
const idIcono = $('#id_icono');

function converToAscii(str) {
    return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
}

$(function () {
    idIcono.attr("type", "hidden");
    buscarIcono.click(function () {
        modalIcons.modal("show");
    });

    for (var i = 0; i < fawIcons.length; i++) {
        var icono = fawIcons[i].classIcon;
        var nombre = fawIcons[i].paraBuscar.split("-").join(' ').trim().titleCase();
        if (icono === idIcono.val()) {
            buscarIcono.html(`Ícono seleccionado: <i style="font-size: 20px;" class="${icono}"></i> ${nombre}`);
            buscarIcono.removeClass('btn-light').addClass('btn-success');
        }
        iconsContainer.append(`
            <label data-paraBuscar="${nombre}" onclick="agregarIcono('${icono}', '${nombre}')" onmouseenter="icMouseEnter(this)" onmouseleave="icMouseLeave(this)" style="cursor: pointer;" for="radioIcons_${i}" class="col-xs-4 col-md-4 col-lg-2 flex justify-content-center text-center mt-2 text-secondary classIconos">
                <input id="radioIcons_${i}" type="radio" style="display: none;" class="radioIcons" name="radioIcons" value="${icono}" />
                <i style="font-size: 48px;" class="${icono}"></i>
                <br>
                <span>${nombre}</span>
            </label>
        `);
    }
    const txtBuscarIcono = $('#txtBuscarIcono');
    txtBuscarIcono.keyup(function () {
        var critero = converToAscii($(this).val());
        $('.classIconos').each(function () {
            var currentLiText = converToAscii($(this).attr('data-paraBuscar')),
                showCurrentLi = currentLiText.indexOf(critero) !== -1;
            $(this).toggle(showCurrentLi);
        });
    });
    txtBuscarIcono.on("search", function () {
        var critero = converToAscii($(this).val());
        $('.classIconos').each(function () {
            var currentLiText = converToAscii($(this).attr('data-paraBuscar')),
                showCurrentLi = currentLiText.indexOf(critero) !== -1;
            $(this).toggle(showCurrentLi);
        });
    });
});

function icMouseEnter(ctr) {
    $(ctr).removeClass('text-secondary').addClass('text-primary');
}

function icMouseLeave(ctr) {
    $(ctr).removeClass('text-primary').addClass('text-secondary');
}

function agregarIcono(valor, nombre) {
    idIcono.val(valor);
    buscarIcono.html(`Ícono seleccionado:   <i style="font-size: 20px;" class="${valor}"></i> ${nombre}`);
    buscarIcono.removeClass('btn-light').addClass('btn-success');
    modalIcons.modal("hide");
}