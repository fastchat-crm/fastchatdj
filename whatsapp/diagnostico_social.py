"""Diagnóstico de conectividad para sesiones sociales (Instagram, Messenger, TikTok).

On-demand (no persiste nada nuevo salvo `SesionWhatsApp.estado`): corre chequeos
secuenciales y devuelve una lista de pasos con causa concreta y solución accionable,
para que el operador entienda POR QUÉ una sesión no conecta y cómo resolverlo.

Devuelve: {'ok': bool, 'resumen': str, 'pasos': [{'label','ok','detalle','solucion'}]}
Cada red arma su propia card/menú; esta lógica de backend es compartida.
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def _paso(label, ok, detalle='', solucion=''):
    return {'label': label, 'ok': bool(ok), 'detalle': detalle, 'solucion': solucion}


def _causa_graph(error):
    """Traduce el error crudo de Graph (dict con code/subcode/message, o string
    de red) a (causa_legible, solucion_accionable)."""
    if isinstance(error, dict):
        code = error.get('code')
        sub = error.get('error_subcode')
        msg = error.get('message') or 'Error de la API de Meta'
        if code == 190:
            return ('Token inválido o expirado',
                    'Reconectá la cuenta y pegá un Page Access Token de larga duración vigente.')
        if code in (10, 200, 803, 3) or sub in (33,):
            return ('Falta un permiso o la app no tiene acceso',
                    'La app de Meta necesita los permisos aprobados (pages_messaging, '
                    'instagram_manage_messages, pages_show_list) y la página vinculada a la cuenta.')
        if code == 100:
            return ('Identificador (Page ID / IG user ID) incorrecto',
                    'Volvé a autodetectar desde el token para recuperar el ID correcto.')
        if code in (4, 17, 32, 613):
            return ('Límite de solicitudes alcanzado (rate limit)',
                    'Esperá unos minutos antes de reintentar.')
        if code == 368:
            return ('Cuenta o página restringida por Meta',
                    'Revisá el estado de la página en Meta Business Manager (bloqueo por políticas).')
        return (msg, 'Revisá el detalle y el estado de la app en Meta.')
    # error como string → red / config
    texto = str(error or '')
    if 'config' in texto:
        return ('No hay configuración cargada para la sesión',
                'Volvé a crear o editar la sesión con sus credenciales.')
    return ('No se pudo contactar la API (red o timeout)',
            'Verificá la conectividad del servidor y que la API sea accesible desde aquí.')


def _diag_meta(sesion, canal):
    """Diagnóstico para Instagram (canal='instagram') y Messenger (canal='messenger')."""
    from meta.instagram import InstagramService, MessengerService
    config = getattr(sesion, 'config_instagram' if canal == 'instagram' else 'config_messenger', None)
    id_attr = 'ig_user_id' if canal == 'instagram' else 'page_id'
    id_label = 'IG User ID' if canal == 'instagram' else 'Page ID'
    servicio = InstagramService() if canal == 'instagram' else MessengerService()
    webhook_url = '/instagram/webhook/' if canal == 'instagram' else '/facebook/webhook/'

    pasos = []
    if not config:
        pasos.append(_paso('Configuración de la cuenta', False,
                           'La sesión no tiene credenciales cargadas.',
                           'Editá la sesión y cargá el token de acceso.'))
        return {'ok': False, 'resumen': 'Sin configuración', 'pasos': pasos}
    pasos.append(_paso('Configuración de la cuenta', True, 'Credenciales cargadas.'))

    tiene_token = bool((config.access_token or '').strip())
    pasos.append(_paso('Token de acceso', tiene_token,
                       'Token presente.' if tiene_token else 'No hay token de acceso.',
                       '' if tiene_token else 'Editá la sesión y pegá un Page Access Token válido.'))

    id_val = getattr(config, id_attr, None)
    pasos.append(_paso(id_label, bool(id_val),
                       f'{id_label}: {id_val}' if id_val else f'Falta el {id_label}.',
                       '' if id_val else 'Autodetectá desde el token para recuperar el identificador.'))

    api_ok = False
    if tiene_token and id_val:
        res = servicio.obtener_perfil(sesion.session_id)
        api_ok = bool(res.get('success'))
        if api_ok:
            perfil = res.get('perfil') or {}
            nombre = perfil.get('username') or perfil.get('name') or ''
            pasos.append(_paso('Respuesta de la API', True,
                               f'Conectado como {nombre}.' if nombre else 'La API respondió correctamente.'))
        else:
            causa, solucion = _causa_graph(res.get('error'))
            pasos.append(_paso('Respuesta de la API', False, causa, solucion))
    else:
        pasos.append(_paso('Respuesta de la API', False,
                           'No se probó: falta token o identificador.',
                           'Completá los pasos anteriores.'))

    verif = bool(getattr(config, 'webhook_verificado_en', None))
    pasos.append(_paso('Webhook verificado', verif,
                       'El webhook está verificado.' if verif else 'El webhook aún no fue verificado por Meta.',
                       '' if verif else f'Configurá la URL {webhook_url} en el panel de Meta y verificá el token.'))

    # Solo PROMOVEMOS a 'conectado' cuando la API respondió OK. No degradamos a
    # 'error' desde acá: un fallo transitorio (rate limit, timeout de red) al
    # momento del diagnóstico marcaría como rota una sesión sana. El estado de
    # error lo fija el flujo real (envío/recepción) o la acción "Probar conexión".
    if api_ok and sesion.estado != 'conectado':
        sesion.estado = 'conectado'
        sesion.save(update_fields=['estado'])

    ok = api_ok
    resumen = 'Conexión correcta' if ok else 'La sesión no puede conectar — revisá los pasos marcados.'
    return {'ok': ok, 'resumen': resumen, 'pasos': pasos}


def _diag_tiktok(sesion):
    """Diagnóstico para TikTok. La Business Messaging API está en beta: no hay
    prueba de perfil en vivo, así que se valida credenciales, expiración y el
    último error registrado."""
    config = getattr(sesion, 'config_tiktok', None)
    pasos = []
    if not config:
        pasos.append(_paso('Configuración de la cuenta', False,
                           'La sesión no tiene credenciales TikTok cargadas.',
                           'Editá la sesión y cargá los datos de la cuenta Business.'))
        return {'ok': False, 'resumen': 'Sin configuración', 'pasos': pasos}
    pasos.append(_paso('Configuración de la cuenta', True, 'Credenciales cargadas.'))

    tiene_token = bool((config.access_token or '').strip())
    pasos.append(_paso('Token de acceso', tiene_token,
                       'Token presente.' if tiene_token else 'No hay token OAuth.',
                       '' if tiene_token else 'Completá el flujo OAuth de TikTok para obtener el token.'))

    expira = getattr(config, 'token_expira_en', None)
    if expira:
        vigente = expira > timezone.now()
        pasos.append(_paso('Vigencia del token', vigente,
                           f'Vence el {expira:%Y-%m-%d %H:%M}.' if vigente else 'El token está vencido.',
                           '' if vigente else 'Renová el token (refresh) o reconectá la cuenta.'))

    id_val = getattr(config, 'business_id', None) or getattr(config, 'open_id', None)
    pasos.append(_paso('Identificador del negocio', bool(id_val),
                       f'ID: {id_val}' if id_val else 'Falta business_id / open_id.',
                       '' if id_val else 'Reconectá la cuenta Business para obtener el identificador.'))

    err = (getattr(config, 'error_mensaje', '') or '').strip()
    if err:
        pasos.append(_paso('Último error registrado', False, err,
                           'Revisá el mensaje: suele indicar token vencido o permiso faltante.'))

    verif = bool(getattr(config, 'webhook_verificado_en', None))
    secret = bool((getattr(config, 'client_secret', '') or '').strip())
    pasos.append(_paso('Webhook verificado', verif,
                       'Webhook verificado.' if verif else 'El webhook aún no fue verificado.',
                       '' if verif else 'Configurá la URL /tiktok/webhook/ y verificá el token.'))
    pasos.append(_paso('Firma del webhook (client_secret)', secret,
                       'client_secret configurado (webhook fail-closed).' if secret
                       else 'Sin client_secret: el webhook no valida firma (modo beta).',
                       '' if secret else 'Cargá el client_secret de la app TikTok para validar la firma.'))

    ok = tiene_token and bool(id_val) and not err
    resumen = ('Credenciales OK (API en beta, sin prueba en vivo)' if ok
               else 'Faltan datos o hay un error registrado — revisá los pasos.')
    return {'ok': ok, 'resumen': resumen, 'pasos': pasos}


def diagnosticar_conexion(sesion):
    """Punto de entrada. Devuelve pasos con causa+solución según el proveedor."""
    prov = getattr(sesion, 'proveedor', '')
    try:
        if prov == 'instagram':
            return _diag_meta(sesion, 'instagram')
        if prov == 'messenger':
            return _diag_meta(sesion, 'messenger')
        if prov == 'tiktok':
            return _diag_tiktok(sesion)
    except Exception as e:
        logger.exception('Diagnóstico de conexión falló para sesión %s', getattr(sesion, 'id', None))
        return {'ok': False, 'resumen': 'No se pudo completar el diagnóstico.',
                'pasos': [_paso('Diagnóstico', False, str(e),
                                'Reintentá; si persiste, revisá los logs del servidor.')]}
    return {'ok': False, 'resumen': 'Canal no soportado',
            'pasos': [_paso('Canal', False, f'Proveedor «{prov}» no soportado por el diagnóstico.', '')]}
