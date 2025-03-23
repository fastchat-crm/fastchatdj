import sys
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect

from core.custom_models import FormError
from core.funciones import addData, secure_module, log
from core.funciones_adicionales import salva_logs
from seguridad.forms import ConfiguracionTerminosForm
from seguridad.models import Configuracion


@login_required
@secure_module
def confiTerminos(request):
    if Configuracion.objects.count() == 0:
        return redirect('/admin/seguridad/configuracion/add/')
    confi = Configuracion.get_instancia()

    data = {
        'titulo': 'Terminos y Condiciones {}'.format(confi.nombre_empresa),
        'modulo': 'Configuración',
        'ruta': request.path,
        'fecha': str(date.today())
    }
    addData(request, data)
    model = Configuracion
    Formulario = ConfiguracionTerminosForm
    nombre_app, nombre_model = model._meta.app_label, model._meta.model_name
    if request.method == 'POST':
        res_json = []
        if 'action' in request.POST:
            action = request.POST["action"]
            try:
                with transaction.atomic():
                    if action == 'change':
                            form = Formulario(request.POST, request.FILES, instance=confi, request=request)
                            if form.is_valid():
                                obj = form.save()
                                if request.FILES.get('archivo_manual'):
                                    obj.fecha_reg_manual = datetime.now()
                                    obj.save()
                                log(f"Modifico Terminos {form.instance.__str__()}", request, "change",obj=form.instance.id)
                                res_json.append({'error': False,
                                                 "to": request.path
                                                 })
                                messages.success(request, "Modificado correctamente.")
                            else:
                                raise FormError(form)
            except ValueError as ex:
                res_json.append({'error': True,
                                 "message": str(ex)
                                 })
            except FormError as ex:
                res_json.append(ex.dict_error)
            except Exception as ex:
                salva_logs(request, __file__, request.method,
                           action, type(ex).__name__,
                           'Error on line {}'.format(sys.exc_info()[-1].tb_lineno), ex)
                res_json.append({'error': True,
                                 "message": "Intente Nuevamente"
                                 })
        return JsonResponse(res_json, safe=False)
    elif request.method == 'GET':
        data["form"] = Formulario(instance=confi)
        data["pk"] = confi.pk
        return render(request, 'seguridad/configuracion/form_terminos.html', data)
