from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.db import transaction
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse

from area_geografica.models import Provincia, Pais, Ciudad
from autenticacion.models import Usuario, PerfilPersona
from autenticacion.recuperar_clave import generarclave
from core.email_config import send_html_mail
from core.funciones import addData, get_decrypt, generar_nombre, convertir_fecha_invertida, codnombre
from fastchatdj import settings
from fastchatdj.settings import ID_GRUPO_CLIENTE

from seguridad.models import *


def registro(request):
    data = {'titulo': 'Registro', 'url_auth':True}
    addData(request, data)
    if request.method == 'POST':
        with transaction.atomic():
            try:
                if not request.user.is_authenticated:
                    if not 'terminoscondiciones' in request.POST:
                        raise ValueError("Para continuar, debe aceptar los términos y condiciones & políticas de privacidad.")
                    if Usuario.objects.filter(email=request.POST['email'], status=True, is_active=True).exists():
                        raise ValueError("Correo electrónico ya se encuentra en uso por otro usuario..")
                    if Usuario.objects.filter(documento=request.POST['documento'], status=True, is_active=True).exists():
                        raise ValueError("Número de identidad ya se encuentra en uso por otro usuario..")
                    else:
                        correo_, password_ = request.POST['email'].strip(), request.POST['documento'].strip()
                        nombre_, apellido_ = request.POST['first_name'], request.POST['last_name']
                        telefono_ = request.POST['telefono']
                        ciudad_ = Ciudad.objects.get(id=request.POST['ciudad'])
                        username_ = codnombre(nombre_, apellido_)
                        tpdocumento = "PASAPORTE"
                        if len(password_) == 10:
                            tpdocumento = "CEDULA"
                        if len(password_) == 13:
                            tpdocumento = "RUC"
                        usuario_ = Usuario.objects.create_user(username=username_, first_name=nombre_, last_name=apellido_,
                                                               telefono=telefono_, tipo_documento=tpdocumento, ciudad=ciudad_,
                                                               sexo='NINGUNO', email=correo_, password=password_, documento=password_, is_active=True, is_staff=False, is_superuser=False)
                        perfil_ = PerfilPersona.objects.create(usuario=usuario_)
                        perfil_.save()
                        grupo_ = Group.objects.get(pk=ID_GRUPO_CLIENTE)
                        if not grupo_.user_set.filter(id=usuario_.id).exists():
                            grupo_.user_set.add(usuario_)
                            grupo_.save()
                        datos = {
                            'sucursal': request.config.nombre_empresa,
                            'instancia': usuario_,
                            'url': f'{data["DOMINIO_DEL_SISTEMA"]}',
                            'correo': str(settings.EMAIL_HOST_USER)
                        }
                        subject = f'¡Registro completado!'
                        to = correo_
                        send_html_mail(subject, "email/registro_usuario.html", datos, [to], [], [])
                        messages.success(request, 'Registro completado, revise su bandeja de correo electronico para obtener sus credenciales de acceso.')
                        user = authenticate(username=username_, password=password_)
                        if user is not None:
                            login(request, user)
                            su = SessionUser.nuevo(request)
                        response = JsonResponse({'respuesta': True, 'to': request.POST.get('next') or '/'})
                        return HttpResponse(response.content)
                else:
                    response = JsonResponse({'respuesta': False, 'mensaje': 'Ya se encuentra autenticado, cierre sesión para registrarse.'})
                    return HttpResponse(response.content)

            except ValueError as ex:
                transaction.set_rollback(True)
                response = JsonResponse({'respuesta': False, 'mensaje': str(ex)})
                return HttpResponse(response.content)
            except Exception as ex:
                transaction.set_rollback(True)
                response = JsonResponse({'respuesta': False, "mensaje": f"Intente nuevamente. {ex}"})
                return HttpResponse(response.content)
    elif request.method == 'GET':
        des, data['next'] = get_decrypt(request.GET.get('next'))
        if not des:
            data['next'] = request.GET.get('next')
        if request.user.is_authenticated:
            return redirect('/')
        return render(request, 'public/seguridad/registrarse.html', data)