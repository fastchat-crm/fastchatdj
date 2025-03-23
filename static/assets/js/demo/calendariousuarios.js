/*
Template Name: Color Admin - Responsive Admin Dashboard Template build with Twitter Bootstrap 4
Version: 4.6.0
Author: Sean Ngu
Website: http://www.seantheme.com/color-admin/admin/
*/

var handleCalendarDemo = function () {
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
    $('#calendar').fullCalendar({
        header: {
            left: 'month,agendaWeek,agendaDay',
            center: 'title',
            right: 'prev,today,next '
        },
        // droppable: true, // this allows things to be dropped onto the calendar
        // drop: function () {
        //     $(this).remove();
        // },
        selectable: true,
        selectHelper: true,
        // select: function(start, end) {
        // 	var title = prompt('Event Title:');
        // 	var eventData;
        // 	if (title) {
        // 		eventData = {
        // 			title: title,
        // 			start: start,
        // 			end: end
        // 		};
        // 		$('#calendar').fullCalendar('renderEvent', eventData, true); // stick? = true
        // 	}
        // 	$('#calendar').fullCalendar('unselect');
        // },
        editable: true,
        eventLimit: false, // allow "more" link when too many events
        events: `/ajaxrequest/consultar_calendario?clienteConsulta=${$("#clienteConsultaMantenimiento").length?$("#clienteConsultaMantenimiento").val():"0"}&equipoIdDetalle=${$("#equipoIdDetalle").length?$("#equipoIdDetalle").val():"0"}`,
        // eventSources: [
        //
        //     // your event source
        //     {
        //         url: '/ajaxrequest/consultar_calendario',
        //         method: 'GET',
        //         failure: function () {
        //             alert('there was an error while fetching events!');
        //         },
        //         color: '#009688',   // a non-ajax option
        //         textColor: 'white' // a non-ajax option
        //     }
        //
        //     // any other sources...
        //
        // ],
        eventClick: function(info) {
            if(info.action && info.action === "cronograma_mantenimiento"){
                ModalAlertaCalendario.find('#accion').html(info.title);
                ModalAlertaCalendario.find('#icono').attr("class", "fas fa-calendar");
                ModalAlertaCalendario.find("form").attr("action", info.action_form);
                ModalAlertaCalendario.find("form").attr("method", "GET");
                var observacionAlert = "";
                if(info.observacion){
                    observacionAlert = `
                        <div class="alert alert-info">
                            <h6><i class="fa fa-info-circle"></i> ¡Atención!</h6>
                            <p>
                                ${info.observacion}
                            </p>
                        </div>
                    `;
                }
                if(info.cantRegMant > 0){
                    observacionAlert = observacionAlert +`
                        <div class="alert alert-info">
                            <h6><i class="fa fa-info-circle"></i> ¡Atención!</h6>
                            <p>
                                Ya se registraron ${info.cantRegMant} mantentimiento${info.cantRegMant > 1?"s":""} en la${info.cantRegMant > 1?"s":""} fecha${info.cantRegMant > 1?"s":""} ${info.fechasRegMant.join(', ')}
                            </p>
                        </div>
                    `;
                }
                ModalAlertaCalendario.find('.tablaaqui').html(`
                    <div>${observacionAlert}</div>
                    <input type="hidden" name="fechaid" value="${info.objid}">
                    <input type="hidden" name="action" value="add">
                    <input type="hidden" name="tipo_mant" value="${info.tipo_mant}">
                    <input type="hidden" name="contrato" value="${info.contrato}">
                    <input type="hidden" name="equipo" value="${info.equipo}">
                    <div>
                        <label for="id_fecha_select">Seleccione la fecha a realizar el mantenimiento:</label>
                        <select class="form-control" required name="fecha_select" id="id_fecha_select">
                            <option value="">--------------</option>
                            ${
                                info.lista_fechas.map(function(x) {
                                   return `<option value="${x.value}">${x.text}</option>`;
                                }).join('')
                            }
                        </select>
                    </div>
                    <div class="mt-2">
                        <button type="submit" class="btn btn-success">
                            Ir a registrar
                        </button>
                    </div>
                `);
                ModalAlertaCalendario.modal({backdrop: 'static'}).modal('show');
            }
            if(info.action && info.action === "cronograma_detalle"){
                ModalAlertaCalendario.find('#accion').html(info.title);
                var observacionAlert = `
                        <div class="alert alert-info">
                            <h6><i class="fa fa-info-circle"></i> Información</h6>
                            <p>
                                Aún no hay registros de mantenimientos para este mes.
                            </p>
                        </div>
                    `;
                if(info.cantRegMant > 0){
                    observacionAlert = `
                        <div class="alert alert-info">
                            <h6><i class="fa fa-info-circle"></i> ¡Atención!</h6>
                            <p>
                                Ya se registraron ${info.cantRegMant} mantentimiento${info.cantRegMant > 1?"s":""} en la${info.cantRegMant > 1?"s":""} fecha${info.cantRegMant > 1?"s":""} ${info.fechasRegMant.join(', ')}
                            </p>
                        </div>
                    `;
                }
                ModalAlertaCalendario.find('.tablaaqui').html(`
                    <div>${observacionAlert}</div>
                    <div class="mt-2 text-right">
                        <button type="button" class="btn btn-success" data-dismiss="modal">
                            Ok
                        </button>
                    </div>
                `);
                ModalAlertaCalendario.modal({backdrop: 'static'}).modal('show');
            }
        }
    });
};

var Calendar = function () {
    "use strict";
    return {
        //main function
        init: function () {
            handleCalendarDemo();
        }
    };
}();

$(document).ready(function () {
    Calendar.init();
});