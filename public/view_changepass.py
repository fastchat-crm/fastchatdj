import asyncio

from core.correos_background import enviar_correo_html
from core.email_config import send_html_mail, conectar_cuenta
from core.funciones import addData, salva_auditoria, log
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

@login_required()
def changepass(request):
    confi = Configuracion.objects.first()
    data = {'titulo': 'Cambiar Contraseña', 'url_auth':True}
    addData(request, data)
    resp = {'resp': False}
    if request.method == 'POST':
        if 'passNew' in request.POST:
            try:
                with transaction.atomic():
                    user_ = Usuario.objects.get(id=request.user.id)
                    pass_ = request.POST['passNew']
                    user_.set_password(pass_)
                    user_.passmoodle = user_.set_password_moodle(pass_)
                    user_.cambio_clave = False
                    user_.save()
                    login(request, user_)
                    log(f"Cambio contraseña manual {user_.get_full_name()}", request, "change")
                    resp['resp'] = True
                    resp['url'] = '/'
                    messages.success(request, f"Su contraseña actualizada con éxito")
            except Exception as ex:
                resp['error'] = str(ex)
            return JsonResponse(resp)
        else:
            data['error'] = 'Credenciales Incorrectas'
            return JsonResponse(data)

    elif request.method == 'GET':
        return render(request, 'public/seguridad/cambiarclave.html', data)
