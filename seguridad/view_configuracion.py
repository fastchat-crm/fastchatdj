import sys
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect

from core.custom_models import FormError
from core.funciones import addData, salva_auditoria, secure_module, log, remover_caracteres_especiales_unicode, \
    generar_nombre
from core.funciones_adicionales import salva_logs
from seguridad.forms import ConfiguracionForm
from seguridad.models import Configuracion


@login_required
@secure_module
def configuracion(request):
    if Configuracion.objects.count() == 0:
        return redirect('/admin/seguridad/configuracion/add/')
    confi = Configuracion.get_instancia()

    data = {
        'titulo': 'Configuración del Sistema {}'.format(confi.nombre_empresa),
        'modulo': 'Configuración',
        'ruta': request.path,
        'fecha': str(date.today())
    }
    addData(request, data)
    model = Configuracion
    Formulario = ConfiguracionForm

    if request.method == 'POST':
        res_json = []
        if 'action' in request.POST:
            action = request.POST["action"]
            if action == 'estado_tika':
                from agents_ai.rag.tika_client import ping_tika
                url_prueba = (request.POST.get('url') or '').strip()
                if not url_prueba and not getattr(confi, 'tika_activo', False):
                    return JsonResponse({'state': True, 'estado': {
                        'activo': False, 'error': 'Servicio Tika desactivado en la configuración.'
                    }})
                estado = ping_tika(url=url_prueba or None)
                return JsonResponse({'state': True, 'estado': estado})
            try:
                with transaction.atomic():
                    if action == 'eliminar_icono':
                        c = model.objects.get(pk=int(request.POST["pk"]))
                        c.ico = ''
                        c.save(request)
                        log(f"Elimino icono {c.nombre_empresa}", request, "del")

                        return JsonResponse({'state': True})
                    elif action == 'eliminar_logo':
                        c = model.objects.get(pk=int(request.POST["pk"]))
                        c.logo_sistema = ''
                        c.save(request)
                        log(f"Elimino logo {c.nombre_empresa}", request, "del")
                        return JsonResponse({'state': True})
                    elif action == 'eliminar_logo_white':

                        c = model.objects.get(pk=int(request.POST["pk"]))
                        c.logo_sistema_white = ''
                        c.save(request)
                        log(f"Elimino logo {c.nombre_empresa}", request, "del")
                        return JsonResponse({'state': True})
                    elif action == 'eliminar_fondo_perfil':

                        c = model.objects.get(pk=int(request.POST["pk"]))
                        c.fondo_perfil = ''
                        c.save(request)
                        log(f"Elimino fondo perfil {c.nombre_empresa}", request, "del")
                        return JsonResponse({'state': True})
                    elif action == 'eliminar_banner_login':

                        c = model.objects.get(pk=int(request.POST["pk"]))
                        c.banner_login = ''
                        c.save(request)
                        log(f"Elimino banner login {c.nombre_empresa}", request, "del")
                        return JsonResponse({'state': True})
                    elif action == 'change':

                        form = Formulario(request.POST, request.FILES, instance=confi, request=request)
                        if form.is_valid():
                            if 'ico' in request.FILES:
                                file = request.FILES['ico']
                                nombredocumento = remover_caracteres_especiales_unicode('ico')
                                file._name = generar_nombre(nombredocumento, file._name)
                                form.instance.ico = file
                            if 'logo_sistema' in request.FILES:
                                file = request.FILES['logo_sistema']
                                nombredocumento = remover_caracteres_especiales_unicode('logo_sistema')
                                file._name = generar_nombre(nombredocumento, file._name)
                                form.instance.logo_sistema = file
                            if 'logo_sistema_white' in request.FILES:
                                file = request.FILES['logo_sistema_white']
                                nombredocumento = remover_caracteres_especiales_unicode('logo_sistema_white')
                                file._name = generar_nombre(nombredocumento, file._name)
                                form.instance.logo_sistema_white = file
                            if 'fondo_perfil' in request.FILES:
                                file = request.FILES['fondo_perfil']
                                nombredocumento = remover_caracteres_especiales_unicode('fondo_perfil')
                                file._name = generar_nombre(nombredocumento, file._name)
                                form.instance.fondo_perfil = file
                            if 'banner_login' in request.FILES:
                                file = request.FILES['banner_login']
                                nombredocumento = remover_caracteres_especiales_unicode('banner_login')
                                file._name = generar_nombre(nombredocumento, file._name)
                                form.instance.banner_login = file
                            if 'fondoprincipal' in request.FILES:
                                file = request.FILES['fondoprincipal']
                                nombredocumento = remover_caracteres_especiales_unicode('fondoprincipal')
                                file._name = generar_nombre(nombredocumento, file._name)
                                form.instance.fondoprincipal = file
                            if 'imagenprincipal' in request.FILES:
                                file = request.FILES['imagenprincipal']
                                nombredocumento = remover_caracteres_especiales_unicode('imagenprincipal')
                                file._name = generar_nombre(nombredocumento, file._name)
                                form.instance.imagenprincipal = file
                            if 'imagen_landing' in request.FILES:
                                file = request.FILES['imagen_landing']
                                nombredocumento = remover_caracteres_especiales_unicode('imagen_landing')
                                file._name = generar_nombre(nombredocumento, file._name)
                                form.instance.imagen_landing = file
                            form.save()
                            log(f"Edito Configuracion {form.instance.__str__()}", request, "change", obj=form.instance.id)

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
        return render(request, 'seguridad/configuracion/form.html', data)
    return None
