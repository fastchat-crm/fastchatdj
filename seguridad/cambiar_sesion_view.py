from django.contrib.auth import logout, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages
from django.http import HttpResponseForbidden

from core.funciones import log
from autenticacion.models import Usuario


@login_required
def cambiarSesionView(request):
    # Suplantación de sesión: SOLO superusuarios. Sin este guard, cualquier
    # visitante podía loguearse como el usuario que quisiera pasando ?pk=.
    if not request.user.is_superuser:
        return HttpResponseForbidden('No autorizado.')
    user_pk = request.GET['pk']
    path = request.GET['path']
    pkUserAnterior = request.user.pk
    userNuevaSesion = Usuario.objects.get(is_active=True, id=user_pk)
    log(f"Superuser {request.user.username} cambió sesión al usuario {userNuevaSesion.username}",
        request, "change", obj=userNuevaSesion.id)
    logout(request)
    login(request, userNuevaSesion)
    request.session['user_anterior'] = pkUserAnterior
    request.session['url'] = path
    perfil_nueva_sesion = userNuevaSesion.get_perfil_per()
    if perfil_nueva_sesion:
        request.session['perfilprincipal'] = perfil_nueva_sesion.id
    messages.success(request, "Ahora te encuentras logueado con el usuario {} - {}".format(userNuevaSesion.username,
                                                                                           userNuevaSesion.get_full_name()))
    return redirect('/panel/')


@login_required
def regresarSesionView(request):
    # Solo tiene sentido si esta sesión nació de una suplantación previa.
    if 'user_anterior' not in request.session:
        return HttpResponseForbidden('No autorizado.')
    userAnteriorSesion = Usuario.objects.get(is_active=True, id=request.session['user_anterior'])
    if 'path' in request.GET:
        path = request.GET['path']
    else:
        path = request.session['url']
    logout(request)
    login(request, userAnteriorSesion)
    perfil_anterior_sesion = userAnteriorSesion.get_perfil_per()
    if perfil_anterior_sesion:
        request.session['perfilprincipal'] = perfil_anterior_sesion.id
    messages.success(request, "Regresaste a tu sesión {} - {}".format(userAnteriorSesion.username,
                                                                      userAnteriorSesion.get_full_name()))
    return redirect(path)
