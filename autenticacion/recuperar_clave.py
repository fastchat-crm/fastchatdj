from random import choice

from autenticacion.models import Usuario
from core.correos_background import enviar_correo_html
from fastchatdj import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect
from django.utils.html import strip_tags
from core.funciones import addData
from fastchatdj.settings import LOGIN_URL
from seguridad.models import Configuracion
import time
from django.utils.timezone import activate

activate(settings.TIME_ZONE)
from django.template.loader import render_to_string


def generarclave():
    longitud = 8
    valores = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    p = ""
    p = p.join([choice(valores) for i in range(longitud)])
    return p


def recuperar(request):
    confi = Configuracion.objects.first()
    data = {'titulo': 'Recuperar Clave',}

    addData(request, data)

    if request.method == 'POST':
        if 'usuario' in request.POST:
            usuario = request.POST['usuario']
            try:
                user = Usuario.objects.filter(username=usuario)
                if Usuario.objects.filter(username=usuario).exists():
                    us = Usuario.objects.get(username=usuario)
                    with transaction.atomic():
                        if user.exists():
                            if us.is_active:
                                if us.email == request.POST['email']:
                                    codigo = generarclave()
                                    us.set_password(str(codigo))
                                    us.save()
                                    datos = {
                                        'sucursal': confi.nombre_empresa,
                                        'usuario': str(us.username),
                                        'codigo': str(codigo),
                                        'fecha': str(time.strftime("%Y-%m-%d %H:%M")),
                                        'correo': str(settings.EMAIL_HOST_USER)
                                    }
                                    subject = 'CAMBIO DE CONTRASEÑA!'
                                    html_message = render_to_string('email/recuperar.html', datos)
                                    plain_message = strip_tags(html_message)
                                    from_email = confi.nombre_empresa
                                    to = str(us.email)
                                    enviar_correo_html(
                                        {"subject": subject, "plain_message": plain_message, "from_email": from_email,
                                         "to": [to], "html_message": html_message})
                                    messages.success(request,'Clave restaurada, revise su dirección de correo electronico.')
                                else:
                                    messages.error(request,'El correo ingresado, no esta asociado a esta cuenta.')
                            else:
                                messages.error(request, 'Usuario ' + usuario + ' esta deshabilitado.')
                        else:
                            messages.error(request, 'Usuario ' + usuario + ' no existe.')
            except Exception as ex:
                messages.error(request, ex)
            return redirect(LOGIN_URL)
        else:
            return render(request, "autenticacion/recuperar.html", data)
    else:
        return render(request, 'autenticacion/recuperar.html', data)
