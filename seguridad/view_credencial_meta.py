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

# Toda la lógica que habla con Meta vive en el paquete `meta/`.
# Acá solo orquestamos la vista y delegamos.
from meta.autodetect import auto_detectar_meta
from meta.validacion import validar_credenciales


# Aliases privados para compat — apuntan al paquete . Si encontrás
# código viejo que importa estos nombres, podés actualizarlo a usar
#  directamente.
_auto_detectar_meta = auto_detectar_meta
_validar_credenciales = validar_credenciales




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
                elif action == 'validar':
                    app_id = (request.POST.get('app_id') or credencial.app_id or '').strip()
                    app_secret = (request.POST.get('app_secret') or '').strip() or (credencial.app_secret or '')
                    business_id = (request.POST.get('business_id') or credencial.business_id or '').strip()
                    system_user_id = (request.POST.get('system_user_id') or credencial.system_user_id or '').strip()
                    system_user_token = (request.POST.get('system_user_token') or '').strip() or (credencial.system_user_token or '')
                    config_id = (request.POST.get('config_id') or credencial.config_id or '').strip()
                    checks = _validar_credenciales(app_id, app_secret, business_id, system_user_id, system_user_token, config_id)
                    total_ok = sum(1 for c in checks if c['ok'])
                    log(f"Validar Credencial Meta App ({total_ok}/{len(checks)} OK)", request, "view", obj=credencial.id)
                    res_json.append({'error': False, 'checks': checks, 'total_ok': total_ok, 'total': len(checks)})
                elif action == 'auto_detect':
                    app_id = (request.POST.get('app_id') or '').strip()
                    app_secret = (request.POST.get('app_secret') or '').strip()
                    if not app_secret and credencial.pk:
                        app_secret = credencial.app_secret or ''
                    system_user_token = (request.POST.get('system_user_token') or '').strip()
                    if not system_user_token and credencial.pk:
                        system_user_token = credencial.system_user_token or ''
                    resultado = _auto_detectar_meta(app_id, app_secret, system_user_token)
                    if resultado.get('error'):
                        res_json.append({'error': True, 'message': resultado.get('message', 'Error')})
                    else:
                        log(f"Auto-detect Meta credenciales (app_id={app_id})", request, "view", obj=credencial.id)
                        res_json.append({'error': False, **resultado.get('detectado', {})})
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
