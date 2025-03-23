import os
import time
from django.core import mail
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect
from django.utils.html import strip_tags
from core.funciones import addData, salva_auditoria, secure_module, generar_nombre
from autenticacion.models import Usuario
from datetime import timedelta, datetime



@login_required
def perfil(request):
    data = {
        'titulo': "Editar Perfil",
        'modulo': 'Perfil',
        'ruta': request.path,
    }
    addData(request, data)

    if request.method == 'POST':
        res_json = []
        if 'action' in request.POST:
            action = request.POST['action']
            try:
                with transaction.atomic():

                    if action == 'changeperfil':
                        try:
                            usuario = Usuario.objects.get(pk=int(request.user.pk))
                            usuario.first_name = request.POST['first_name']
                            usuario.last_name = request.POST['last_name']
                            usuario.telefono = request.POST['telefono']
                            usuario.ciudad_id =  request.POST['ciudad']
                            fecha_nacimiento_ = request.POST["fechanacimiento"]
                            usuario.fecha_nacimiento = fecha_nacimiento_
                            usuario.save()
                            messages.success(request, 'Información de perfil actualizada')
                            res_json.append({'error': False, "to": request.path})
                        except ValueError as e:
                            messages.error(request, str(e))
                        except Exception as ex:
                            res_json.append({"error": True, "message": ex})
                        return JsonResponse(res_json, safe=False)

                    if action == 'changepass':
                        try:
                            usuario = Usuario.objects.get(pk=int(request.user.pk))
                            user_login = authenticate(username=usuario.username, password=request.POST['clave_actual'])
                            if user_login is not None:
                                if request.POST['clave_actual'] != request.POST['clave']:
                                    user_login.set_password(request.POST['clave'])
                                    user_login.save()
                                    messages.success(request, 'Contraseña cambiada satisfactoriamente.')
                                    res_json.append({'error': False, "to": f'{request.path}?action=changepass'})
                                else:
                                    res_json.append({"error": True, "message": 'La contraseña nueva debe ser diferente a la contraseña actual'})
                                    return JsonResponse(res_json, safe=False)
                            else:
                                res_json.append({"error": True, "message": 'Contraseña actual incorrecta'})
                                return JsonResponse(res_json, safe=False)
                        except ValueError as e:
                            messages.error(request, str(e))
                        except Exception as ex:
                            res_json.append({"error": True, "message": ex})
                        return JsonResponse(res_json, safe=False)

            except Exception as ex:
                messages.error(request, ex)
            return redirect(request.path, data)
    else:
        if 'action' in request.GET:
            data['action'] = action = request.GET['action']
            if action == 'changepass':
                data['titulo'] = 'Cambiar Contraseña'
                return render(request, 'public/perfil/changepass.html', data)
    data['fecha_nacimiento'] = str(request.user.fecha_nacimiento)
    return render(request, 'public/perfil/perfil.html', data)
