from __future__ import annotations

from django.core.files.images import get_image_dimensions
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


#para el modelo financiero.models.Constante


@deconstructible
class FileMaxSizeInMbValidator:
    message = "El tamaño máximo del archivo es %(maxSize)sMB."
    code = "invalid_file_size"

    def __init__(self, fileSize: int | float = None, message=None, code=None):
        self.fileSize = fileSize
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code

    def __call__(self, file):
        file_size = file.file.size
        limit_kb = self.fileSize * 1000
        if file_size > limit_kb * 1024:
            raise ValidationError(
                self.message,
                code=self.code,
                params={
                    "maxSize": self.fileSize,
                    "value": file,
                }
            )

    def __eq__(self, other):
        return (
                isinstance(other, self.__class__)
                and self.fileSize == other.fileSize
                and self.message == other.message
                and self.code == other.code
        )

def validate_file_size_2mb(file):
    __general_validate_file_size(file, 2000)

def validate_file_size_3mb(file):
    __general_validate_file_size(file, 3000)

def validate_file_size_20mb(file):
    __general_validate_file_size(file, 20000)

def __general_validate_file_size(file, size):
    file_size = file.file.size
    limit_kb = size
    if file_size > limit_kb * 1024:
        raise ValidationError("El tamaño máximo del archivo es {}MB".format(int(size/1000)))

def solo_numeros(value):
    if not str(value).isdigit():
        raise ValidationError("Sólo debe ser números")
    return value

def str_to_upper(value):
    rt = value
    if value:
        rt = value.upper()
    return rt

def validar_cedula(value):
    if not es_cedula(value):
        raise ValidationError("Cédula no Válida")
    return value

def validar_ruc(value):
    if not es_ruc(value):
        raise ValidationError("RUC no Válido")
    return value

def es_ruc(ruc):
    cant_digit = len(ruc)
    if ruc.isdigit() and cant_digit == 13 and int(ruc[10:]) >= 1 and int(ruc[10:]) <= 999:
        return True
    return False

def es_pasaporte(doc):
    cant_digit = len(doc)
    if cant_digit >= 5 and cant_digit < 10:
        return True
    return False

def es_cedula(cedula):
    if cedula.isdigit() and len(cedula) == 10:
        if cedula in ('2' * 10, '4' * 10, '6' * 10, '8' * 10,):
            return False
        digito_region = int(cedula[0:2])
        if (digito_region >= 1 and digito_region <= 24) or digito_region == 30:
            ultimo_digito = int(cedula[9:10])
            pares = int(cedula[1:2]) + int(cedula[3:4]) + int(cedula[5:6]) + int(cedula[7:8])

            numero1 = int(cedula[0:1])

            numero1 = (numero1 * 2)
            if numero1 > 9:
                numero1 = (numero1 - 9)

            numero3 = int(cedula[2:3])

            numero3 = (numero3 * 2)
            if numero3 > 9:
                numero3 = (numero3 - 9)

            numero5 = int(cedula[4:5])

            numero5 = (numero5 * 2)
            if numero5 > 9:
                numero5 = (numero5 - 9)

            numero7 = int(cedula[6:7])

            numero7 = (numero7 * 2)
            if numero7 > 9:
                numero7 = (numero7 - 9)

            numero9 = int(cedula[8: 9])

            numero9 = (numero9 * 2)
            if numero9 > 9:
                numero9 = (numero9 - 9)

            impares = numero1 + numero3 + numero5 + numero7 + numero9

            suma_total = (pares + impares)

            primer_digito_suma = str(suma_total)[0: 1]

            decena = (int(primer_digito_suma) + 1) * 10

            digito_validador = decena - suma_total

            if digito_validador == 10:
                digito_validador = 0

            digito_validador_final = int(str(digito_validador)[len(str(digito_validador)) - 1])
            if digito_validador_final == ultimo_digito:
                return True
    return False

def validar_ced_o_ruc(dato=""):
    if len(dato) == 10:
        return validar_cedula(dato)
    elif len(dato) == 13:
        return validar_ruc(dato)
    else:
        return False