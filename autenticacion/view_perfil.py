import sys

from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.db.models import When, Value, BooleanField, Case
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect
from django.utils import timezone

from area_geografica.models import Ciudad, Provincia
from core.constantes import TIMEZONE_CHOICES
from core.funciones import addData, salva_auditoria, secure_module, log, remover_caracteres_especiales_unicode, \
    generar_nombre
from seguridad.models import AudiUsuarioTabla, SessionUser
from .forms import EditPersonaForm
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
                        usuario = Usuario.objects.get(pk=int(request.user.pk))
                        usuario.first_name = request.POST['first_name']
                        usuario.last_name = request.POST['last_name']
                        usuario.telefono = request.POST['telefono']
                        usuario.ciudad_id =  request.POST['ciudad']
                        fecha_nacimiento_ = request.POST["fecha_nacimiento"]
                        usuario.fecha_nacimiento = fecha_nacimiento_
                        usuario.direccion = request.POST["direccion"]
                        usuario.save()
                        messages.success(request, 'Información de perfil actualizada')
                        res_json.append({'error': False, 'reload': True})
                    if action == 'changepass':
                        usuario = Usuario.objects.get(pk=int(request.user.pk))
                        user_login = authenticate(username=usuario.username, password=request.POST['clave_actual'])
                        if user_login is not None:
                            if request.POST['clave_actual'] != request.POST['clave']:
                                user_login.set_password(request.POST['clave'])
                                user_login.save()
                                messages.success(request, 'Contraseña cambiada satisfactoriamente.')
                                res_json.append({'error': False, 'reload': True})
                            else:
                                res_json.append({"error": True, "message": 'La contraseña nueva debe ser diferente a la contraseña actual'})
                        else:
                            res_json.append({"error": True, "message": 'Contraseña actual incorrecta'})
                    if action == 'updatephoto':
                        usuario = Usuario.objects.get(pk=int(request.user.pk))
                        if 'foto' in request.FILES:
                            file = request.FILES['foto']
                            nombredocumento = remover_caracteres_especiales_unicode(f"{usuario.username}_{file._name}")
                            file._name = generar_nombre(nombredocumento, file._name)
                            usuario.foto = file
                            usuario.save()
                            messages.success(request, 'Foto de perfil actualizada exitosamente')
                            res_json.append({'error': False, 'reload': True})
                        else:
                            res_json.append({"error": True, "message": 'No se ha seleccionado ninguna imagen'})
            except Exception as ex:
                res_json.append({"error": True, "message": f"{ex}"})
            return JsonResponse(res_json, safe=False)
    try:
        formPersona = EditPersonaForm(instance=request.user)
        if request.user.ciudad:
            if request.user.ciudad.provincia:
                formPersona.fields['ciudad'].queryset = Ciudad.objects.filter(provincia=request.user.ciudad.provincia).order_by('nombre')
                formPersona.fields['provincia'].queryset = Provincia.objects.filter(pais=request.user.ciudad.provincia.pais).order_by('nombre')
                formPersona.fields['ciudad'].initial = request.user.ciudad.pk
                formPersona.fields['provincia'].initial = request.user.ciudad.provincia.pk
                formPersona.fields['pais'].initial = request.user.ciudad.provincia.pais.pk
        else:
            formPersona.fields['ciudad'].queryset = Ciudad.objects.none()
            formPersona.fields['provincia'].queryset = Provincia.objects.none()
        data['formPersona'] = formPersona
        return render(request, 'autenticacion/perfil.html', data)
    except Exception as ex:
        msg_error_linea = f"{ex} - Code ({ex.__class__.__name__}) - Line {sys.exc_info()[-1].tb_lineno}"
        return JsonResponse({"error": True, "message": msg_error_linea})
