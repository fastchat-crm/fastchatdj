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
from .forms import SesionWhatsAppForm
from .models import SesionWhatsApp
from .services import WhatsAppService


@login_required
@secure_module
def sesionesView(request):
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
                    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
                    session_id = request.POST['session_id']
                    session = SesionWhatsApp.objects.get(id=session_id)
                    result = whatsapp_service.create_session(session, webhook_url)
                    session.qr_code = result.get('qr_code')
                    session.save()
                    log(f"Crear sesión WhatsApp pendiente (ID: {session.id})", request, "create_session", obj=session.id)
                    res_json = {'error': False, 'qr': session.qr_code, 'session_id': session.id}
                    return JsonResponse(res_json, safe=False)
                elif action == 'probar_envio_mensaje':
                    from django.utils import timezone as _tz
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    if filtro.estado != 'conectado':
                        return JsonResponse({'error': True, 'message': 'La sesión no está conectada.'})
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
                    destino_fmt = whatsapp_service.format_phone_number(numero_destino)
                    resultado = whatsapp_service.send_text_message(
                        filtro.session_id, destino_fmt, texto,
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
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    webhook_url = request.build_absolute_uri(reverse('whatsapp_webhook_handler'))
                    result = whatsapp_service.create_session(filtro, webhook_url)
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

                elif action == 'delete_force':
                    session_id = request.POST.get('id')
                    session = SesionWhatsApp.objects.filter(id=session_id).first()
                    if session:
                        from django.utils import timezone
                        tiempo_sin_numero = timezone.now() - session.fecha_registro
                        if tiempo_sin_numero.total_seconds() > 600:  # 10 minutos
                            session.delete()
                            log(f"Sesión eliminada forzadamente por inactividad sin número (ID: {session_id})", request,
                                "delete_force", obj=session_id)
                            return JsonResponse({'error': False, 'message': 'Sesión eliminada forzadamente.'})
                        else:
                            return JsonResponse(
                                {'error': True, 'message': 'La sesión no supera los 10 minutos sin número.'})
                    else:
                        return JsonResponse({'error': True, 'message': 'Sesión no encontrada o ya tiene número.'})
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
        return render(request, 'whatsapp/sesiones/form.html', data)
    if action == 'change_modal':
        try:
            data['instance'] = instance = SesionWhatsApp.objects.get(id=request.GET['pk'])
            data['form'] = form = SesionWhatsAppForm(instance=instance)
            form.fields['agente_ia'].queryset = AgentesIA.objects.filter(perfil=perfil, status=True)
            data['regla_fin'] = getattr(instance, 'regla_fin', None)
            data['acciones_fin'] = data['regla_fin'].acciones.filter(status=True) if data['regla_fin'] else []
            data['tiene_plantilla_agente'] = bool(instance.agente_ia and getattr(instance.agente_ia, 'regla_fin', None))
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