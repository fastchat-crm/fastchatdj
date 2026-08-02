"""Núcleo compartido de las páginas de parámetros de plataforma.

`ParametroSistema` se edita desde dos pantallas distintas, cada una con su
módulo y su permiso:

    /crm/parametros-agentes/  → grupo `comportamiento_ia`  (cómo responde el bot)
    /crm/parametros-tokens/   → grupo `limites`            (cuánto puede gastar)

Están separadas a propósito: quien ajusta el tono y el contexto del agente no es
necesariamente quien controla el gasto, y con módulos distintos se le puede dar
a cada rol solo lo suyo. La lógica de leer, validar y guardar es la misma, así
que vive acá y cada vista solo declara qué grupos muestra.
"""
import sys
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, log
from core.funciones_adicionales import salva_logs
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
    """Guarda solo los parámetros de los grupos que muestra esta pantalla.

    El filtro por grupo es lo que impide que un POST armado a mano desde la
    pantalla de agentes toque los topes de gasto, que viven en otro módulo con
    su propio permiso.
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


def render_parametros(request, *, titulo, descripcion, grupos, plantilla, extra=None):
    """Vista genérica: GET pinta los grupos indicados, POST los guarda."""
    data = {
        'titulo': titulo,
        'modulo': titulo,
        'descripcion': descripcion,
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    if extra:
        data.update(extra)

    if request.method == 'POST':
        res_json = []
        action = request.POST.get('action', '')
        try:
            with transaction.atomic():
                if action == 'guardar':
                    _guardar(request, grupos)
                    log('Editó {}'.format(titulo), request, 'change')
                    messages.success(request, '{} actualizados correctamente.'.format(titulo))
                    res_json.append({'error': False, 'to': request.path})
                else:
                    res_json.append({'error': True, 'message': 'Acción no reconocida.'})
        except ValueError as ex:
            res_json.append({'error': True, 'message': str(ex)})
        except Exception as ex:
            salva_logs(request, __file__, request.method, action, type(ex).__name__,
                       'Error on line {}'.format(sys.exc_info()[-1].tb_lineno), ex)
            res_json.append({'error': True, 'message': 'Intente nuevamente.'})
        return JsonResponse(res_json, safe=False)

    etiquetas = dict(ParametroSistema.GRUPO_CHOICES)
    grupos_parametros = []
    for clave_grupo in grupos:
        filas = list(
            ParametroSistema.objects
            .filter(status=True, grupo=clave_grupo)
            .order_by('orden', 'clave')
        )
        if filas:
            grupos_parametros.append({
                'clave': clave_grupo,
                'etiqueta': etiquetas.get(clave_grupo, clave_grupo),
                'filas': filas,
            })

    data['grupos_parametros'] = grupos_parametros
    data['sin_parametros'] = not grupos_parametros
    return render(request, plantilla, data)
