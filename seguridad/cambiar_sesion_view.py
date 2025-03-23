from django.contrib.auth import logout, login
from django.shortcuts import redirect
from django.contrib import messages
from core.funciones import secure_module
from autenticacion.models import Usuario


def cambiarSesionView(request):
    user_pk = request.GET['pk']
    path = request.GET['path']
    pkUserAnterior = request.user.pk
    userNuevaSesion = Usuario.objects.get(is_active=True, id=user_pk)
    logout(request)
    login(request, userNuevaSesion)
    request.session['user_anterior'] = pkUserAnterior
    request.session['url'] = path
    if userNuevaSesion.get_perfil_per():
        request.session['perfilprincipal'] = userNuevaSesion.get_perfil_per()
    messages.success(request, "Ahora te encuentras logueado con el usuario {} - {}".format(userNuevaSesion.username,
                                                                                           userNuevaSesion.get_full_name()))
    return redirect('/panel/')


def regresarSesionView(request):
    userAnteriorSesion = Usuario.objects.get(is_active=True, id=request.session['user_anterior'])
    if 'path' in request.GET:
        path = request.GET['path']
    else:
        path = request.session['url']
    logout(request)
    login(request, userAnteriorSesion)
    if userAnteriorSesion.get_perfil_per():
        request.session['perfilprincipal'] = userAnteriorSesion.get_perfil_per()
    messages.success(request, "Regresaste a tu sesión {} - {}".format(userAnteriorSesion.username,
                                                                      userAnteriorSesion.get_full_name()))
    return redirect(path)
