function mayus(e) {
    e.value = e.value.toUpperCase();
}

if (typeof (String.prototype.trim) === "undefined") {
    String.prototype.trim = function () {
        return String(this).replace(/^\s+|\s+$/g, '');
    };
}

if (typeof (String.prototype.titleCase) === "undefined") {
    String.prototype.titleCase = function () {
        var sentence = String(this).toLowerCase().split(" ");
        for (var i = 0; i < sentence.length; i++) {
            sentence[i] = sentence[i][0].toUpperCase() + sentence[i].slice(1);
        }
        return sentence.join(" ");
    };
}

var cedula = document.getElementById('cedula');

function validarCedula(cedula) {
    if (typeof (cedula) == 'string' && cedula.length == 10 && /^\d+$/.test(cedula)) {
        var digitos = cedula.split('').map(Number);
        var codigo_provincia = digitos[0] * 10 + digitos[1];

        //if (codigo_provincia >= 1 && (codigo_provincia <= 24 || codigo_provincia == 30) && digitos[2] < 6) {

        if (codigo_provincia >= 1 && (codigo_provincia <= 24 || codigo_provincia == 30)) {
            var digito_verificador = digitos.pop();

            var digito_calculado = digitos.reduce(
                function (valorPrevio, valorActual, indice) {
                    return valorPrevio - (valorActual * (2 - indice % 2)) % 9 - (valorActual == 9) * 9;
                }, 1000) % 10;
            return digito_calculado === digito_verificador;
        }
    }
    return false;
}


var web = document.getElementById('web');

function validarWeb(web) {
    expr = /^www.\w+.\w+$/gi;
    if (!expr.test(web)) {
        $("#web").val("");
        swal("La dirección web !! " + web + " !! es incorrecta.", 'Validación', 'error');
    }
}

function soloNumeros(e) {
    var key = window.Event ? e.which : e.keyCode
    return (key >= 48 && key <= 57)
}

function soloNumeros1(e) {
    key = e.keyCode || e.which;
    teclado = String.fromCharCode(key);
    letras = "1234567890.";
    teclado_especial = false;
    if (letras.indexOf(teclado) == -1 && !teclado_especial) {
        return false;
    }
}


function sololetras(e) {
    key = e.keyCode || e.which;
    teclado = String.fromCharCode(key);
    letras = "abcdefghijklmnopqrstuwxyzABCDEFGHIJKLMNÑOPQRSTUWXYVvZñ ";
    teclado_especial = false;
    if (letras.indexOf(teclado) == -1 && !teclado_especial) {
        return false;
    }
}

function sololetras3(e) {
    key = e.keyCode || e.which;
    teclado = String.fromCharCode(key);
    letras = "abcdefghijklmnopqrstuwxyzABCDEFGHIJKLMNÑOPQRSTUWXYVvZ1234567890";
    teclado_especial = false;
    if (letras.indexOf(teclado) == -1 && !teclado_especial) {
        return false;
    }
}

function sololetrasnumeros(e) {
    key = e.keyCode || e.which;
    teclado = String.fromCharCode(key);
    letras = "abcdefghijklmnopqrstuwxyzABCDEFGHIJKLMNÑOPQRSTUWXYVvZñ1234567890 ";
    teclado_especial = false;
    if (letras.indexOf(teclado) == -1 && !teclado_especial) {
        return false;
    }
}

function soloNumerosT(e) {

    var num_sf = document.getElementById('tel').value;
    var num_cf = '';
    num_cf = num_sf.substring(0, 3) + "-";
    num_cf += num_sf.substring(3, 6) + "-";
    num_cf += num_sf.substring(6, 9);
    document.getElementById('format').value = num_cf;

    var key = window.Event ? e.which : e.keyCode
    var c
    c += 1;
    if (c == 3)
        key = key + "-";
    return (key >= 48 && key <= 57)
}

function isValidDate(day, month, year) {
    var dteDate;
    month = month - 1;
    dteDate = new Date(year, month, day);
    return ((day == dteDate.getDate()) && (month == dteDate.getMonth()) && (year == dteDate.getFullYear()));
}

// function validate_fecha(fecha) {
//     var patron = new RegExp("^(19|20)+([0-9]{2})([-])([0-9]{1,2})([-])([0-9]{1,2})$");
//     if (fecha.search(patron) == 0) {
//         var values = fecha.split("-");
//         if (isValidDate(values[2], values[1], values[0])) {
//             return true;
//         }
//     }
//     return false;
// }

function calcularEdad(fecha) {
    var values = fecha.split("-");
    var dia = values[2];
    var mes = values[1];
    var ano = values[0];

    // cogemos los valores actuales
    var fecha_hoy = new Date();
    var ahora_ano = fecha_hoy.getYear();
    var ahora_mes = fecha_hoy.getMonth() + 1;
    var ahora_dia = fecha_hoy.getDate();

    // realizamos el calculo
    var edad = (ahora_ano + 1900) - ano;
    if (ahora_mes < mes) {
        edad--;
    }
    if ((mes == ahora_mes) && (ahora_dia < dia)) {
        edad--;
    }
    if (edad > 1900) {
        edad -= 1900;
    }

    // calculamos los meses
    var meses = 0;
    if (ahora_mes > mes)
        meses = ahora_mes - mes;
    if (ahora_mes < mes)
        meses = 12 - (mes - ahora_mes);
    if (ahora_mes == mes && dia > ahora_dia)
        meses = 11;

    // calculamos los dias
    var dias = 0;
    if (ahora_dia > dia)
        dias = ahora_dia - dia;
    if (ahora_dia < dia) {
        ultimoDiaMes = new Date(ahora_ano, ahora_mes, 0);
        dias = ultimoDiaMes.getDate() - (dia - ahora_dia);
    }


    return edad;

}

