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


def generarclave():
    longitud = 6
    valores = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    p = ""
    p = p.join([choice(valores) for i in range(longitud)])
    return p


def restaurar(request):
    confi = Configuracion.objects.first()
    data = {'titulo': 'Recuperar Clave', 'url_auth':True}
    addData(request, data)
    resp = {'resp': False}
    if request.method == 'POST':
        if 'email' in request.POST:
            email = request.POST['email']
            try:
                if Usuario.objects.filter(email=email, perfiladministrativo__isnull=True).exists():
                    user = Usuario.objects.filter(email=email, perfiladministrativo__isnull=True).first()
                    with transaction.atomic():
                        if user.is_active and not user.es_administrativo():
                            if user.email:
                                codigo = generarclave()
                                user.set_password(str(codigo))
                                user.save()
                                datos = {
                                    'sucursal': confi.nombre_empresa,
                                    'usuario': str(user.username),
                                    'codigo': str(codigo),
                                    'fecha': str(time.strftime("%Y-%m-%d %H:%M")),
                                    'correo': str(settings.EMAIL_HOST_USER)
                                }
                                subject = 'Cambio de contraseña'
                                to = user.email
                                send_html_mail(subject, "email/recuperar.html", datos, [to], [], [])
                                resp['resp'] = True
                                resp['url'] = '/'
                                messages.success(request, 'Clave restaurada, revise su dirección de correo electrónico.')
                            else:
                                resp['error'] = 'El correo ingresado, no esta asociado.'
                        else:
                            resp['error'] = 'El correo ingresado, no esta asociado.'
                else:
                    resp['error'] = 'El correo ingresado, no esta asociado.'
                    return JsonResponse(resp)
            except Exception as ex:
                resp['error'] = str(ex)
            return JsonResponse(resp)
        else:
            data['error'] = 'Credenciales Incorrectas'
            return JsonResponse(data)

    elif request.method == 'GET':
        # if request.user.username != "":
        #     return redirect('/')
        return render(request, 'public/seguridad/restaurar.html', data)
