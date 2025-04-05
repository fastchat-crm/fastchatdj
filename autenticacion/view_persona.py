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
from .forms import UserForm, PersonaForm, GrupoUserForm, ManageProfileForm
from django.contrib import messages

from .models import Usuario, PerfilAdministrativo, PerfilPersona


@login_required
@secure_module
def personasView(request):
    data = {
        'titulo': 'Clientes',
        'descripcion': 'Crear, Editar y Eliminar Clientes, Proveedores, etc.',
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
                        form.instance.get_client()
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
                        if PerfilAdministrativo.objects.filter(usuario=user).exists():
                            perfil_ = PerfilAdministrativo.objects.get(usuario=user)
                            perfil_.status = True
                            perfil_.save(request)
                            log(f"Perfil administrativo habilitado {user.get_full_name()}", request, "add")
                            messages.success(request, "Perfil administrativo habilitado.")
                        else:
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
                    user.is_active = False
                    user.status = False
                    user.save(request)
                    administrativo = user.get_admin()
                    administrativo.status = False
                    administrativo.save(request)
                    cliente = user.get_client()
                    cliente.status = False
                    cliente.save(request)
                    log(f"Inhabilito usuario {user.username} - {user.get_full_name()}", request, "del")
                    messages.success(request, "Inhabilitado correctamente.")
                    res_json = {"error": False}
                elif action == 'deleteperfiladm':
                    user = model.objects.get(pk=int(request.POST['id']))
                    perfil_ = PerfilAdministrativo.objects.get(usuario=user)
                    perfil_.status = False
                    perfil_.save(request)
                    log(f"Inhabilitado perfil administrativo {user.get_full_name()}", request, "del")
                    messages.success(request, "Perfil administrativo inhabilitado.")
                    res_json={"error":False}
                elif action == 'activate':
                    user = model.objects.get(pk=int(request.POST['id']))
                    user.is_active = True
                    user.status = True
                    user.save(request)
                    log(f"Habilito persona {user.username} - {user.get_full_name()}", request, "add")
                    messages.success(request, "Habilitado correctamente.")
                    res_json.append({'error': False,'reload': True})
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
                elif action == 'manage_profile':
                    user = model.objects.get(pk=int(request.POST['pk']))
                    form = ManageProfileForm(request.POST)
                    if not form.is_valid():
                        raise FormError(form)
                    user.is_active=form.cleaned_data['user_is_active']
                    user.status = form.cleaned_data['user_is_active']
                    user.save(request)
                    administrativo = user.get_admin()
                    administrativo.status = form.cleaned_data['perfil_administrativo']
                    administrativo.save(request)
                    cliente = user.get_client()
                    cliente.status = form.cleaned_data['perfil_cliente']
                    cliente.save(request)
                    log(f"Modifico perfil usuario {user.username} - {user.get_full_name()}", request, "change")
                    messages.success(request, "Modificado correctamente.")
                    res_json.append({'error': False,
                                     "to": redirectAfterPostGet(request)
                                     })
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

            elif action == 'manage_profile':
                data['id'] = id = int(request.GET['pk'])
                data['filtro'] = usuario = Usuario.objects.get(pk=id)
                titulo = f'Gestionar perfiles de {usuario.nombre_corto()}'
                form = ManageProfileForm()
                form.fields['perfil_administrativo'].initial = usuario.es_administrativo()
                form.fields['perfil_cliente'].initial = usuario.es_persona()
                form.fields['user_is_active'].initial = usuario.is_active
                data['form'] = form
                template = get_template("autenticacion/usuario/form_manage_profiles.html")
                return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})

        status_perfil, criterio, filtros, url_vars = request.GET.get('status_perfil', ''), request.GET.get('criterio', ''), Q(id__gt=0), ''
        id, documento = request.GET.get('id', ''), request.GET.get('documento', '')
        orderby = request.GET.get('orderby', '')

        order = 'last_name'
        if orderby:
            data["orderby"] = orderby
            url_vars += '&orderby=' + orderby
            if orderby == '1':
                order = 'last_name'
            elif orderby == '2':
                order = '-last_name'
            elif orderby == '3':
                order = 'date_joined'
            elif orderby == '4':
                order = '-date_joined'

        if id:
            data['id'] = id
            url_vars += f'&id={id}'
            filtros = filtros & Q(id=id)

        if documento:
            data['documento'] = documento
            url_vars += f'&documento={documento}'
            filtros = filtros & Q(documento=documento)

        if status_perfil:
            data['status_perfil'] = status_perfil
            url_vars += f'&status_perfil={status_perfil}'
            if status_perfil == '1':
                filtros = filtros & Q(status=True)
            if status_perfil == '0':
                filtros = filtros & Q(status=False)


        # Filtro por criterio (nombre, apellido, username)
        if criterio:
            data['criterio'] = criterio
            url_vars += f'&criterio={criterio}'
            palabras = criterio.strip().split()
            q_obj = Q()

            if len(palabras) == 1:
                palabra = palabras[0]
                q_obj |= Q(first_name__icontains=palabra)
                q_obj |= Q(last_name__icontains=palabra)
                q_obj |= Q(username__icontains=palabra)

            elif 2 <= len(palabras) <= 4:
                # Generar todas las combinaciones posibles de los términos
                from itertools import permutations

                for combo in permutations(palabras, len(palabras)):
                    # Vamos alternando los campos entre first_name y last_name
                    sub_q = Q()
                    for i, palabra in enumerate(combo):
                        if i % 2 == 0:
                            sub_q &= Q(first_name__icontains=palabra)
                        else:
                            sub_q &= Q(last_name__icontains=palabra)
                    q_obj |= sub_q

            else:
                # Fallback: solo usar las 3 primeras para evitar combinaciones excesivas
                q_obj &= (Q(first_name__icontains=palabras[0]) &
                          Q(last_name__icontains=palabras[1]) &
                          Q(last_name__icontains=palabras[2]))

            filtros &= q_obj
        listado = model.objects.filter(filtros).filter(perfilpersona__isnull=False).order_by('-id')
        data["url_vars"] = url_vars
        data["list_count"] = listado.count()
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'autenticacion/personas/listado.html', data)