function calcularFechaActual() {
    var fecha = document.getElementById("PAC_FECHA").value;
    document.getElementById("PAC_FECHA1").value = fecha;

}

var email = document.getElementById('email');

function validarEmail(email) {
    expr = /^([a-zA-Z0-9_\.\-])+\@(([a-zA-Z0-9\-])+\.)+([a-zA-Z0-9]{2,4})+$/;
    if (!expr.test(email)) {
        $("#id_email").val("");
        swal("La dirección de correo  " + email + " es incorrecta.", 'Validación', 'error');
    }
}

var number = document.getElementById('ruc');

function validarRuc(number) {
    var dto = number.length;
    var valor;
    var acu = 0;
    if (number == "") {
        swal('No has ingresado ningún dato, porfavor ingresar los datos correspondientes.', 'Validación', 'error');
    } else {
        for (var i = 0; i < dto; i++) {
            valor = number.substring(i, i + 1);
            if (valor == 0 || valor == 1 || valor == 2 || valor == 3 || valor == 4 || valor == 5 || valor == 6 || valor == 7 || valor == 8 || valor == 9) {
                acu = acu + 1;
            }
        }
        if (acu == dto) {
            while (number.substring(10, 13) !== '001') {
                return;
            }
            while (number.substring(0, 2) > 24) {
                return;
            }
            var porcion1 = number.substring(2, 3);
        }
    }
}

function verificarCedula(cedula) {
    if (typeof (cedula) == 'string') {
        if(cedula.length === 10){
            return esCedula(cedula);
        }else if(cedula.length === 13){
            return esRuc(cedula);
        }
    }
    return false;
}


String.prototype.isDigit = function () {
    for (var i = 0; i < this.length; i++) {
        if ("0123456789".indexOf(this[i].toString()) === -1) {
            return false;
        }
    }
    return true;
};

var validadores = {
    _cedula: function (field) {

        var numero = field;

        var __validarcedula = function (numero) {
            //Preguntamos si la cedula consta de 10 digitos
            if (numero.length == 10) {
                if (numero == '2222222222' || numero == '4444444444' || numero == '6666666666' || numero == '8888888888') {
                    return false;
                }

                //Obtenemos el digito de la region que sonlos dos primeros digitos
                var digito_region = numero.substring(0, 2);

                //Pregunto si la region existe ecuador se divide en 24 regiones
                if ((digito_region >= 1 && digito_region <= 24) || digito_region == 30) {

                    // Extraigo el ultimo digito
                    var ultimo_digito = numero.substring(9, 10);

                    //Agrupo todos los pares y los sumo
                    var pares = parseInt(numero.substring(1, 2)) + parseInt(numero.substring(3, 4)) + parseInt(numero.substring(5, 6)) + parseInt(numero.substring(7, 8));

                    //Agrupo los impares, los multiplico por un factor de 2, si la resultante es > que 9 le restamos el 9 a la resultante
                    var numero1 = numero.substring(0, 1);
                    numero1 = (numero1 * 2);
                    if (numero1 > 9) {
                        numero1 = (numero1 - 9);
                    }

                    var numero3 = numero.substring(2, 3);
                    numero3 = (numero3 * 2);
                    if (numero3 > 9) {
                        numero3 = (numero3 - 9);
                    }

                    var numero5 = numero.substring(4, 5);
                    numero5 = (numero5 * 2);
                    if (numero5 > 9) {
                        numero5 = (numero5 - 9);
                    }

                    var numero7 = numero.substring(6, 7);
                    numero7 = (numero7 * 2);
                    if (numero7 > 9) {
                        numero7 = (numero7 - 9);
                    }

                    var numero9 = numero.substring(8, 9);
                    numero9 = (numero9 * 2);
                    if (numero9 > 9) {
                        numero9 = (numero9 - 9);
                    }

                    var impares = numero1 + numero3 + numero5 + numero7 + numero9;

                    //Suma total
                    var suma_total = (pares + impares);


                    //extraemos el primero digito
                    var primer_digito_suma = String(suma_total).substring(0, 1);

                    //Obtenemos la decena inmediata
                    var decena = (parseInt(primer_digito_suma) + 1) * 10;

                    //Obtenemos la resta de la decena inmediata - la suma_total esto nos da el digito validador
                    var digito_validador = decena - suma_total;
                    //Si el digito validador es = a 10 toma el valor de 0

                    if (digito_validador == 10)
                        digito_validador = 0;

                    var digito_validador_final = parseInt(String(digito_validador).substring(String(digito_validador).length - 1));

                    //Validamos que el digito validador sea igual al de la cedula
                    if (digito_validador_final == ultimo_digito) {
                        return true;// return('la cedula:' + cedula + ' es correcta');
                    } else {
                        return false;
                    }

                } else {
                    // imprimimos en consola si la region no pertenece
                    return false;
                }
            } else {
                //imprimimos en consola si la cedula tiene mas o menos de 10 digitos
                return false;
            }
        };
        return __validarcedula(numero);
    }
};

function esCedula(cedula) {
    if (typeof (cedula) == 'string' && cedula.length === 10 && /^\d+$/.test(cedula)) {
        return validadores._cedula(cedula);
    }
    return false;
}

function esRuc(ruc) {
    if (typeof (ruc) == 'string' && ruc.isDigit() &&
        ruc.length === 13 && parseInt(ruc.substr(10)) >= 1 &&
        parseInt(ruc.substr(10)) <= 999) {
        return true;//esCedula(ruc.substr(0, 10))
    }
    return false;
}