"""Helpers de conexión de cuentas Instagram (view_cuentas).

La cuenta se materializa como `SesionWhatsApp(proveedor='instagram')` +
`ConfigInstagram` OneToOne, para reusar todo el motor compartido
(conversaciones, IA, asignación de asesores, webhooks).
"""
import secrets

import requests

from meta.instagram import GRAPH_API_BASE, InstagramService
from whatsapp.models import ConfigInstagram, SesionWhatsApp


def generar_verify_token():
    return secrets.token_urlsafe(30)[:40]


def autodetectar_desde_token(access_token):
    """Extrae automáticamente page_id / ig_user_id / username a partir de un token.

    Acepta token de usuario (lista sus páginas vía /me/accounts) o token de
    página (consulta /me directamente). Devuelve lista de candidatos:
    [{page_id, page_name, page_access_token, ig_user_id, username}].
    """
    candidatos = []
    try:
        r = requests.get(
            f'{GRAPH_API_BASE}/me/accounts',
            params={
                'fields': 'id,name,access_token,instagram_business_account{id,username}',
                'access_token': access_token,
            },
            timeout=15,
        )
        if r.ok:
            for page in (r.json().get('data') or []):
                ig = page.get('instagram_business_account') or {}
                if ig.get('id'):
                    candidatos.append({
                        'page_id':           page.get('id'),
                        'page_name':         page.get('name'),
                        'page_access_token': page.get('access_token') or access_token,
                        'ig_user_id':        ig.get('id'),
                        'username':          ig.get('username') or '',
                    })
        if candidatos:
            return {'success': True, 'candidatos': candidatos}

        r = requests.get(
            f'{GRAPH_API_BASE}/me',
            params={
                'fields': 'id,name,instagram_business_account{id,username}',
                'access_token': access_token,
            },
            timeout=15,
        )
        if r.ok:
            page = r.json()
            ig = page.get('instagram_business_account') or {}
            if ig.get('id'):
                candidatos.append({
                    'page_id':           page.get('id'),
                    'page_name':         page.get('name'),
                    'page_access_token': access_token,
                    'ig_user_id':        ig.get('id'),
                    'username':          ig.get('username') or '',
                })
        if candidatos:
            return {'success': True, 'candidatos': candidatos}
        detalle = ''
        try:
            detalle = (r.json().get('error') or {}).get('message', '')
        except Exception:
            detalle = r.text[:200]
        return {
            'success': False,
            'error': 'No se encontró una cuenta Instagram Business vinculada al token. '
                     'Verifica los permisos instagram_basic y pages_show_list. ' + detalle,
        }
    except Exception as e:
        return {'success': False, 'error': f'Error consultando Graph API: {e}'}


def guardar_cuenta(request, sesion=None):
    """Crea o actualiza la sesión Instagram + su ConfigInstagram."""
    nombre = (request.POST.get('nombre') or '').strip()
    ig_user_id = (request.POST.get('ig_user_id') or '').strip()
    page_id = (request.POST.get('page_id') or '').strip()
    username = (request.POST.get('username') or '').strip().lstrip('@')
    access_token = (request.POST.get('access_token') or '').strip()

    if not nombre or not ig_user_id or not page_id:
        return {'success': False, 'error': 'Nombre, IG User ID y Page ID son obligatorios.'}
    if sesion is None and not access_token:
        return {'success': False, 'error': 'El Access Token es obligatorio al conectar la cuenta.'}

    # Unicidad de ig_user_id entre sesiones activas: sin esto, editar una sesión
    # y pegar el IG User ID de otra empresa creaba dos ConfigInstagram con el
    # mismo id y el webhook enrutaba los DMs a un tenant arbitrario.
    conflicto = ConfigInstagram.objects.filter(ig_user_id=ig_user_id, sesion__status=True)
    if sesion is not None:
        conflicto = conflicto.exclude(sesion=sesion)
    if conflicto.exists():
        return {'success': False, 'error': 'Ese IG User ID ya está conectado en otra sesión.'}

    if sesion is None:
        session_id = f'instagram-{ig_user_id}'
        existente = SesionWhatsApp.objects.filter(session_id=session_id).first()
        if existente and existente.status:
            return {'success': False, 'error': 'Esa cuenta de Instagram ya está conectada.'}
        if existente and not existente.status:
            # Reactivar una sesión previamente eliminada (soft-delete) en vez de
            # chocar con el session_id único e impedir la reconexión.
            existente.status = True
            existente.activo = True
            existente.nombre = nombre
            existente.numero = username or ig_user_id
            existente.estado = 'pendiente'
            existente.usuario = request.user
            existente.save()
            sesion = existente
            config = getattr(sesion, 'config_instagram', None)
            if config is None:
                config = ConfigInstagram(sesion=sesion, webhook_verify_token=generar_verify_token())
            config.status = True
            config.ig_user_id = ig_user_id
            config.page_id = page_id
            config.username = username
            config.access_token = access_token
            config.save()
            probar_conexion(sesion)
            return {'success': True, 'sesion': sesion}
        sesion = SesionWhatsApp.objects.create(
            nombre=nombre,
            numero=username or ig_user_id,
            proveedor='instagram',
            session_id=session_id,
            usuario=request.user,
            estado='pendiente',
        )
        ConfigInstagram.objects.create(
            sesion=sesion,
            ig_user_id=ig_user_id,
            page_id=page_id,
            username=username,
            access_token=access_token,
            webhook_verify_token=generar_verify_token(),
        )
    else:
        sesion.nombre = nombre
        sesion.numero = username or ig_user_id
        sesion.session_id = f'instagram-{ig_user_id}'
        sesion.save()
        config = getattr(sesion, 'config_instagram', None)
        if config is None:
            config = ConfigInstagram(sesion=sesion, webhook_verify_token=generar_verify_token())
        config.ig_user_id = ig_user_id
        config.page_id = page_id
        config.username = username
        if access_token:
            config.access_token = access_token
        config.save()

    probar_conexion(sesion)
    return {'success': True, 'sesion': sesion}


def probar_conexion(sesion):
    """Valida el token contra Graph y actualiza estado/username de la sesión."""
    res = InstagramService().obtener_perfil(sesion.session_id)
    config = getattr(sesion, 'config_instagram', None)
    if res.get('success'):
        perfil = res.get('perfil') or {}
        sesion.estado = 'conectado'
        sesion.save()
        if config and perfil.get('username'):
            config.username = perfil['username']
            config.save()
    else:
        sesion.estado = 'error'
        sesion.save()
    return res
