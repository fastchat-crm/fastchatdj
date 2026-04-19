import uuid
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib import messages
from django.template.loader import get_template
from django.urls import reverse

from core.custom_forms import FormError
from core.funciones import addData, paginador, secure_module, log, redirectAfterPostGet
from crm.models import AgentesIA, PerfilNegocioIA, ReglaFinConversacion, AccionFinConversacion
from .forms import SesionWhatsAppForm, ConfigMetaForm
from .models import SesionWhatsApp, ConfigMeta
from .services import WhatsAppService, get_whatsapp_service


@login_required
@secure_module
def sesionesView(request):
    # WhatsAppService() es Baileys-only: create/reconnect/check/close de sesion
    # solo aplican al transporte Node. Las acciones que SI funcionan para ambos
    # proveedores (ej. probar_envio_mensaje) usan get_whatsapp_service(filtro).
    whatsapp_service = WhatsAppService()
    data = {
        'titulo': 'Sesiones WhatsApp',
        'descripcion': 'Control de números de teléfono para sesiones de WhatsApp',
        'ruta': request.path
    }
    addData(request, data)
    model = SesionWhatsApp
    perfil, creado = PerfilNegocioIA.objects.get_or_create(usuario=request.user)
    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                if action == 'add':
                    last_session_id = request.POST.get('last_session_id') or 0
                    last_session = SesionWhatsApp.objects.filter(id=last_session_id).first()

                    session = last_session or SesionWhatsApp.objects.create(
                        estado='pendiente', usuario=request.user, session_id=str(uuid.uuid4()), qr_code='',
                        whatsapp_id=''
                    )

                    session.qr_code = ''

                    log(f"Inicio de sesión WhatsApp pendiente (ID: {session.id})", request, "add", obj=session.id)
                    res_json = {'error': False, 'qr': session.qr_code, 'session_id': session.id}
                    return JsonResponse(res_json, safe=False)
                elif action == 'create_session':
                    import logging as _lg
                    _logger = _lg.getLogger(__name__)
                    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
                    session_id = request.POST['session_id']
                    session = SesionWhatsApp.objects.get(id=session_id)
                    # Si la sesión venía rota, rotar el sessionId (UUID) para que Node arranque
                    # con auth state limpio. La PK Django (id) NO cambia → FK intactas.
                    rotar = (request.POST.get('reset') == '1') or session.estado in ('desconectado', 'error')
                    _logger.warning("CREATE_SESSION id=%s sessionId=%s estado=%s rotar=%s",
                                    session.id, session.session_id, session.estado, rotar)
                    if rotar:
                        old_uuid = session.session_id
                        # best-effort: cleanup del viejo en Node (no bloqueante si falla)
                        try:
                            close_res = whatsapp_service.close_session(old_uuid)
                            _logger.warning("CREATE_SESSION close_session(%s) result=%s", old_uuid, close_res)
                        except Exception as _ex:
                            _logger.warning("CREATE_SESSION close_session(%s) excepcion=%s", old_uuid, _ex)
                        new_uuid = str(uuid.uuid4())
                        session.session_id = new_uuid
                        session.qr_code = ''
                        session.whatsapp_id = ''
                        session.estado = 'pendiente'
                        session.error_mensaje = None
                        session.save(update_fields=['session_id', 'qr_code', 'whatsapp_id', 'estado', 'error_mensaje'])
                        _logger.warning("CREATE_SESSION rotado %s → %s (Django id=%s)", old_uuid, new_uuid, session.id)
                    result = whatsapp_service.create_session(session, webhook_url)
                    _logger.warning("CREATE_SESSION create_session result=%s", result)
                    if not result.get('success'):
                        error_detalle = result.get('error') or 'No se pudo crear la sesión en el servicio Node.js'
                        session.estado = 'error'
                        session.error_mensaje = error_detalle[:500]
                        session.save(update_fields=['estado', 'error_mensaje'])
                        log(f"Fallo create_session ID={session.id}: {error_detalle}", request, "create_session", obj=session.id)
                        return JsonResponse({'error': True, 'message': error_detalle, 'session_id': session.id}, safe=False)
                    session.qr_code = result.get('qr_code') or ''
                    session.save(update_fields=['qr_code'])
                    log(f"Crear sesión WhatsApp pendiente (ID: {session.id})", request, "create_session", obj=session.id)
                    res_json = {'error': False, 'qr': session.qr_code, 'session_id': session.id}
                    return JsonResponse(res_json, safe=False)
                elif action == 'probar_envio_mensaje':
                    from django.utils import timezone as _tz
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    # Validacion de estado por proveedor
                    if filtro.es_baileys:
                        if filtro.estado != 'conectado':
                            return JsonResponse({'error': True, 'message': 'La sesión no está conectada.'})
                    elif filtro.es_meta:
                        config = getattr(filtro, 'config_meta', None)
                        if not config or not config.access_token or not config.phone_number_id:
                            return JsonResponse({'error': True, 'message': 'La sesión Meta no tiene credenciales completas (access_token / phone_number_id).'})
                    numero_destino = (request.POST.get('numero_destino') or '').strip()
                    if not numero_destino:
                        numero_destino = filtro.numero
                    if not numero_destino:
                        return JsonResponse({'error': True, 'message': 'No se proporcionó un número de destino y la sesión no tiene número.'})
                    texto = (request.POST.get('texto') or '').strip() or (
                        f"🔧 Mensaje de prueba desde FastChat\n"
                        f"Sesión: {filtro.numero or filtro.session_id}\n"
                        f"Fecha: {_tz.now().strftime('%d/%m/%Y %H:%M:%S')}"
                    )
                    service = get_whatsapp_service(filtro)
                    # Baileys quiere formato '<num>@s.whatsapp.net'; Meta lo normaliza solo
                    destino_fmt = (
                        service.format_phone_number(numero_destino)
                        if filtro.es_baileys else numero_destino
                    )
                    resultado = service.send_text_message(
                        filtro.session_id, destino_fmt, texto, simularEscritura=True,
                    )
                    if resultado.get('success'):
                        log(f"Prueba de envío enviada desde sesión {filtro.id} a {destino_fmt}", request, "change", obj=filtro.id)
                        return JsonResponse({
                            'error': False,
                            'message': 'Mensaje de prueba enviado correctamente.',
                            'message_id': resultado.get('message_id'),
                            'destino': destino_fmt,
                            'texto': texto,
                        })
                    return JsonResponse({
                        'error': True,
                        'message': resultado.get('error') or 'No se pudo enviar el mensaje de prueba.',
                        'destino': destino_fmt,
                    })
                elif action == 'verificar_conexion':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    if not filtro.es_baileys:
                        return JsonResponse({'error': True, 'message': 'Verificar conexión solo aplica para sesiones Baileys. Para Meta usa "Verificar conexión con Meta" en el formulario.'})
                    if not filtro.session_id:
                        return JsonResponse({'error': True, 'message': 'La sesión no tiene session_id asignado.'})
                    result = whatsapp_service.check_session_status(filtro.session_id)
                    if not result.get('success'):
                        if result.get('not_found') and filtro.estado == 'conectado':
                            filtro.estado = 'desconectado'
                            filtro.error_mensaje = 'Sesión no existe en el servidor de WhatsApp'
                            filtro.save()
                            log(f"Verificación: sesión {filtro.id} no existe en Node — marcada como desconectada", request, "change", obj=filtro.id)
                        return JsonResponse({
                            'error': True,
                            'connected': False,
                            'message': result.get('error') or 'No se pudo verificar la sesión',
                        })
                    connected = result.get('connected')
                    estado_previo = filtro.estado
                    if connected and filtro.estado != 'conectado':
                        filtro.estado = 'conectado'
                        filtro.error_mensaje = None
                        filtro.save()
                        log(f"Verificación: sesión {filtro.id} está realmente conectada — estado actualizado", request, "change", obj=filtro.id)
                    elif not connected and filtro.estado == 'conectado':
                        filtro.estado = 'desconectado'
                        filtro.error_mensaje = 'Conexión con WhatsApp perdida (detectado por verificación manual)'
                        filtro.save()
                        log(f"Verificación: sesión {filtro.id} reportaba conectada pero el socket está caído — marcada como desconectada", request, "change", obj=filtro.id)
                    return JsonResponse({
                        'error': False,
                        'connected': connected,
                        'is_active': result.get('is_active'),
                        'estado': filtro.estado,
                        'estado_previo': estado_previo,
                        'last_activity': result.get('last_activity'),
                        'message': (
                            'Conexión activa con WhatsApp.' if connected
                            else 'La sesión no tiene conexión real con WhatsApp.'
                        ),
                    })
                elif action == 'reconectar':
                    import logging as _lg
                    _logger = _lg.getLogger(__name__)
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    if not filtro.es_baileys:
                        return JsonResponse({'error': True, 'message': 'Reconectar solo aplica para sesiones Baileys.'})
                    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
                    _logger.warning("RECONECTAR id=%s sessionId=%s estado=%s", filtro.id, filtro.session_id, filtro.estado)
                    # Rotar UUID: cleanup del viejo + nuevo sessionId. Django id no cambia, FK intactas.
                    old_uuid = filtro.session_id
                    try:
                        close_res = whatsapp_service.close_session(old_uuid)
                        _logger.warning("RECONECTAR close_session(%s) result=%s", old_uuid, close_res)
                    except Exception as _ex:
                        _logger.warning("RECONECTAR close_session(%s) excepcion=%s", old_uuid, _ex)
                    new_uuid = str(uuid.uuid4())
                    filtro.session_id = new_uuid
                    filtro.qr_code = ''
                    filtro.whatsapp_id = ''
                    filtro.estado = 'pendiente'
                    filtro.error_mensaje = None
                    filtro.desconectado_manualmente = False
                    filtro.save(update_fields=['session_id', 'qr_code', 'whatsapp_id', 'estado', 'error_mensaje', 'desconectado_manualmente'])
                    _logger.warning("RECONECTAR rotado %s → %s (Django id=%s)", old_uuid, new_uuid, filtro.id)
                    result = whatsapp_service.create_session(filtro, webhook_url)
                    _logger.warning("RECONECTAR create_session result=%s", result)
                    if result.get('success'):
                        filtro.estado = 'pendiente'
                        filtro.error_mensaje = None
                        filtro.desconectado_manualmente = False
                        if result.get('qr_code'):
                            filtro.qr_code = result['qr_code']
                        filtro.save(update_fields=['estado', 'error_mensaje', 'desconectado_manualmente', 'qr_code'])
                        log(f"Sesión {filtro.id} reconectada manualmente", request, "change", obj=filtro.id)
                        return JsonResponse({'error': False, 'qr': filtro.qr_code or '', 'message': 'Reconexión iniciada. Escanea el QR si es necesario.'})
                    else:
                        return JsonResponse({'error': True, 'message': result.get('error') or 'No se pudo reconectar'})
                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    if not filtro.es_baileys:
                        return JsonResponse({'error': True, 'message': 'Desconectar solo aplica para sesiones Baileys. Las sesiones Meta se gestionan desde el panel de Meta.'})
                    result = whatsapp_service.close_session(filtro.session_id)
                    if 'success' in result:
                        if not result['success']:
                            raise NameError(result['error'])
                    filtro.estado = 'desconectado'
                    filtro.error_mensaje = None
                    filtro.desconectado_manualmente = True  # el cron no intentará reconectar
                    filtro.save()
                    log(f"Sesión de WhatsApp {filtro.numero} desconectada", request, "del", obj=filtro.id)
                    messages.success(request, "Sesión desconectada correctamente.")
                    return JsonResponse({"error": False})
                elif action == 'change':
                    instance = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    form = SesionWhatsAppForm(request.POST, request.FILES, instance=instance)

                    if not form.is_valid():
                        raise FormError(form)

                    obj = form.save()

                    res_json.append({'error': False, 'to': redirectAfterPostGet(request)})
                    return JsonResponse(res_json, safe=False)
                elif action == 'change_modal':
                    instance = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    form = SesionWhatsAppForm(request.POST, request.FILES, instance=instance)

                    if not form.is_valid():
                        raise FormError(form)

                    obj = form.save()
                    res_json.append({'error': False, 'reload': True})
                    return JsonResponse(res_json, safe=False)

                # ── Regla de Fin de Conversación ─────────────────────────────
                elif action == 'regla_fin_cargar_plantilla':
                    # Carga la plantilla del agente asociado a la sesión
                    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    agente = session.agente_ia
                    if not agente:
                        return JsonResponse({'error': True, 'message': 'Esta sesión no tiene un agente asignado.'})
                    plantilla = getattr(agente, 'regla_fin', None)
                    if not plantilla:
                        return JsonResponse({'error': True, 'message': 'El agente no tiene una plantilla de cierre configurada.'})
                    regla, _ = ReglaFinConversacion.objects.get_or_create(sesion=session)
                    regla.activo = plantilla.activo
                    regla.usar_senal_llm = plantilla.usar_senal_llm
                    regla.frases_cierre = plantilla.frases_cierre
                    regla.save()
                    # Copiar acciones
                    regla.acciones.all().delete()
                    for accion in plantilla.acciones.filter(status=True):
                        AccionFinConversacion.objects.create(
                            regla=regla, tipo=accion.tipo,
                            destino=accion.destino,
                            plantilla_mensaje=accion.plantilla_mensaje,
                        )
                    return JsonResponse({'error': False, 'message': 'Plantilla cargada correctamente.'})

                elif action == 'regla_fin_guardar':
                    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    regla, _ = ReglaFinConversacion.objects.get_or_create(sesion=session)
                    regla.activo = request.POST.get('activo') == 'true'
                    regla.usar_senal_llm = request.POST.get('usar_senal_llm') == 'true'
                    regla.frases_cierre = request.POST.get('frases_cierre', '').strip() or None
                    regla.save()
                    return JsonResponse({'error': False})

                elif action == 'regla_fin_accion_add':
                    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    regla, _ = ReglaFinConversacion.objects.get_or_create(sesion=session)
                    tipo = request.POST.get('tipo', 'ninguna')
                    destino = request.POST.get('destino', '').strip() or None
                    plantilla_mensaje = request.POST.get('plantilla_mensaje', '').strip() or None
                    accion = AccionFinConversacion.objects.create(
                        regla=regla, tipo=tipo,
                        destino=destino, plantilla_mensaje=plantilla_mensaje,
                    )
                    return JsonResponse({
                        'error': False,
                        'accion': {
                            'id': accion.id,
                            'tipo': accion.get_tipo_display(),
                            'destino': accion.destino or '',
                        }
                    })

                elif action == 'regla_fin_accion_delete':
                    accion = AccionFinConversacion.objects.get(id=request.POST['accion_id'])
                    accion.delete()
                    return JsonResponse({'error': False})

                # ── Configuracion Meta Cloud API ───────────────────────────
                elif action == 'guardar_config_meta':
                    import secrets
                    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    config, _ = ConfigMeta.objects.get_or_create(
                        sesion=session,
                        defaults={
                            'waba_id': '',
                            'phone_number_id': '',
                            'access_token': '',
                            'webhook_verify_token': secrets.token_urlsafe(32),
                        },
                    )
                    # Validacion manual de los campos obligatorios (el form los
                    # tiene required=False para no bloquear el submit principal
                    # cuando la sesion esta en modo Baileys).
                    obligatorios = {
                        'waba_id':         'WABA ID',
                        'phone_number_id': 'Phone Number ID',
                        'access_token':    'Access Token',
                    }
                    faltantes = [
                        label for campo, label in obligatorios.items()
                        if not (request.POST.get(campo) or '').strip()
                    ]
                    if faltantes:
                        return JsonResponse({
                            'error': True,
                            'message': 'Completa los campos obligatorios: ' + ', '.join(faltantes) + '.',
                        })
                    form = ConfigMetaForm(request.POST, instance=config)
                    if not form.is_valid():
                        raise FormError(form)
                    obj = form.save()

                    # Garantizar que la sesion quede marcada como proveedor=meta
                    if session.proveedor != 'meta':
                        session.proveedor = 'meta'
                        session.save(update_fields=['proveedor'])

                    # URL de webhook para que el cliente la copie a Meta
                    webhook_url = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
                    log(f"Config Meta guardada para sesion {session.id}", request, "change", obj=session.id)
                    return JsonResponse({
                        'error': False,
                        'message': 'Configuracion Meta guardada correctamente.',
                        'webhook_url': webhook_url,
                        'verify_token': obj.webhook_verify_token,
                    })

                elif action == 'regenerar_verify_token':
                    import secrets
                    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    config = getattr(session, 'config_meta', None)
                    if not config:
                        return JsonResponse({'error': True, 'message': 'La sesion no tiene configuracion Meta todavia.'})
                    config.webhook_verify_token = secrets.token_urlsafe(32)
                    config.webhook_verificado_en = None
                    config.save(update_fields=['webhook_verify_token', 'webhook_verificado_en'])
                    log(f"Verify token regenerado para sesion {session.id}", request, "change", obj=session.id)
                    return JsonResponse({
                        'error': False,
                        'verify_token': config.webhook_verify_token,
                        'message': 'Nuevo verify token generado. Actualizalo en Meta Developer Portal.',
                    })

                elif action == 'verificar_meta_conexion':
                    # Intenta hacer una consulta liviana a Graph API con el token almacenado
                    import requests
                    session = SesionWhatsApp.objects.get(id=request.POST['pk'])
                    config = getattr(session, 'config_meta', None)
                    if not config:
                        return JsonResponse({'error': True, 'message': 'Sesion sin ConfigMeta.'})
                    if not config.access_token or not config.phone_number_id:
                        return JsonResponse({'error': True, 'message': 'Faltan credenciales Meta (token o phone_number_id).'})
                    try:
                        from .services_meta import GRAPH_API_BASE
                        r = requests.get(
                            f'{GRAPH_API_BASE}/{config.phone_number_id}',
                            headers={'Authorization': f'Bearer {config.access_token}'},
                            params={'fields': 'display_phone_number,verified_name,quality_rating,messaging_limit_tier'},
                            timeout=10,
                        )
                    except Exception as e:
                        return JsonResponse({'error': True, 'message': f'Error de conexion: {str(e)}'})
                    if r.status_code != 200:
                        return JsonResponse({
                            'error': True,
                            'message': f'Meta respondio {r.status_code}: {r.text[:400]}',
                        })
                    data = r.json()
                    # Persistir info descubierta
                    from django.utils import timezone as _tz
                    config.display_phone_number = data.get('display_phone_number') or config.display_phone_number
                    config.quality_rating = (data.get('quality_rating') or 'UNKNOWN').upper()
                    if data.get('messaging_limit_tier'):
                        config.messaging_limit_tier = data.get('messaging_limit_tier')
                    config.ultima_sincronizacion = _tz.now()
                    config.save(update_fields=[
                        'display_phone_number', 'quality_rating',
                        'messaging_limit_tier', 'ultima_sincronizacion',
                    ])
                    # Replicar numero en la sesion si no esta seteado
                    if not session.numero and config.display_phone_number:
                        session.numero = ''.join(c for c in config.display_phone_number if c.isdigit())
                        session.estado = 'conectado'
                        session.save(update_fields=['numero', 'estado'])
                    return JsonResponse({
                        'error': False,
                        'message': 'Conexion con Meta verificada correctamente.',
                        'display_phone_number': config.display_phone_number,
                        'quality_rating': config.get_quality_rating_display(),
                        'messaging_limit_tier': config.get_messaging_limit_tier_display() if config.messaging_limit_tier else None,
                        'verified_name': data.get('verified_name'),
                    })

                elif action == 'add_meta':
                    form = SesionWhatsAppForm(request.POST, request.FILES)
                    if not form.is_valid():
                        raise FormError(form)
                    obj = form.save(commit=False)
                    obj.usuario = request.user
                    obj.session_id = str(uuid.uuid4())
                    obj.proveedor = 'meta'
                    obj.estado = 'pendiente'
                    obj.save()
                    form.save_m2m()
                    log(f"Sesion Meta creada: {obj.nombre or obj.id}", request, "add", obj=obj.id)
                    res_json.append({'error': False, 'reload': True})
                    return JsonResponse(res_json, safe=False)

                elif action == 'delete_force':
                    session_id = request.POST.get('id')
                    session = SesionWhatsApp.objects.filter(id=session_id).first()
                    if not session:
                        return JsonResponse({'error': True, 'message': 'Sesión no encontrada.'})
                    # Permitir eliminar si: esta pendiente, o es vacia (sin numero + >10 min)
                    if session.estado == 'pendiente':
                        session.delete()
                        log(f"Sesión pendiente eliminada (ID: {session_id})", request, "delete_force", obj=session_id)
                        return JsonResponse({'error': False, 'message': 'Sesión eliminada.'})
                    from django.utils import timezone
                    tiempo_sin_numero = timezone.now() - session.fecha_registro
                    if not session.numero and tiempo_sin_numero.total_seconds() > 600:
                        session.delete()
                        log(f"Sesión vacía eliminada por inactividad (ID: {session_id})", request, "delete_force", obj=session_id)
                        return JsonResponse({'error': False, 'message': 'Sesión eliminada.'})
                    return JsonResponse({'error': True, 'message': 'Solo se pueden eliminar sesiones en estado pendiente o vacías sin número.'})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            res_json.append({'error': True, 'message': f"Error, intente nuevamente. {str(ex)}"})
            return JsonResponse(res_json, safe=False)
    # ====================== LISTADO SESIONES =========================
    data['action'] = action = request.GET.get('action')
    if action == 'change':
        data['instance'] = instance = SesionWhatsApp.objects.get(id=request.GET['pk'])
        data['form'] = form = SesionWhatsAppForm(instance=instance)
        form.fields['agente_ia'].queryset = AgentesIA.objects.filter(perfil=perfil, status=True)
        data['regla_fin'] = getattr(instance, 'regla_fin', None)
        data['acciones_fin'] = data['regla_fin'].acciones.filter(status=True) if data['regla_fin'] else []
        data['tiene_plantilla_agente'] = bool(instance.agente_ia and getattr(instance.agente_ia, 'regla_fin', None))
        data['config_meta'] = config_meta = getattr(instance, 'config_meta', None)
        data['config_meta_form'] = ConfigMetaForm(instance=config_meta) if config_meta else ConfigMetaForm()
        data['meta_webhook_url'] = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
        return render(request, 'whatsapp/sesiones/form.html', data)
    if action == 'change_modal':
        try:
            pk = request.GET.get('pk', '')
            if pk == 'new_meta':
                data['instance'] = None
                data['action'] = 'add_meta'
                data['form'] = form = SesionWhatsAppForm(initial={'proveedor': 'meta'})
            else:
                data['instance'] = instance = SesionWhatsApp.objects.get(id=pk)
                data['form'] = form = SesionWhatsAppForm(instance=instance)
            form.fields['agente_ia'].queryset = AgentesIA.objects.filter(perfil=perfil, status=True)
            instance = data.get('instance')
            data['regla_fin'] = getattr(instance, 'regla_fin', None) if instance else None
            data['acciones_fin'] = data['regla_fin'].acciones.filter(status=True) if data['regla_fin'] else []
            data['tiene_plantilla_agente'] = bool(instance and instance.agente_ia and getattr(instance.agente_ia, 'regla_fin', None))
            data['config_meta'] = config_meta = getattr(instance, 'config_meta', None) if instance else None
            data['config_meta_form'] = ConfigMetaForm(instance=config_meta) if config_meta else ConfigMetaForm()
            data['meta_webhook_url'] = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
            template = get_template("whatsapp/sesiones/form_modal.html")
            return JsonResponse({"result": True, 'data': template.render(data)})
        except Exception as ex:
            return JsonResponse({"result": False, 'message': str(ex)})
    if action == 'historial_de_sesiones':
        data['instance'] = instance = SesionWhatsApp.objects.get(id=request.GET['pk'])
        data['listado'] = instance.get_log_entries().filter(change_message__istartswith='HS: ')
        return render(request, 'whatsapp/sesiones/historial_de_sesiones.html', data)
    criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True, usuario_id=request.user.id), ''
    estado = request.GET.get('estado', '')
    if criterio:
        filtros = filtros & (Q(numero__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio
    if estado:
        filtros &= Q(estado=estado)
        data["estado"] = estado
        url_vars += '&estado=' + estado

    listado = model.objects.filter(filtros)
    data["list_count"] = listado.count()
    data["url_vars"] = url_vars

    base_qs = model.objects.filter(status=True, usuario_id=request.user.id)
    stats_raw = {row['estado']: row['total'] for row in base_qs.values('estado').annotate(total=Count('id'))}
    data['stats'] = {
        'total': sum(stats_raw.values()),
        'conectado': stats_raw.get('conectado', 0),
        'pendiente': stats_raw.get('pendiente', 0),
        'desconectado': stats_raw.get('desconectado', 0),
        'error': stats_raw.get('error', 0),
    }

    paginador(request, listado.order_by('numero'), 12, data, url_vars)
    return render(request, 'whatsapp/sesiones/listado.html', data)