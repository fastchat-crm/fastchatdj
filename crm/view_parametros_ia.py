"""Parámetros IA — página de gobernanza runtime (`/crm/parametros-ia/`).

Edita la tabla `ParametroSistema` (clave→valor cacheado 60 s). Los agentes toman
estos valores a nivel plataforma vía `crm.ia_config._valor_plataforma`, así que
cambiarlos aquí ajusta el comportamiento del motor sin tocar código.
"""
import sys
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, secure_module, log
from core.funciones_adicionales import salva_logs
from seguridad.models import ParametroSistema


def _validar(parametro, crudo):
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


@login_required
@secure_module
def parametros_ia_view(request):
    data = {
        'titulo': 'Parámetros IA',
        'modulo': 'Parámetros IA',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)

    if request.method == 'POST':
        res_json = []
        action = request.POST.get('action', '')
        try:
            with transaction.atomic():
                if action == 'guardar':
                    editables = ParametroSistema.objects.filter(status=True, editable=True)
                    errores = []
                    for parametro in editables:
                        campo = 'param_{}'.format(parametro.pk)
                        if campo not in request.POST:
                            continue
                        crudo = (request.POST.get(campo) or '').strip()
                        ok, msg = _validar(parametro, crudo)
                        if not ok:
                            errores.append('{}: {}'.format(parametro.etiqueta, msg))
                            continue
                        parametro.valor = crudo
                        parametro.save(request)
                    if errores:
                        raise ValueError(' · '.join(errores))
                    log('Editó Parámetros IA', request, 'change')
                    messages.success(request, 'Parámetros IA actualizados correctamente.')
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

    grupos_parametros = []
    for clave_grupo, etiqueta_grupo in ParametroSistema.GRUPO_CHOICES:
        filas = list(
            ParametroSistema.objects.filter(status=True, grupo=clave_grupo).order_by('orden', 'clave')
        )
        if filas:
            grupos_parametros.append({
                'clave': clave_grupo,
                'etiqueta': etiqueta_grupo,
                'filas': filas,
            })
    data['grupos_parametros'] = grupos_parametros
    data['sin_parametros'] = not grupos_parametros
    return render(request, 'crm/parametros_ia/listado.html', data)
