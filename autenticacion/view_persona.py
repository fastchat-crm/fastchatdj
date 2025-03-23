import sys
from datetime import date
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template

from area_geografica.models import Provincia, Ciudad
from core.custom_models import FormError
from core.funciones import addData, paginador, salva_auditoria, secure_module, redirectAfterPostGet, codnombre, log
from core.funciones_adicionales import salva_logs
from .forms import UserForm, PersonaForm, GrupoUserForm
from django.contrib import messages

from .models import Usuario, PerfilAdministrativo, PerfilPersona


@login_required
@secure_module
def personasView(request):
    data = {
        'titulo': 'Personas',
        'modulo': 'Autenticación',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    model = Usuario
    Formulario = PersonaForm

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':

                    form = Formulario(request.POST, request.FILES, request=request)
                    if form.is_valid():
                        if 'ciudad' in request.POST:
                            form.instance.ciudad_id = request.POST['ciudad']
                        username_ = codnombre(request.POST['first_name'], request.POST['last_name'])
                        form.instance.username = username_
                        form.instance.set_password(request.POST["documento"])
                        obj = form.save()
                        perfil_ = PerfilPersona(usuario_id=form.instance.id)
                        perfil_.save()
                        log(f"Registro nueva persona {obj.username} - {obj.get_full_name()}", request, "add", obj=form.instance.id)

                        messages.success(request, "Agregado correctamente.")
                        res_json.append({'error': False,
                                         "to": redirectAfterPostGet(request)
                                         })
                    else:
                        raise FormError(form)

                elif action == 'change':

                    user = model.objects.get(pk=int(request.POST['pk']))

                    form = Formulario(request.POST, request.FILES, instance=user, request=request)
                    if form.is_valid():
                        if 'ciudad' in request.POST:
                            form.instance.ciudad_id = request.POST['ciudad']
                        form.save()
                        if form.instance.get_perfil_per():
                            perfil_ = PerfilPersona.objects.get(id=form.instance.get_perfil_per().id)
                        else:
                            perfil_ = PerfilPersona(usuario=form.instance)
                        perfil_.save()
                        log(f"Edito persona {form.instance.username} - {form.instance.get_full_name()}", request,
                            "change", obj=form.instance.id)
                        messages.success(request, "Modificado correctamente.")
                        res_json.append({'error': False,
                                         "to": redirectAfterPostGet(request)
                                         })
                    else:
                        raise FormError(form)

                elif action == 'crearperfiladm':
                    user = model.objects.get(pk=int(request.POST['id']))
                    if not user.es_administrativo():
                        perfil_ = PerfilAdministrativo(usuario=user)
                        perfil_.save(request)
                        log(f"Creo perfil administrativo {user.get_full_name()}", request, "add")
                        messages.success(request, "Perfil administrativo habilitado.")
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise NameError(f"Usuario ya cuenta con perfil administrativo")
                elif action == 'changegroup':
                    filtro = model.objects.get(pk=int(request.POST['pk']))
                    form = GrupoUserForm(request.POST, request.FILES, instance=filtro, request=request)
                    if form.is_valid() and filtro:
                        form.save()
                        log(f"Cambio grupo usuario {filtro.username} - {filtro.get_full_name()}", request, "change")
                        res_json.append({'error': False, "reload": True})
                    else:
                        res_json.append({'error': True,
                                         "form": [{k: v[0]} for k, v in form.errors.items()],
                                         "message": "Error en el formulario"
                                         })
                elif action == 'delete':
                    user = model.objects.get(pk=int(request.POST['id']))
                    qs_anterior = list(model.objects.filter(id=user.id).values())
                    user.is_active = False
                    user.status = False
                    user.save(request)
                    log(f"Inhabilitado persona  {user.username} - {user.get_full_name()}", request,
                        "del")

                    messages.success(request, "Inhabilitado correctamente.")
                    res_json={"error":False}

                elif action == 'activate':

                    user = model.objects.get(pk=int(request.POST['id']))
                    user.is_active = True
                    user.status = True
                    user.save(request)
                    log(f"Habilito persona {user.username} - {user.get_full_name()}", request, "add")
                    messages.success(request, "Habilitado correctamente.")

                    return redirect(redirectAfterPostGet(request))
                elif action == 'change_password':

                    user = model.objects.get(pk=int(request.POST['pk']))
                    user.set_password(request.POST["password"])
                    user.save(request)
                    log(f"Cambio contraseña persona {user.username} - {user.get_full_name()}", request, "change")
                    messages.success(request, "Contraseña del usuario {} / {} cambiada".format(user.get_full_name(),
                                                                                               user.username))

                    return redirect(redirectAfterPostGet(request))
                elif action == 'eliminar_foto':

                    user = model.objects.get(pk=int(request.POST['pk']))
                    user.foto = ""
                    user.save(request)
                    log(f"Elimino foto {user.username} - {user.get_full_name()}", request, "del")
                    return JsonResponse({'state': True})

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
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
            if action == 'add':

                form = Formulario()
                form.fields['provincia'].queryset = Provincia.objects.none()
                form.fields['ciudad'].queryset = Ciudad.objects.none()
                data["form"] = form
                return render(request, 'autenticacion/usuario/form.html', data)

            elif action == 'change':

                pk = int(request.GET['pk'])
                user = model.objects.get(pk=pk)
                data["pk"] = pk
                data["object"] = user
                form = Formulario(instance=user)
                if user.ciudad:
                    form.fields['provincia'].queryset = Provincia.objects.filter(status=True,
                                                                                 id=user.ciudad.provincia.id)
                    form.fields['ciudad'].queryset = Ciudad.objects.filter(status=True, id=user.ciudad.id)
                else:
                    form.fields['provincia'].queryset = Provincia.objects.none()
                    form.fields['ciudad'].queryset = Ciudad.objects.none()
                data["form"] = form
                return render(request, 'autenticacion/personas/form.html', data)

            elif action == 'changegroup':
                try:
                    data['id'] = id = int(request.GET['id'])
                    data['filtro'] = filtro = Usuario.objects.get(pk=id)
                    form = GrupoUserForm(instance=filtro)
                    data['form'] = form
                    template = get_template("autenticacion/usuario/formmodal.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    pass

            elif action == 'ver':

                pk = int(request.GET['pk'])
                user = model.objects.get(pk=pk)
                data["pk"] = pk
                data["object"] = user
                data["form"] = Formulario(instance=user, ver=True)
                return render(request, 'autenticacion/personas/form.html', data)

        criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(id__gt=0), ''
        if criterio:
            filtros = filtros & (Q(username__icontains=criterio) | Q(first_name__icontains=criterio) |
                                     Q(last_name__icontains=criterio) | Q(documento__icontains=criterio))
            data["criterio"] = criterio
            url_vars += '&criterio=' + criterio
        listado = model.objects.filter(filtros).filter(perfilpersona__isnull=False, status=True).order_by('-id')
        data["url_vars"] = url_vars
        data["list_count"] = listado.count()
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'autenticacion/personas/listado.html', data)
