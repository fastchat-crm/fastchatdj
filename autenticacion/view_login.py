from autenticacion.models import Usuario
from fastchatdj import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.timezone import activate
from core.funciones import addData
from seguridad.models import SessionUser, Empresa

activate(settings.TIME_ZONE)


def login_session(request):
    data = {'titulo': 'Iniciar Sesión', }
    addData(request, data)

    if request.method == 'POST':
        datos = {'resp': False}
        action = request.POST.get('action')
        password = request.POST['password']
        if Usuario.objects.filter(username=request.POST['usuario'].lower()).exists():
            user = authenticate(username=request.POST['usuario'].lower(),
                                password=password)
            if user is not None:
                if user.status:
                    if user.is_active:
                        if user.is_superuser or user.is_staff:
                            login(request, user)
                            empresa_selected = Empresa.objects.filter(status=True).order_by('-id').first()
                            request.session['empresa_selected'] = empresa_selected.id if empresa_selected else None
                            SessionUser.nuevo(request)
                            url = request.POST.get('next_url', '/panel/')
                            datos = {"resp": True, "to": url}
                        else:
                            datos['error'] = 'Este usuario a sido desvinculado del sistema'
                    else:
                        datos['error'] = 'Usuario a sido desvinculado del sistema'
                else:
                    datos['error'] = 'Este usuario a sido desvinculado del sistema'
            else:
                datos['error'] = 'Credenciales Incorrectas'
        else:
            datos['error'] = 'Usuario no existe'
        return JsonResponse(datos)
    elif request.method == 'GET':
        if not request.user.is_authenticated:
            data["next_url"] = request.GET.get('next', False)
            return render(request, 'autenticacion/login.html', data)
        else:
            return redirect('/panel/')


def logout_user(request):
    logout(request)
    return redirect('/')