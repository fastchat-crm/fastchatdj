import base64
from django.contrib import messages
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from core.funciones import addData, ip_client_address, get_decrypt, datetime, get_client_ip, log
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.timezone import activate
from fastchatdj import settings
from fastchatdj.settings import EMAIL_HOST_USER, URL_GENERAL
from autenticacion.models import Usuario
from seguridad.models import Empresa

activate(settings.TIME_ZONE)


def login_tienda(request):
    data = {'titulo': 'Iniciar Sesión', 'url_auth':True}
    addData(request, data)
    if request.method == 'GET':
        des, data['next'] = get_decrypt(request.GET.get('next'))
        if not des:
            data['next'] = request.GET.get('next')
        if request.user.username != "":
            return redirect('/')
        return render(request, 'public/seguridad/login.html', data)
    datos = {'resp': False}
    try:
        addData(request, data)
        if request.method == 'POST':
            usuario_, password = request.POST['usuario'], request.POST['password']
            if Usuario.objects.filter(username=usuario_).exists():
                user = authenticate(username=usuario_, password=password)
                if user is not None:
                    if user.is_active:
                        login(request, user)
                        request.session['empresa_selected'] = Empresa.objects.filter(status=True).order_by('-id').first()
                        datos['resp'] = True
                        ipreal = get_client_ip(request)
                        ip = ipreal if ipreal != '127.0.0.1' else '127.0.0.1'
                        log(f"Ha iniciado sesion desde la ip: {ip}", request, "add", obj='login')
                        if request.POST.get('next'):
                            datos['redirect'] = request.POST.get('next')
                    else:
                        datos['error'] = 'Este usuario a sido desvinculado del sistema'
                else:
                    datos['error'] = 'Credenciales Incorrectas'
            else:
                datos['error'] = 'Usuario no existe'
            return JsonResponse(datos)
    except Exception as ex:
        datos['error'] = 'Credenciales Incorrectas'
        messages.error(request, ex)
        return JsonResponse(datos)


def logout_tienda(request):
    logout(request)
    return redirect('/')
