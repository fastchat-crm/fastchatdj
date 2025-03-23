var targetEvent;
const modalDetalle = $('#modalDetalle');
const modalDetalleContenido = $('#modalDetalleContenido');
const rutaPlan = '/planificacion/calendario/';
var handleCalendar = function () {
    $('#external-events .fc-event').each(function () {
        $(this).data('event', {
            title: $.trim($(this).text()), // use the element's text as the event title
            stick: true, // maintain when user navigates (see docs on the renderEvent method)
            color: ($(this).attr('data-color')) ? $(this).attr('data-color') : ''
        });
        $(this).draggable({
            zIndex: 999,
            revert: true,      // will cause the event to go back to its
            revertDuration: 0  //  original position after the drag
        });
    });

    var date = new Date();
    var currentYear = date.getFullYear();
    var currentMonth = date.getMonth() + 1;
    currentMonth = (currentMonth < 10) ? '0' + currentMonth : currentMonth;
    var calendar = $('#calendar').fullCalendar({
        header: {
            left: 'month,agendaWeek,agendaDay',
            center: 'title',
            right: 'prev,today,next '
        },
        selectable: true,
        selectHelper: true,
        editable: true,
        eventLimit: false, // allow "more" link when too many events
        events: `${rutaPlan}?action=get_fechas`,
        eventClick: function (info, event, b) {
            if (info.puede_modificar) {
                targetEvent = event.currentTarget;
                getPromise(rutaPlan, {
                    action: 'anular_activar_dia',
                    id: info.rangoFechaId,
                    fecha: info.start._i.split(" ")[0].split("T")[0]
                }).then(function (data) {
                    if (data.resp) {
                        modalDetalleContenido.html(data.contenido);
                        modalDetalle.find('#titulo').html(data.titulo);
                        modalDetalle.find('#btnToggleFecha').html(data.titulo);
                        modalDetalle.find('#btnToggleFecha').attr("onclick", `toggleFecha(${info.rangoFechaId}, '${info.start._i.split(" ")[0].split("T")[0]}', this)`);
                        modalDetalle.modal('show');
                    } else {
                        mensajeDanger("No hay detalle.");
                    }
                });
            } else{
                window.open(`/planificacion/citas/?desde=${info.start._i.split(" ")[0].split("T")[0]}&hasta=${info.start._i.split(" ")[0].split("T")[0]}`, "_blank");            }
        }
    });
};

var Calendar = function () {
    "use strict";
    return {
        //main function
        init: function () {
            handleCalendar();
        }
    };
}();

$(document).ready(function () {
    Calendar.init();
});

function toggleFecha(id, fecha, control) {
    let form = $('#modalDetalleContenido')[0];
    let formData = new FormData(form);
    postPromise(rutaPlan, {
        id: id,
        action: 'anular_activar_dia',
        fecha: fecha,
        'csrfmiddlewaretoken': formData.get("csrfmiddlewaretoken")
    }).then(function (value) {
        if (value.state) {
            $(`.event${id}${fecha}`).css("background-color", value.color);
            modalDetalle.modal("hide");
        } else {
            alertaDanger(value.message);
        }
    });
}