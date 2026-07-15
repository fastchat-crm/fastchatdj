import logging
import time

from django.contrib import messages
from django.contrib.auth import password_validation
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.html import strip_tags
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.timezone import activate

from autenticacion.models import Usuario
from core.correos_background import enviar_correo_html
from core.funciones import addData
from fastchatdj import settings
from fastchatdj.settings import LOGIN_URL
from seguridad.models import Configuracion

activate(settings.TIME_ZONE)

logger = logging.getLogger(__name__)


def _usuario_por_uid(uidb64):
    """Decodifica el uid del enlace y devuelve el Usuario, o None si es inválido."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        return Usuario.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, Usuario.DoesNotExist):
        return None


def recuperar(request):
    confi = Configuracion.objects.first()
    data = {'titulo': 'Recuperar Clave'}
    addData(request, data)

    if request.method == 'POST' and 'usuario' in request.POST:
        usuario = (request.POST.get('usuario') or '').strip()
        email_ingresado = (request.POST.get('email') or '').strip()
        # Mensaje SIEMPRE genérico: no revela si el usuario existe, si está
        # activo, ni si el correo coincide (evita enumeración de cuentas).
        aviso_generico = ('Si los datos coinciden con una cuenta activa, te enviamos '
                          'un correo con un enlace para restablecer tu contraseña. '
                          'Revisa tu bandeja de entrada.')

        # Rate-limit: máximo 5 intentos cada 15 min por IP y por usuario.
        from django.core.cache import cache
        ip = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
              or request.META.get('REMOTE_ADDR', 'anon'))
        bloqueado = False
        for clave in (f'recuperar_ip_{ip}', f'recuperar_user_{usuario.lower()}'):
            intentos = cache.get(clave, 0)
            if intentos >= 5:
                bloqueado = True
            cache.set(clave, intentos + 1, 15 * 60)
        if bloqueado:
            messages.success(request, aviso_generico)
            return redirect(LOGIN_URL)

        try:
            us = Usuario.objects.filter(username=usuario).first()
            # Solo se envía el enlace si TODO coincide; cualquier fallo cae al
            # mismo aviso genérico sin distinguir la causa. NO se cambia la clave
            # aquí: el token de un solo uso se consume al confirmar la nueva clave,
            # así nadie que sepa usuario+email puede dejar a la víctima fuera.
            if us and us.is_active and email_ingresado and us.email == email_ingresado:
                uid = urlsafe_base64_encode(force_bytes(us.pk))
                token = default_token_generator.make_token(us)
                reset_url = request.build_absolute_uri(
                    reverse('auth_reset_confirmar', kwargs={'uidb64': uid, 'token': token})
                )
                datos = {
                    'sucursal': confi.nombre_empresa if confi else '',
                    'usuario': str(us.username),
                    'reset_url': reset_url,
                    'fecha': str(time.strftime("%Y-%m-%d %H:%M")),
                    'correo': str(settings.EMAIL_HOST_USER),
                }
                html_message = render_to_string('email/recuperar.html', datos)
                plain_message = strip_tags(html_message)
                enviar_correo_html({
                    "subject": 'Restablece tu contraseña',
                    "plain_message": plain_message,
                    "from_email": confi.nombre_empresa if confi else '',
                    "to": [str(us.email)],
                    "html_message": html_message,
                })
        except Exception:
            logger.exception('Fallo en solicitud de recuperación de clave')

        messages.success(request, aviso_generico)
        return redirect(LOGIN_URL)

    return render(request, 'autenticacion/recuperar.html', data)


def reset_confirmar(request, uidb64, token):
    data = {'titulo': 'Restablecer contraseña'}
    addData(request, data)

    us = _usuario_por_uid(uidb64)
    token_valido = bool(us) and us.is_active and default_token_generator.check_token(us, token)
    data['token_valido'] = token_valido

    if not token_valido:
        # No distinguimos "usuario inexistente" de "token vencido/usado": mismo
        # aviso para no filtrar información ni el estado del token.
        return render(request, 'autenticacion/reset_confirmar.html', data)

    if request.method == 'POST':
        p1 = request.POST.get('password1') or ''
        p2 = request.POST.get('password2') or ''
        if p1 != p2:
            messages.error(request, 'Las contraseñas no coinciden.')
            return render(request, 'autenticacion/reset_confirmar.html', data)
        try:
            password_validation.validate_password(p1, us)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
            return render(request, 'autenticacion/reset_confirmar.html', data)

        # set_password cambia el hash de la clave → el token queda invalidado
        # automáticamente (un solo uso, sin necesidad de tabla extra).
        us.set_password(p1)
        if hasattr(us, 'cambio_clave'):
            us.cambio_clave = False
        us.save()
        messages.success(request, 'Tu contraseña fue actualizada. Ya puedes iniciar sesión.')
        return redirect(LOGIN_URL)

    return render(request, 'autenticacion/reset_confirmar.html', data)
