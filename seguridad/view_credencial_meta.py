import sys
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render

from core.custom_models import FormError
from core.funciones import addData, secure_module, log
from core.funciones_adicionales import salva_logs
from seguridad.forms import CredencialMetaAppForm
from seguridad.models import Configuracion, CredencialMetaApp


@login_required
@secure_module
def credencial_meta(request):
    confi = Configuracion.get_instancia()
    if not confi.pk:
        messages.warning(request, "Debe crear la Configuración del sistema antes de registrar credenciales Meta.")
        return render(request, 'seguridad/credencial_meta/form.html', {
            'titulo': 'Credenciales Meta App',
            'modulo': 'Credenciales Meta App',
            'ruta': request.path,
            'fecha': str(date.today()),
            'form': None,
            'pk': None,
        })

    credencial, _ = CredencialMetaApp.objects.get_or_create(
        configuracion=confi,
        defaults={'app_id': '', 'app_secret': ''},
    )

    data = {
        'titulo': 'Credenciales Meta App',
        'modulo': 'Credenciales Meta App',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)

    if request.method == 'POST':
        res_json = []
        action = request.POST.get('action', '')
        try:
            with transaction.atomic():
                if action == 'change':
                    form = CredencialMetaAppForm(request.POST, instance=credencial, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Edito Credencial Meta App {credencial.app_id}", request, "change", obj=credencial.id)
                        res_json.append({'error': False, "to": request.path})
                        messages.success(request, "Credenciales guardadas correctamente.")
                    else:
                        raise FormError(form)
        except ValueError as ex:
            res_json.append({'error': True, "message": str(ex)})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            salva_logs(request, __file__, request.method,
                       action, type(ex).__name__,
                       'Error on line {}'.format(sys.exc_info()[-1].tb_lineno), ex)
            res_json.append({'error': True, "message": "Intente Nuevamente"})
        return JsonResponse(res_json, safe=False)

    data['form'] = CredencialMetaAppForm(instance=credencial)
    data['pk'] = credencial.pk
    return render(request, 'seguridad/credencial_meta/form.html', data)
