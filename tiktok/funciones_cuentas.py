"""Helpers de cuentas TikTok (view_cuentas).

La API de mensajes de TikTok (Business Messaging) está en beta y requiere
aprobación; mientras tanto las cuentas se pre-registran como
`SesionWhatsApp(proveedor='tiktok')` + `ConfigTikTok` para dejar listo el
canal (asesores, IA, horarios) y activarlo apenas llegue la aprobación.
"""
import secrets

from whatsapp.models import ConfigTikTok, SesionWhatsApp


def generar_verify_token():
    return secrets.token_urlsafe(30)[:40]


def guardar_cuenta(request, sesion=None):
    """Crea o actualiza la sesión TikTok + su ConfigTikTok."""
    nombre = (request.POST.get('nombre') or '').strip()
    username = (request.POST.get('username') or '').strip().lstrip('@')
    business_id = (request.POST.get('business_id') or '').strip()
    access_token = (request.POST.get('access_token') or '').strip()
    refresh_token = (request.POST.get('refresh_token') or '').strip()
    client_secret = (request.POST.get('client_secret') or '').strip()

    if not nombre or not username:
        return {'success': False, 'error': 'Nombre y @username son obligatorios.'}

    if sesion is None:
        session_id = f'tiktok-{username}'
        existente = SesionWhatsApp.objects.filter(session_id=session_id).first()
        if existente and existente.status:
            return {'success': False, 'error': 'Esa cuenta de TikTok ya está registrada.'}
        if existente and not existente.status:
            # Reactivar una sesión previamente eliminada (soft-delete) en vez de
            # chocar con el session_id único e impedir el re-registro.
            existente.status = True
            existente.activo = True
            existente.nombre = nombre
            existente.numero = username
            existente.estado = 'pendiente'
            existente.usuario = request.user
            existente.save()
            sesion = existente
            config = getattr(sesion, 'config_tiktok', None)
            if config is None:
                config = ConfigTikTok(sesion=sesion, webhook_verify_token=generar_verify_token())
            config.status = True
            config.username = username
            config.business_id = business_id
            if access_token:
                config.access_token = access_token
            if refresh_token:
                config.refresh_token = refresh_token
            if client_secret:
                config.client_secret = client_secret
            config.save()
            return {'success': True, 'sesion': sesion}
        sesion = SesionWhatsApp.objects.create(
            nombre=nombre,
            numero=username,
            proveedor='tiktok',
            session_id=session_id,
            usuario=request.user,
            estado='pendiente',
        )
        ConfigTikTok.objects.create(
            sesion=sesion,
            username=username,
            business_id=business_id,
            access_token=access_token,
            refresh_token=refresh_token,
            client_secret=client_secret,
            webhook_verify_token=generar_verify_token(),
        )
    else:
        sesion.nombre = nombre
        sesion.numero = username
        sesion.save()
        config = getattr(sesion, 'config_tiktok', None)
        if config is None:
            config = ConfigTikTok(sesion=sesion, webhook_verify_token=generar_verify_token())
        config.username = username
        config.business_id = business_id
        if access_token:
            config.access_token = access_token
        if refresh_token:
            config.refresh_token = refresh_token
        if client_secret:
            config.client_secret = client_secret
        config.save()

    return {'success': True, 'sesion': sesion}
