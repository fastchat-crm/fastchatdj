import asyncio

from core.correos_background import enviar_correo_html
from core.email_config import send_html_mail, conectar_cuenta
from core.funciones import addData
from fastchatdj import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.timezone import activate
from autenticacion.models import Usuario

activate(settings.TIME_ZONE)
from django.template.loader import render_to_string
from random import choice
from django.core import mail
from django.contrib.auth import authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.html import strip_tags
from seguridad.models import *
import time
from django.utils.timezone import activate


def recordarusername(request):
    confi = Configuracion.objects.first()
    data = {'titulo': 'Recuperar Nombre de Usuario', 'url_auth':True}
    addData(request, data)
    resp = {'resp': False}
    if request.method == 'POST':
        if 'email' in request.POST:
            email = request.POST['email']
            try:
                user = Usuario.objects.filter(email=email)
                if user.exists():
                    us = user.first()
                    with transaction.atomic():
                        if us.is_active and not us.es_administrativo():
                            datos = {
                                'sucursal': confi.nombre_empresa,
                                'usuario': us,
                                'fecha': str(time.strftime("%Y-%m-%d %H:%M")),
                                'correo': str(settings.EMAIL_HOST_USER)
                            }
                            subject = 'Recordar nombre de usuario'
                            to = us.email
                            send_html_mail(subject, "email/restaurar.html", datos, [to], [], [])
                            resp['resp'] = True
                            resp['url'] = '/'
                            messages.success(request,'Recordatorio enviado, revise su dirección de correo electrónico.')
                        else:
                            resp['error'] = 'Usuario esta deshabilitado'
                else:
                    resp['error'] = 'No existe usuarios asociados a este correo {} '.format(email)
            except Exception as ex:
                resp['error'] = str(ex)
            return JsonResponse(resp)
        else:
            data['error'] = 'Credenciales Incorrectas'
            return JsonResponse(data)

    elif request.method == 'GET':
        if request.user.username != "":
            return redirect('/')
        # return render(request, 'public/seguridad/recuperar_username.html', data)
        return render(request, 'public/seguridad/recover_username.html', data)