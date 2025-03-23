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
        #'auditoria': AudiUsuarioTabla.objects.filter(usuario__id=request.user.pk).order_by('-id')[:10],
        'auditoria': LogEntry.objects.filter(user__id=request.user.pk).order_by('-id')[:10],
    }
    addData(request, data)

    if request.method == 'POST':
        if 'action' in request.POST:
            action = request.POST['action']
            try:
                with transaction.atomic():
                    if action == 'add':
                        u = Usuario.objects.get(id=request.user.id)
                        if u.check_password(request.POST['clave_actual']):
                            if request.POST['clave_actual'] != request.POST['clave']:
                                u.set_password(request.POST['clave'])
                                tomarclave = (request.POST['clave'])
                                u.save(request)

                                log(f"Contraseña Cambiada {u.username} - {u.get_full_name()}", request, "add", obj=u.id)
                                messages.success(request, 'Contraseña cambiada satisfactoriamente.')
                                return redirect('/')
                            else:
                                messages.warning(request, 'Por favor ingrese una contraseña diferente.')
                        else:
                            messages.warning(request, 'Contraseña actual no es la correcta.')

                    if action == 'editar':
                        u = Usuario.objects.get(id=request.user.pk)
                        if 'foto' in request.FILES:
                            u.foto = request.FILES['foto']
                            u.save(request)
                        fecha_nacimiento = request.POST.get('fecha_nacimiento')
                        u.fecha_nacimiento = fecha_nacimiento
                        if fecha_nacimiento == "":
                            u.fecha_nacimiento = None
                        u.save()
                        log(f"Información editada {u.username} - {u.get_full_name()}", request, "change", obj=u.id)
                        messages.success(request, 'Información cambiada satisfactoriamente.')
                    if action == 'cerrar_sesion':
                        su = SessionUser.objects.get(pk=int(request.POST['pk']),
                                                     user_id=request.user.pk)
                        Session.objects.get(session_key=su.session.session_key).delete()
                        return JsonResponse({"resp": True})
            except ValueError as ex:
                messages.error(request, str(ex))
            except Exception as ex:
                messages.error(request, ex)

            return redirect(ruta, data)
    sesiones = SessionUser.objects.filter(user_id=request.user.pk, session__expire_date__gt=timezone.now()).annotate(es_la_actual=Case(
        When(session__session_key=request.session.session_key, then=True),
        default=Value('0'),
        output_field=BooleanField()
    )).order_by('-es_la_actual', '-pk')
    data['sesiones'] = sesiones
    return render(request, 'autenticacion/perfil.html', data)
