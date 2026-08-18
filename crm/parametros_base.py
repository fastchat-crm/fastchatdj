"""Lectura y escritura de `ParametroSistema`, el nivel de plataforma.

Lo usa el Centro de IA (`/crm/centro-ia/`) desde dos pestañas distintas:

    Parámetros      → grupo `comportamiento_ia`  (cómo responde el bot)
    Límites de gasto → grupo `limites`           (cuánto puede gastar)

El guardado **siempre filtra por grupo**. Es lo que impide que un POST armado a
mano desde la pestaña de parámetros toque los topes de gasto, que son una
decisión de otra naturaleza.
"""
from seguridad.models import ParametroSistema


def validar_valor(parametro, crudo):
    """Comprueba que el texto entre en el tipo declarado del parámetro.

    Devuelve `(ok, mensaje)`. El mensaje se concatena al nombre del parámetro,
    así que se escribe como continuación de la frase.
    """
    if parametro.tipo == 'entero':
        try:
            int(crudo)
        except (TypeError, ValueError):
            return False, 'debe ser un número entero.'
    elif parametro.tipo == 'decimal':
        try:
            float(str(crudo).replace(',', '.'))
        except (TypeError, ValueError):
            return False, 'debe ser un número decimal.'
    elif parametro.tipo == 'booleano':
        if str(crudo).strip().lower() not in ('true', 'false'):
            return False, 'valor booleano inválido.'
    return True, ''


def _guardar(request, grupos):
    """Guarda los parámetros de `grupos` que vengan en el POST.

    Lanza `ValueError` con todos los errores juntos si alguno no valida, para
    que el llamador los muestre de una sola vez en vez de de a uno.
    """
    editables = ParametroSistema.objects.filter(status=True, editable=True, grupo__in=grupos)
    errores = []
    for parametro in editables:
        campo = 'param_{}'.format(parametro.pk)
        if campo not in request.POST:
            continue
        crudo = (request.POST.get(campo) or '').strip()
        ok, msg = validar_valor(parametro, crudo)
        if not ok:
            errores.append('{}: {}'.format(parametro.etiqueta, msg))
            continue
        parametro.valor = crudo
        parametro.save(request)
    if errores:
        raise ValueError(' · '.join(errores))
