import sys
from datetime import date
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.template.loader import get_template
from openpyxl.reader.excel import load_workbook

from area_geografica.models import Ciudad, Provincia
from core.custom_models import FormError
from core.funciones import addData, paginador, salva_auditoria, secure_module, redirectAfterPostGet, codnombre, log
from core.funciones_adicionales import salva_logs
from .forms import UserForm, GrupoUserForm, ManageProfileForm, ChangeUsernameForm, CargarUsuariosForm

from django.contrib import messages

from .models import Usuario, PerfilAdministrativo, PerfilPersona
from .view_persona import personasView


@login_required
@secure_module
def usuarioView(request):
    data = {
        'titulo': 'Control de Usuarios Administrativos',
        'descripcion': 'Crear, Editar y Eliminar Administradores',
        'modulo': 'Autenticación',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    model = Usuario
    Formulario = UserForm

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
                        perfil_ = PerfilAdministrativo(usuario_id=form.instance.id)
                        perfil_.save()
                        log(f"Habilito usuario {obj.username} - {obj.get_full_name()}", request, "add")
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
                        form.instance.get_admin()
                        log(f"Edito usuario {form.instance.username} - {form.instance.get_full_name()}", request,
                            "change")

                        messages.success(request, "Modificado correctamente.")
                        res_json.append({'error': False,
                                         "to": redirectAfterPostGet(request)
                                         })
                    else:
                        raise FormError(form)
                elif action == 'crearperfilpersona':
                    user = model.objects.get(pk=int(request.POST['id']))
                    group = Group.objects.get(name='Cliente')
                    user.groups.add(group)
                    if not user.es_persona():
                        if PerfilPersona.objects.filter(usuario=user).exists():
                            perfil_ = PerfilPersona.objects.get(usuario=user)
                            perfil_.status = True
                            perfil_.save(request)
                            log(f"Activo perfil cliente usuario {user.username} - {user.get_full_name()}", request, "change")
                            messages.success(request, "Perfil persona habilitado.")
                        else:
                            perfil_ = PerfilPersona(usuario=user)
                            perfil_.save(request)
                            log(f"Creo perfil cliente usuario {user.username} - {user.get_full_name()}", request, "add")
                            messages.success(request, "Perfil persona habilitado.")
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise NameError(f"Usuario ya cuenta con perfil persona")
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
                    user.is_superuser = False
                    user.is_staff = False
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
                    perfil_ = PerfilPersona.objects.get(usuario=user)
                    perfil_.status = False
                    perfil_.save(request)
                    log(f"Inhabilitado perfil cliente {user.get_full_name()}", request, "del")
                    messages.success(request, "Perfil administrativo inhabilitado.")
                    res_json={"error":False}
                elif action == 'activate':
                    user = model.objects.get(pk=int(request.POST['id']))
                    user.is_active = True
                    user.is_staff = True
                    user.status = True
                    user.save(request)
                    log(f"Habilito usuario {user.username} - {user.get_full_name()}", request, "add")
                    messages.success(request, "Habilitado correctamente.")
                    res_json.append({'error': False,'reload': True})
                elif action == 'change_password':
                    user = model.objects.get(pk=int(request.POST['pk']))
                    user.set_password(request.POST["password"])
                    user.save(request)
                    log(f"Modifico contraseña usuario {user.username} - {user.get_full_name()}", request, "change")

                    messages.success(request, "Contraseña del usuario {} / {} cambiada".format(user.get_full_name(),
                                                                                               user.username))
                    res_json.append({'error': False,'reload': True})
                elif action == 'eliminar_foto':
                    user = model.objects.get(pk=int(request.POST['pk']))
                    user.foto = ""
                    user.save(request)
                    log(f"Elimino usuario {user.username} - {user.get_full_name()}", request, "del")
                    return JsonResponse({'state': True})
                elif action == 'manage_profile':
                    user = model.objects.get(pk=int(request.POST['pk']))
                    form = ManageProfileForm(request.POST)
                    if not form.is_valid():
                        raise FormError(form)
                    user.is_active=form.cleaned_data['user_is_active']
                    user.is_staff=form.cleaned_data['user_is_staff']
                    user.status = form.cleaned_data['user_is_active']
                    user.save(request)
                    administrativo = user.get_admin()
                    administrativo.status = form.cleaned_data['perfil_administrativo']
                    administrativo.save(request)
                    cliente = user.get_client(form.cleaned_data['perfil_cliente'])
                    cliente.status = form.cleaned_data['perfil_cliente']
                    cliente.save(request)
                    log(f"Modifico perfil usuario {user.username} - {user.get_full_name()}", request, "change")
                    messages.success(request, "Modificado correctamente.")
                    res_json.append({'error': False,
                                     "to": redirectAfterPostGet(request)
                                     })
                elif action == 'change_username':
                    user = model.objects.get(pk=int(request.POST['pk']))
                    form = ChangeUsernameForm(request.POST)
                    if not form.is_valid():
                        raise FormError(form)
                    if Usuario.objects.filter(username=form.cleaned_data['username']).exists():
                        raise ValueError("Ya existe un usuario con ese nombre de usuario.")
                    user.username = form.cleaned_data['username']
                    user.save(request)
                    log(f"Modifico nombre de usuario {user.username} - {user.get_full_name()}", request, "change")
                    messages.success(request, "Modificado correctamente.")
                    res_json.append({'error': False,
                                     "reload": True
                                     })
                elif action == 'uploadUsers':
                    form = CargarUsuariosForm(request.POST, request.FILES)
                    if form.is_valid():
                        archivo = request.FILES['archivo']
                        workbook = load_workbook(archivo)
                        sheet = workbook[workbook.sheetnames[0]]
                        linea_lectura = 1
                        creados = 0
                        editado = 0
                        for rowx in sheet.iter_rows(min_row=2):
                            cols = [cell.value for cell in rowx]

                            if len(cols) < 3:
                                continue

                            apellidos = (cols[0] or '').strip().upper()
                            nombres = (cols[1] or '').strip().upper()
                            cedula = str(cols[2] or '').strip()

                            if not (nombres and apellidos and cedula):
                                continue

                            telefono = str(cols[3] or '').strip()
                            email = (cols[4] or '').strip()

                            if not Usuario.objects.filter(username=cedula).exists():
                                user = Usuario.objects.create_user(
                                    username=cedula,
                                    email=email,
                                    password=cedula,
                                    first_name=nombres,
                                    last_name=apellidos,
                                    telefono=telefono,
                                    documento=cedula
                                )
                                creados += 1
                            else:
                                user = Usuario.objects.get(username=cedula)
                                user.documento = cedula
                                user.first_name = nombres
                                user.last_name = apellidos
                                user.telefono = telefono
                                user.email = email
                                editado += 1
                                user.status = True
                                user.is_active = True
                                user.save(request)
                            _success, resp = user.register_staff_user()
                            if not _success:
                                raise NameError(f"Error al registrar usuario {nombres} {apellidos}: {resp}")
                        log(f"Subió archivo de usuarios con {creados} creados y {editado} editados", request, "add")
                        messages.success(request, f"Creados: {creados}, Editados: {editado}")
                        res_json.append({'error': False, "reload": True})
                    else:
                        raise FormError(form)

        except ValueError as ex:
            res_json.append({'error': True,
                             "message": str(ex)
                             })
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            res_json.append({'error': True,
                             "message": f"Intente Nuevamente {ex}"
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
                return render(request, 'autenticacion/usuario/form.html', data)
            elif action == 'changegroup':
                try:
                    data['id'] = id = int(request.GET['pk'])
                    data['filtro'] = filtro = Usuario.objects.get(pk=id)
                    titulo= f'Gestionar Grupos de {filtro.nombre_corto()}'
                    form = GrupoUserForm(instance=filtro)
                    data['form'] = form
                    template = get_template("autenticacion/usuario/formmodal.html")
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo':titulo })
                except Exception as ex:
                    pass
            elif action == 'ver':
                pk = int(request.GET['pk'])
                user = model.objects.get(pk=pk)
                data["pk"] = pk
                data["object"] = user
                data["form"] = Formulario(instance=user, ver=True)
                return render(request, 'autenticacion/usuario/form.html', data)
            elif action =='manage_profile':
                data['id'] = id = int(request.GET['pk'])
                data['filtro'] = usuario = Usuario.objects.get(pk=id)
                titulo = f'Gestionar perfiles de {usuario.nombre_corto()}'
                form = ManageProfileForm()
                form.fields['perfil_administrativo'].initial = usuario.es_administrativo()
                form.fields['perfil_cliente'].initial = usuario.es_persona()
                form.fields['user_is_active'].initial = usuario.is_active
                form.fields['user_is_staff'].initial = usuario.is_staff
                data['form'] = form
                template = get_template("autenticacion/usuario/form_manage_profiles.html")
                return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
            elif action =='change_username':
                try:
                    data['id'] = id = int(request.GET['pk'])
                    data['filtro'] = usuario = Usuario.objects.get(pk=id)
                    titulo = f'Cambiar nombre de usuario de {usuario.nombre_corto()}'
                    form = ChangeUsernameForm()
                    data['form'] = form
                    template = get_template("autenticacion/usuario/form_change_username.html")
                    return JsonResponse({"result": True, 'data': template.render(data), 'titulo': titulo})
                except Exception as ex:
                    return JsonResponse({"result": False, "message": f"Error: {ex}."})
            elif action == 'uploadUsers':
                try:
                    form = CargarUsuariosForm()
                    data['form'] = form
                    template = get_template("autenticacion/usuario/cargausuarios.html")
                    return JsonResponse({"result": True, 'data': template.render(data)})
                except Exception as ex:
                    return JsonResponse({"result": False, "message": f"Error: {ex}."})

        grupoid, status_perfil, criterio, filtros, url_vars = request.GET.getlist('grupoid', ''), request.GET.get('status_perfil', ''), request.GET.get('criterio', ''), Q(id__gt=0), ''
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
            elif status_perfil == '0':
                filtros = filtros & Q(status=False)
            elif status_perfil == '2':
                filtros = filtros & Q(is_superuser=True)
            elif status_perfil == '3':
                filtros = filtros & Q(is_staff=True)

        if grupoid:
            data["grupoid"] = grupoid = list(map(lambda x: int(x), grupoid))
            for scl in grupoid:
                url_vars += "&grupoid={}".format(scl)
            filtros = filtros & Q(groups__in=grupoid)

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


        listado = model.objects.filter(filtros).filter(perfiladministrativo__isnull=False).order_by(order)
        data["url_vars"] = url_vars
        data["list_count"] = listado.count()
        data['gruposrol'] = Group.objects.all()
        paginador(request, listado, 20, data, url_vars)
        return render(request, 'autenticacion/usuario/listado.html', data)
