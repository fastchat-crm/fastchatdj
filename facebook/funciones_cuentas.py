"""Helpers de conexión de páginas de Facebook (view_cuentas).

La página se materializa como `SesionWhatsApp(proveedor='messenger')` +
`ConfigMessenger` OneToOne, para reusar todo el motor compartido
(conversaciones, IA, asignación de asesores, webhooks).
"""
import secrets

import requests

from meta.instagram import GRAPH_API_BASE, MessengerService
from whatsapp.models import ConfigMessenger, SesionWhatsApp


def generar_verify_token():
    return secrets.token_urlsafe(30)[:40]


def autodetectar_desde_token(access_token):
    """Extrae automáticamente page_id / page_name a partir de un token.

    Acepta token de usuario (lista sus páginas vía /me/accounts) o token de
    página (consulta /me directamente). Devuelve lista de candidatos:
    [{page_id, page_name, page_access_token}].
    """
    candidatos = []
    try:
        r = requests.get(
            f'{GRAPH_API_BASE}/me/accounts',
            params={
                'fields': 'id,name,access_token',
                'access_token': access_token,
            },
            timeout=15,
        )
        if r.ok:
            for page in (r.json().get('data') or []):
                if page.get('id'):
                    candidatos.append({
                        'page_id':           page.get('id'),
                        'page_name':         page.get('name') or '',
                        'page_access_token': page.get('access_token') or access_token,
                    })
        if candidatos:
            return {'success': True, 'candidatos': candidatos}

        r = requests.get(
            f'{GRAPH_API_BASE}/me',
            params={
                'fields': 'id,name',
                'access_token': access_token,
            },
            timeout=15,
        )
        if r.ok:
            page = r.json()
            if page.get('id'):
                candidatos.append({
                    'page_id':           page.get('id'),
                    'page_name':         page.get('name') or '',
                    'page_access_token': access_token,
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
            'error': 'No se encontró ninguna página de Facebook asociada al token. '
                     'Verifica los permisos pages_show_list, pages_messaging y '
                     'pages_manage_engagement. ' + detalle,
        }
    except Exception as e:
        return {'success': False, 'error': f'Error consultando Graph API: {e}'}


def guardar_cuenta(request, sesion=None):
    """Crea o actualiza la sesión Messenger + su ConfigMessenger."""
    nombre = (request.POST.get('nombre') or '').strip()
    page_id = (request.POST.get('page_id') or '').strip()
    page_name = (request.POST.get('page_name') or '').strip()
    access_token = (request.POST.get('access_token') or '').strip()

    if not nombre or not page_id:
        return {'success': False, 'error': 'Nombre y Page ID son obligatorios.'}
    if sesion is None and not access_token:
        return {'success': False, 'error': 'El Access Token es obligatorio al conectar la página.'}

    # Unicidad de page_id entre sesiones activas: sin esto, editar una sesión y
    # pegar el Page ID de otra empresa creaba dos ConfigMessenger con el mismo
    # page_id y el webhook enrutaba los mensajes a un tenant arbitrario.
    conflicto = ConfigMessenger.objects.filter(page_id=page_id, sesion__status=True)
    if sesion is not None:
        conflicto = conflicto.exclude(sesion=sesion)
    if conflicto.exists():
        return {'success': False, 'error': 'Ese Page ID ya está conectado en otra sesión.'}

    if sesion is None:
        session_id = f'messenger-{page_id}'
        existente = SesionWhatsApp.objects.filter(session_id=session_id).first()
        if existente and existente.status:
            return {'success': False, 'error': 'Esa página de Facebook ya está conectada.'}
        if existente and not existente.status:
            # Reactivar una sesión previamente eliminada (soft-delete) en vez de
            # chocar con el session_id único e impedir la reconexión.
            existente.status = True
            existente.activo = True
            existente.nombre = nombre
            existente.numero = page_name or page_id
            existente.estado = 'pendiente'
            existente.usuario = request.user
            existente.save()
            sesion = existente
            config = getattr(sesion, 'config_messenger', None)
            if config is None:
                config = ConfigMessenger(sesion=sesion, webhook_verify_token=generar_verify_token())
            config.status = True
            config.page_id = page_id
            config.page_name = page_name
            config.access_token = access_token
            config.save()
            probar_conexion(sesion)
            return {'success': True, 'sesion': sesion}
        sesion = SesionWhatsApp.objects.create(
            nombre=nombre,
            numero=page_name or page_id,
            proveedor='messenger',
            session_id=session_id,
            usuario=request.user,
            estado='pendiente',
        )
        ConfigMessenger.objects.create(
            sesion=sesion,
            page_id=page_id,
            page_name=page_name,
            access_token=access_token,
            webhook_verify_token=generar_verify_token(),
        )
    else:
        sesion.nombre = nombre
        sesion.numero = page_name or page_id
        sesion.session_id = f'messenger-{page_id}'
        sesion.save()
        config = getattr(sesion, 'config_messenger', None)
        if config is None:
            config = ConfigMessenger(sesion=sesion, webhook_verify_token=generar_verify_token())
        config.page_id = page_id
        config.page_name = page_name
        if access_token:
            config.access_token = access_token
        config.save()

    probar_conexion(sesion)
    return {'success': True, 'sesion': sesion}


def probar_conexion(sesion):
    """Valida el token contra Graph y actualiza estado/nombre de página."""
    res = MessengerService().obtener_perfil(sesion.session_id)
    config = getattr(sesion, 'config_messenger', None)
    if res.get('success'):
        perfil = res.get('perfil') or {}
        sesion.estado = 'conectado'
        sesion.save()
        if config and perfil.get('name'):
            config.page_name = perfil['name']
            config.save()
    else:
        sesion.estado = 'error'
        sesion.save()
    return res
