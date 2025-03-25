from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.db.models import When, Value, BooleanField, Case
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect
from django.utils import timezone

from core.constantes import TIMEZONE_CHOICES
from core.funciones import addData, salva_auditoria, secure_module, log
from seguridad.models import AudiUsuarioTabla, SessionUser
from .models import Usuario
from django.contrib.admin.models import LogEntry


@login_required
@secure_module
def perfilView(request):
    ruta = request.path
    data = {
        'titulo': "Perfil",
        'modulo': 'Perfil',
        'ruta': ruta,
        'auditoria': LogEntry.objects.filter(user__id=request.user.pk).order_by('-id')[:10],
    }
    addData(request, data)

    if request.method == 'POST':
        if 'action' in request.POST:
            res_json = []
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
            except ValueError as ex:
                messages.error(request, str(ex))
            except Exception as ex:
                messages.error(request, ex)

            return redirect(ruta, data)
    return render(request, 'autenticacion/perfil.html', data)
