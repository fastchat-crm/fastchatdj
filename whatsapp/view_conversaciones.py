from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.db.models import Q, Sum
from django.contrib import messages
from django.template.loader import render_to_string, get_template
from django.utils import timezone
from django.http import JsonResponse

from autenticacion.models import Usuario
from core.funciones import addData, paginador, secure_module, log, leer_sesion_id, encrypt_sesion_id, decrypt_sesion_id
from seguridad.templatetags.templatefunctions import encrypt
from .forms import CambiarClasificacionForm, CambiarNombreContactoForm, AsignarAgenteForm
from .funcionesWhatsappConversacion import (
    cambiar_clasificacion_get,
    cambiar_clasificacion_post,
    cambiar_nombre_contacto_get,
    cambiar_nombre_contacto_post,
    historial_cliente_list,
    historial_cliente_mensajes,
    _bloqueo_reactivar,
    _control_respuestas,
    _estadisticas_conversacion,
    _tokens_conversacion,
    HORAS_VENTANA_REACTIVAR,
)
from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp, SENTIMIENTO_CHOICES
from .services import WhatsAppService, get_whatsapp_service
from .permisos_sesion import (
    sesiones_visibles,
    sesiones_vista_completa,
    rol_en_sesion,
    filtro_conversaciones_por_rol,
    puede_ver_conversacion,
    es_vista_completa,
)


@login_required
@secure_module
def conversacionesView(request):
    data = {
        'titulo': 'Conversaciones WhatsApp',
        'modulo': 'Conversaciones WhatsApp',
        'ruta': request.path
    }
    addData(request, data)

    # Todas las sesiones visibles para el usuario (dueño, participante o superuser).
    sesiones = sesiones_visibles(request.user).order_by('-ultima_conexion')
    data['sesiones'] = sesiones

    # Sesión seleccionada (por defecto la primera)
    sesion_id = leer_sesion_id(request)
    contactoId = request.session.pop('contactoId', None)
    conversacion_selected = None
    if contactoId:
        try:
            conversacion_selected = ConversacionWhatsApp.objects.get(pk=int(encrypt(contactoId)))
            sesion_id = conversacion_selected.sesion.id
        except Exception as ex:
            raise NameError(f'No se encontró la conversación: {ex}')

    # Soporte deep-link `?conv=<token>` (usado por el correo del asesor de
    # cotización). Si la conversación está finalizada → redirigir a la página
    # de finalizadas con el mismo token. Si está activa → la marcamos para
    # auto-abrir vía JS y forzamos la sesión correcta en el combo.
    conv_token = (request.GET.get('conv') or '').strip()
    auto_open_conv_id = None
    if conv_token:
        conv_id_pedido = decrypt_sesion_id(conv_token, default=None)
        if conv_id_pedido:
            conv_obj = ConversacionWhatsApp.objects.filter(pk=conv_id_pedido).select_related(
                'contacto', 'contacto__sesion'
            ).first()
            if conv_obj:
                if conv_obj.conversacion_finalizada:
                    return redirect(f'/whatsapp/conversaciones-finalizadas/?conv={conv_token}')
                auto_open_conv_id = conv_obj.id
                if conv_obj.contacto and conv_obj.contacto.sesion:
                    sesion_id = conv_obj.contacto.sesion.id
    if sesion_id:
        sesion_seleccionada = sesiones.filter(id=sesion_id).first()
        if not sesion_seleccionada and sesiones.exists():
            sesion_seleccionada = sesiones.first()
    elif sesiones.exists():
        sesion_seleccionada = sesiones.first()
    else:
        sesion_seleccionada = None

    data['sesion_seleccionada'] = sesion_seleccionada
    data['auto_open_conv_id'] = auto_open_conv_id
    rol_sesion = rol_en_sesion(request.user, sesion_seleccionada)
    data['rol_sesion'] = rol_sesion
    data['es_vista_completa'] = es_vista_completa(request.user, sesion_seleccionada)

    # ====================== VER MENSAJES =========================
    if request.method == 'GET' and 'action' in request.GET:
        data['action'] = action = request.GET['action']
        if action == 'ver_mensajes':
            pk = int(request.GET['pk'])
            conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
            if not puede_ver_conversacion(request.user, conversacion):
                return JsonResponse({'error': True, 'message': 'Not authorized.'})
            mensajes = MensajeWhatsApp.objects.filter(conversacion=conversacion).order_by('fecha')
            data['conversacion'] = conversacion
            data['mensajes'] = mensajes
            # Atribución: si la conv tiene referral (Click-to-WhatsApp ad),
            # mandamos un payload compacto al frontend para mostrar un badge
            # en el chat header. El operador ve de qué anuncio vino el lead.
            referral_data = None
            if conversacion.referral_payload_json or conversacion.ad_id or conversacion.campaign_id:
                referral_data = {
                    'headline': conversacion.referral_headline or '',
                    'body':     (conversacion.referral_body or '')[:300],
                    'source_url': conversacion.referral_source_url or '',
                    'source_type': conversacion.referral_source_type or '',
                    'media_type': conversacion.referral_medium or '',
                    'ad_id':       conversacion.ad_id or '',
                    'adset_id':    conversacion.adset_id or '',
                    'campaign_id': conversacion.campaign_id or '',
                    'ctwa_clid':   conversacion.ctwa_clid or '',
                }
            return JsonResponse({
                'html': render_to_string('whatsapp/conversaciones/mensajes_partial.html', data, request=request),
                'conversacion_id': conversacion.id,
                'contacto_nombre': conversacion.contacto_nombre or '',
                'contacto_numero': conversacion.contacto_numero,
                # get_foto_gris() devuelve: la foto real si existe; si no,
                # el PNG con la inicial del nombre; si no hay nombre, el
                # default. Así nunca usamos el avatar genérico cuando hay
                # información mínima del contacto.
                'contacto_foto': conversacion.contacto.get_foto_gris(),
                'hashed_id': conversacion.hashed_id or '',
                'estado_active': conversacion.estado_conversacion == 0,
                'ai_activo': conversacion.ai_activo,
                'asignado_a': conversacion.asignado_a.get_full_name() if conversacion.asignado_a else '',
                'asignado_foto': conversacion.asignado_a.get_foto_gris() if conversacion.asignado_a else '',
                'nota_interna': conversacion.nota_interna or '',
                'fecha_asignacion': conversacion.fecha_asignacion.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_asignacion else '',
                'fecha_inicio': conversacion.fecha_registro.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_registro else '',
                'bloquear_cierre': conversacion.bloquear_cierre,
                'es_meta': bool(getattr(conversacion.sesion, 'es_meta', False)),
                'vence_meta': conversacion.vence_meta_en.isoformat() if conversacion.vence_meta_en else None,
                'meta_bloqueada': conversacion.vence_meta_expirada,
                'es_tradicional': (conversacion.sesion.modo_bot or '') == 'tradicional',
                'referral': referral_data,
                'clasificacion_id': conversacion.clasificacion,
                'clasificacion_label': conversacion.get_clasificacion_display(),
                'clasificacion_color': conversacion.get_estado_color_clasificacion(),
                **_estadisticas_conversacion(conversacion),
            })
        elif action == 'ver_estadisticas':
            try:
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['pk']))
                return JsonResponse({'error': False, **_estadisticas_conversacion(conversacion)})
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'cambiar-clasificacion':
            return cambiar_clasificacion_get(request)
        elif action == 'cambiar-nombre-contacto':
            return cambiar_nombre_contacto_get(request)
        elif action == 'asignar-conversacion':
            try:
                filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
                form = AsignarAgenteForm(instance=filtro)
                data.update({'form': form, 'filtro': filtro})
                template = get_template("whatsapp/conversaciones/form.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})
        elif action == 'historial_cliente':
            try:
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['pk']))
                return historial_cliente_list(request, conv)
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'historial_mensajes':
            try:
                conv = get_object_or_404(ConversacionWhatsApp, pk=int(request.GET['pk']))
                return historial_cliente_mensajes(request, conv)
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})
        elif action == 'listar_plantillas_meta':
            # Devuelve plantillas APPROVED de la sesion Meta de la conversacion.
            # Se usa para poblar el panel en el composer cuando sesion.es_meta.
            try:
                pk = int(request.GET['pk'])
                conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                sesion = conversacion.sesion
                if not getattr(sesion, 'es_meta', False):
                    return JsonResponse({'error': False, 'plantillas': [], 'motivo': 'sesion_no_meta'})
                config = getattr(sesion, 'config_meta', None)
                if not config:
                    return JsonResponse({'error': False, 'plantillas': [], 'motivo': 'sin_config_meta'})
                plantillas = (
                    config.plantillas.filter(status=True, estado_meta='APPROVED')
                    .order_by('nombre', 'idioma')
                )
                def _preview(body, max_chars=140):
                    body = (body or '').strip()
                    return (body[:max_chars] + '…') if len(body) > max_chars else body
                data_plantillas = [{
                    'id':        p.id,
                    'nombre':    p.nombre,
                    'idioma':    p.idioma,
                    'categoria': p.categoria,
                    'cuerpo':    p.cuerpo or '',
                    'preview':   _preview(p.cuerpo),
                    'footer':    p.footer or '',
                    'header_tipo':     p.header_tipo,
                    'header_contenido': p.header_contenido or '',
                    'variables': p.variables_json or [],
                    'botones':   p.botones_json or [],
                    'veces_enviada': p.veces_enviada,
                } for p in plantillas]
                return JsonResponse({'error': False, 'plantillas': data_plantillas})
            except Exception as ex:
                return JsonResponse({'error': True, 'message': str(ex)})

    # ====================== ENVIAR MENSAJE =========================
    if request.method == 'POST':
        try:
            with transaction.atomic():
                action = request.POST['action']
                res_json= []
                if action == 'send':
                    pk = int(request.POST['pk'])
                    texto = request.POST.get('mensaje')
                    archivo = request.FILES.get('archivo')  # Obtener archivo si existe
                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                    if not puede_ver_conversacion(request.user, conversacion):
                        return JsonResponse({'error': True, 'message': 'Not authorized.'})

                    from .funcionesWhatsappConversacion import _bloqueo_ventana_meta
                    meta_bloqueada, _vence_meta = _bloqueo_ventana_meta(conversacion)
                    if meta_bloqueada:
                        return JsonResponse({
                            'error': True,
                            'requiere_plantilla': True,
                            'message': 'La ventana de 24 horas de Meta venció. Para retomar la conversación debes enviar una plantilla aprobada.',
                        })

                    # Crear instancia del servicio segun proveedor de la sesion
                    service = get_whatsapp_service(conversacion.sesion)

                    # Determinar tipo antes de leer el archivo.
                    # `tipo_mensaje` es el valor interno (ES) que guardamos en BD.
                    # `media_type` es el valor canonico (EN) que ambos servicios aceptan.
                    tipo_mensaje = 'texto'
                    media_type = None
                    if archivo:
                        ct = archivo.content_type or ''
                        if 'image' in ct:
                            tipo_mensaje, media_type = 'imagen', 'image'
                        elif 'audio' in ct:
                            tipo_mensaje, media_type = 'audio', 'audio'
                        elif 'video' in ct:
                            tipo_mensaje, media_type = 'video', 'video'
                        else:
                            tipo_mensaje, media_type = 'documento', 'document'

                    if archivo:
                        file_bytes = archivo.read()
                        response = service.send_media_message(
                            conversacion.sesion.session_id, conversacion.from_number, caption=texto,
                            file_content=file_bytes, filename=archivo.name, media_type=media_type,
                            conversacion_id=conversacion.id,
                        )
                    else:
                        response = service.send_text_message(
                            conversacion.sesion.session_id, conversacion.from_number, texto,
                            conversacion_id=conversacion.id,
                        )

                    if not response.get('success', False):
                        return JsonResponse({
                            'error': True,
                            'message': f"Error al enviar mensaje: {response.get('error', 'Error desconocido')}",
                            'requiere_plantilla': bool(response.get('requiere_plantilla')),
                            'cuenta_degradada': bool(response.get('cuenta_degradada')),
                        })

                    # Guardamos en BD
                    mensaje = MensajeWhatsApp(
                        mensaje_id_externo=response.get('message_id'),
                        conversacion=conversacion,
                        remitente=conversacion.sesion.numero,
                        mensaje=texto,
                        tipo=tipo_mensaje,
                        archivo_url=response.get('media_url'),
                        fecha=timezone.now(),
                        leido=True,
                        fecha_leido=timezone.now(),
                        agente=request.user,
                        ia_generado=False,
                    )
                    # Guardar archivo localmente para tener URL definitiva
                    if archivo:
                        from django.core.files.base import ContentFile
                        mensaje.archivo.save(archivo.name, ContentFile(file_bytes), save=False)
                    mensaje.save()

                    # Registrar primer agente humano en responder
                    if not conversacion.primer_agente:
                        conversacion.primer_agente = request.user
                        conversacion.save(update_fields=['primer_agente'])

                    log(f"Mensaje enviado a {conversacion.contacto_numero}", request, "add", obj=conversacion.id)

                    # Devolver el HTML del mensaje para añadirlo al chat
                    return JsonResponse({
                        'error': False,
                        'mensaje_html': render_to_string('whatsapp/conversaciones/mensaje_enviado_partial.html',
                                                        {'mensaje': mensaje},
                                                        request=request)
                    })
                elif action == 'enviar_plantilla_meta':
                    # Envia una plantilla Meta pre-aprobada. Util cuando la
                    # ventana 24h expiro o para reenganchar conversaciones.
                    import json as _json
                    from .models import PlantillaWhatsApp
                    pk = int(request.POST['pk'])
                    plantilla_id = int(request.POST['plantilla_id'])
                    params_cuerpo = _json.loads(request.POST.get('params_cuerpo_json') or '[]')
                    params_header = _json.loads(request.POST.get('params_header_json') or '[]')

                    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
                    sesion = conversacion.sesion
                    if not getattr(sesion, 'es_meta', False):
                        return JsonResponse({'error': True, 'message': 'La sesion no es Meta — usa el envio normal.'})
                    config = getattr(sesion, 'config_meta', None)
                    if not config:
                        return JsonResponse({'error': True, 'message': 'Configuracion Meta no encontrada.'})
                    plantilla = PlantillaWhatsApp.objects.filter(
                        pk=plantilla_id, config_meta=config, status=True, estado_meta='APPROVED'
                    ).first()
                    if not plantilla:
                        return JsonResponse({'error': True, 'message': 'Plantilla no disponible o no aprobada.'})

                    service = get_whatsapp_service(sesion)
                    response = service.send_template(
                        sesion.session_id, conversacion.from_number,
                        plantilla_nombre=plantilla.nombre,
                        idioma=plantilla.idioma,
                        parametros_cuerpo=params_cuerpo if params_cuerpo else None,
                        parametros_header=params_header if params_header else None,
                        conversacion_id=conversacion.id,
                    )
                    if not response.get('success'):
                        return JsonResponse({
                            'error': True,
                            'message': f"Error al enviar plantilla: {response.get('error', 'Error desconocido')}",
                        })

                    # Renderizar cuerpo con los params sustituidos para el historial local
                    def _render_cuerpo(body, params):
                        if not body:
                            return ''
                        out = body
                        for idx, val in enumerate(params or [], start=1):
                            out = out.replace('{{' + str(idx) + '}}', str(val))
                        return out
                    texto_final = _render_cuerpo(plantilla.cuerpo, params_cuerpo)
                    if plantilla.footer:
                        texto_final = f"{texto_final}\n\n_{plantilla.footer}_"

                    mensaje = MensajeWhatsApp(
                        mensaje_id_externo=response.get('message_id'),
                        conversacion=conversacion,
                        remitente=sesion.numero,
                        mensaje=texto_final,
                        tipo='texto',
                        fecha=timezone.now(),
                        leido=True,
                        fecha_leido=timezone.now(),
                        agente=request.user,
                        ia_generado=False,
                    )
                    mensaje.save()

                    # El contador veces_enviada + ultimo_envio lo actualiza
                    # MetaWhatsAppService.send_template via F('veces_enviada')+1.
                    if not conversacion.primer_agente:
                        conversacion.primer_agente = request.user
                        conversacion.save(update_fields=['primer_agente'])

                    log(f"Plantilla Meta '{plantilla.nombre}' enviada a {conversacion.contacto_numero}",
                        request, "add", obj=conversacion.id)

                    return JsonResponse({
                        'error': False,
                        'mensaje_html': render_to_string(
                            'whatsapp/conversaciones/mensaje_enviado_partial.html',
                            {'mensaje': mensaje}, request=request,
                        ),
                    })
                elif action == 'cambiar-clasificacion':
                    return cambiar_clasificacion_post(request)
                elif action == 'cambiar-nombre-contacto':
                    return cambiar_nombre_contacto_post(request)
                elif action == 'asignar-conversacion':
                    filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
                    # Marcar fecha_asignacion y pausar bot antes de pasar al form
                    if request.POST.get('asignado_a'):
                        filtro.fecha_asignacion = timezone.now()
                        filtro.ai_activo = False   # auto-pausar bot al asignar humano
                    else:
                        filtro.fecha_asignacion = None
                        filtro.ai_activo = True    # reactivar bot si se desasigna
                    form = AsignarAgenteForm(request.POST, instance=filtro, request=request)
                    if form.is_valid():
                        filtro = form.save()
                        asignado = filtro.asignado_a
                        log(f"Conversación {filtro.id} asignada a {asignado}", request, "change", obj=filtro.id)
                        # Registrar en historial de asignaciones
                        try:
                            from .models import HistorialAsignacion
                            HistorialAsignacion.objects.create(
                                conversacion=filtro,
                                asignado_a=asignado,
                                asignado_por=request.user,
                                nota=filtro.nota_interna or '',
                            )
                        except Exception:
                            pass
                        if asignado:
                            try:
                                from crm.helpers_asignacion import notificar_agente_asignado
                                notificar_agente_asignado(
                                    filtro, asignado,
                                    motivo='manual',
                                    asignador=request.user,
                                )
                            except Exception:
                                import logging as _lg
                                _lg.getLogger(__name__).exception(
                                    'No se pudo notificar al agente asignado conv=%s', filtro.id,
                                )
                        nombre_asignado = asignado.get_full_name() if asignado else ''
                        # Mensaje de handoff al cliente (si la sesión tiene mensaje configurado)
                        if asignado:
                            try:
                                sesion = filtro.contacto.sesion
                                handoff_msg = getattr(sesion, 'mensaje_handoff', None)
                                if not handoff_msg:
                                    handoff_msg = f'Hola, te atenderá {nombre_asignado}. En breve te contactamos.'
                                service = get_whatsapp_service(sesion)
                                service.send_text_message(
                                    sesion.session_id,
                                    filtro.contacto.from_number,
                                    handoff_msg,
                                    conversacion_id=filtro.id,
                                    simularEscritura=True,
                                )
                            except Exception:
                                pass
                        # JS para actualizar header sin recargar
                        if nombre_asignado:
                            js = (
                                f"$('#asignado-nombre').text({repr(nombre_asignado)});"
                                f"$('#asignado-container').removeClass('d-none');"
                                f"actualizarBotUI(false);"
                                f"bootstrap.Modal.getInstance(document.getElementById('modalDetalle'))?.hide();"
                                f"alertaSuccess('Conversación asignada a {nombre_asignado}. Bot pausado.');"
                            )
                        else:
                            js = (
                                "$('#asignado-container').addClass('d-none');"
                                "actualizarBotUI(true);"
                                "bootstrap.Modal.getInstance(document.getElementById('modalDetalle'))?.hide();"
                                "alertaSuccess('Asignación eliminada. Bot reactivado.');"
                            )
                        res_json.append({
                            'error': False,
                            'reload': False,
                            'function_js': js,
                        })
                        return JsonResponse(res_json, safe=False)
                    else:
                        raise NameError(f'Error al asignar: {form.errors}')
                elif action == 'toggle-bot':
                    filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    filtro.ai_activo = not filtro.ai_activo
                    filtro.save(request)
                    estado = 'activado' if filtro.ai_activo else 'pausado'
                    log(f"Bot {estado} para conversación {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse({'error': False, 'ai_activo': filtro.ai_activo})
                elif action == 'toggle-bloquear-cierre':
                    filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    filtro.bloquear_cierre = not filtro.bloquear_cierre
                    filtro.save(update_fields=['bloquear_cierre'])
                    estado = 'bloqueado' if filtro.bloquear_cierre else 'desbloqueado'
                    log(f"Cierre automático {estado} para conversación {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse({'error': False, 'bloquear_cierre': filtro.bloquear_cierre})
                elif action == 'reiniciar-flujo':
                    # Solo aplica a sesiones con chatbot tradicional. Limpia el
                    # estado del flujo, vuelve al nodo_inicio del depto y dispara
                    # el primer mensaje hacia el cliente.
                    from crm.motor_flujo_chatbot import reiniciar_flujo_tradicional
                    filtro = ConversacionWhatsApp.objects.select_related(
                        'sesion', 'contacto'
                    ).get(pk=int(request.POST['id']))
                    if (filtro.sesion.modo_bot or '') != 'tradicional':
                        return JsonResponse({
                            'error': True,
                            'message': 'Esta acción solo aplica a sesiones con chatbot tradicional.',
                        })
                    resultado = reiniciar_flujo_tradicional(filtro)
                    if resultado.error:
                        return JsonResponse({'error': True, 'message': resultado.error})
                    n_respuestas = len(resultado.respuestas or [])
                    log(f"Flujo reiniciado manualmente en conversación {filtro.id} "
                        f"({n_respuestas} mensajes enviados)",
                        request, "change", obj=filtro.id)
                    return JsonResponse({
                        'error': False,
                        'message': f'Flujo reiniciado. {n_respuestas} mensaje(s) enviado(s) al cliente.',
                        'respuestas_enviadas': n_respuestas,
                    })
                elif action == 'marcar-resuelto':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    # cerrar() ya no levanta excepción si la despedida falla
                    # — cierra igual y deja traza fin_conversacion con nivel
                    # 'error'. Esto evita que un fallo de envío (ventana 24h
                    # Meta, Node caído, etc.) bloquee el cierre manual.
                    filtro.cerrar(enviar_despedida=True)
                    filtro.refresh_from_db(fields=['despedida_enviado'])
                    msg_extra = '' if filtro.despedida_enviado else \
                        ' Despedida no enviada — revisá /whatsapp/trazas/ filtrando fin_conversacion.'
                    res_json.append({
                        'error': False,
                        'url': '/whatsapp/conversaciones-finalizadas/',
                        'message': f'Conversación cerrada.{msg_extra}',
                        'despedida_enviada': filtro.despedida_enviado,
                    })
                    request.session['contactoId'] = encrypt(filtro.id)
                    log(f"Conversación marcada como resuelta {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse(res_json, safe=False)
                elif action == 'terminar-sin-despedida':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    filtro.cerrar(enviar_despedida=False)
                    res_json.append({'error': False, 'url': '/whatsapp/conversaciones-finalizadas/'})
                    request.session['contactoId'] = encrypt(filtro.id)
                    log(f"Conversación marcada como resuelta {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse(res_json, safe=False)
                elif action == 'transcribe_audio':
                    # transcribe_audio es provider-agnostic: solo procesa el archivo local
                    # con whisper, no habla con Node ni Meta. Usar WhatsAppService directo
                    # esta OK aqui (el dispatcher no aplica porque MetaWhatsAppService
                    # delega esta misma funcion a WhatsAppService internamente).
                    service = WhatsAppService()
                    msg = MensajeWhatsApp.objects.select_related('conversacion__contacto__sesion').get(id=request.POST['id'])
                    service.transcribe_audio(msg, 'small', msg.conversacion.contacto.sesion.language.split('-')[0])
                    return JsonResponse({})

                elif action == 'feedback-mensaje':
                    from crm.models import FeedbackMensajeBot
                    msg_id = int(request.POST['mensaje_id'])
                    es_correcto = request.POST.get('es_correcto') == '1'
                    correccion = request.POST.get('correccion', '').strip()
                    pregunta = request.POST.get('pregunta', '').strip()

                    msg = MensajeWhatsApp.objects.select_related(
                        'conversacion__contacto__sesion__agente_ia'
                    ).get(pk=msg_id)

                    # Crear o actualizar feedback
                    feedback, _ = FeedbackMensajeBot.objects.update_or_create(
                        mensaje=msg,
                        defaults={
                            'es_correcto': es_correcto,
                            'correccion': correccion,
                            'pregunta_original': pregunta,
                            'agente': msg.conversacion.sesion.agente_ia,
                            'usuario': request.user,
                            'procesado_vectorstore': False,
                        }
                    )

                    # Si es incorrecto y hay corrección → crear FAQ aprobada + FAISS
                    if not es_correcto and correccion and pregunta:
                        agente = msg.conversacion.sesion.agente_ia
                        if agente:
                            # 1. Crear FaqAgente directamente aprobada (el humano ya validó)
                            try:
                                from crm.models import FaqAgente
                                from django.utils import timezone as _tz
                                ya_existe = FaqAgente.objects.filter(
                                    agente=agente, pregunta__iexact=pregunta.strip(),
                                ).first()
                                if ya_existe:
                                    ya_existe.respuesta = correccion.strip()[:4000]
                                    ya_existe.estado = 'aprobada'
                                    ya_existe.origen = 'feedback'
                                    ya_existe.mensaje_origen = msg
                                    ya_existe.fecha_aprobacion = _tz.now()
                                    ya_existe.usuario_aprobacion = request.user
                                    ya_existe.save()
                                else:
                                    FaqAgente.objects.create(
                                        agente=agente,
                                        pregunta=pregunta.strip()[:2000],
                                        respuesta=correccion.strip()[:4000],
                                        origen='feedback',
                                        estado='aprobada',
                                        conversacion_origen=msg.conversacion,
                                        mensaje_origen=msg,
                                        fecha_aprobacion=_tz.now(),
                                        usuario_aprobacion=request.user,
                                    )
                            except Exception as ex:
                                log(f"Error creando FaqAgente desde feedback: {ex}", request, "error")

                            # 2. Agregar al FAISS si está configurado (compatibilidad)
                            if agente.vectorstore_path and agente.apikey.filter(estado=True).exists():
                                apikey_obj = agente.apikey.filter(estado=True).first()
                                provider = {2: 'gemini', 3: 'openai'}.get(apikey_obj.proveedor, 'gemini')
                                try:
                                    from agents_ai.vectorstore_manager import VectorStoreManager
                                    import os
                                    from django.conf import settings
                                    storage = os.path.join(settings.MEDIA_ROOT, 'vectorstores')
                                    vsm = VectorStoreManager(storage, provider, apikey_obj.descripcion)
                                    vsm.add_correction(agente.vectorstore_path, pregunta, correccion)
                                    feedback.procesado_vectorstore = True
                                    feedback.save(update_fields=['procesado_vectorstore'])
                                    from agents_ai.agente_consultor import AgenteConsultor
                                    AgenteConsultor._faiss_cache.clear()
                                except Exception as ex:
                                    log(f"Error al agregar corrección al vectorstore: {ex}", request, "error")

                    return JsonResponse({
                        'error': False,
                        'procesado_vectorstore': feedback.procesado_vectorstore,
                        'mensaje': 'Feedback guardado' + (' y agregado al vectorstore ✓' if feedback.procesado_vectorstore else ''),
                    })


        except Exception as ex:
            # forms.js espera array para recorrer con forEach — envolver en lista.
            return JsonResponse([{'error': True, 'message': str(ex)}], safe=False)

    # ====================== LISTADO CONVERSACIONES =========================
    criterio = request.GET.get('criterio', '').strip()
    filtro_clasificacion = request.GET.get('clasificacion', '')
    filtro_sin_responder = request.GET.get('sin_responder', '')
    filtro_mis_conv = request.GET.get('mis_conv', '')

    filtros = Q(
        contacto__status=True, status=True,
        contacto__sesion__in=sesiones_visibles(request.user),
        contacto__sesion__status=True,
        estado_conversacion=0
    )
    url_vars = ''

    if sesion_seleccionada:
        filtros = filtros & Q(contacto__sesion=sesion_seleccionada)
        filtros = filtros & filtro_conversaciones_por_rol(request.user, sesion_seleccionada)
        url_vars += f'&sesion={encrypt_sesion_id(sesion_seleccionada.id)}'

    if criterio:
        filtros = filtros & (Q(contacto__contacto_numero__icontains=criterio) | Q(contacto__contacto_nombre__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio

    if filtro_clasificacion:
        filtros = filtros & Q(clasificacion=filtro_clasificacion)
        data["filtro_clasificacion"] = int(filtro_clasificacion)
        url_vars += f'&clasificacion={filtro_clasificacion}'

    if filtro_sin_responder:
        # Último mensaje es del cliente (remitente != numero de sesión)
        filtros = filtros & ~Q(mensajes__remitente=models.F('contacto__sesion__numero')) & Q(mensajes__isnull=False)
        # Más preciso: anotar el last mensaje y verificar
        from django.db.models import Max, Subquery, OuterRef
        ultimo_msg = MensajeWhatsApp.objects.filter(
            conversacion=OuterRef('pk')
        ).order_by('-fecha').values('remitente')[:1]
        filtros = filtros & ~Q(mensajes__isnull=True)
        data["filtro_sin_responder"] = True
        url_vars += '&sin_responder=1'

    if filtro_mis_conv:
        filtros = filtros & Q(asignado_a=request.user)
        data["filtro_mis_conv"] = True
        url_vars += '&mis_conv=1'

    data["url_vars"] = url_vars
    data['conversacion_selected'] = conversacion_selected
    data["today"] = timezone.now().date()
    data["SENTIMIENTO_CHOICES"] = SENTIMIENTO_CHOICES
    from .models import ESTADOS_CLASIFICACION
    data["ESTADOS_CLASIFICACION"] = ESTADOS_CLASIFICACION

    # Conteo global de conversaciones sin leer (para badge en header)
    badge_scope = Q(contacto__sesion__in=sesiones_visibles(request.user)) & (
        Q(contacto__sesion__in=sesiones_vista_completa(request.user))
        | Q(asignado_a=request.user)
    )
    data["total_sin_leer"] = ConversacionWhatsApp.objects.filter(
        badge_scope,
        contacto__status=True, status=True,
        estado_conversacion=0,
        mensajes__leido=False,
        mensajes__remitente=models.F('contacto__contacto_numero')
    ).distinct().count()

    # Si es una solicitud AJAX para cargar conversaciones
    if request.GET.get('load_conversations'):
        from django.db import models as django_models
        from django.db.models import OuterRef, Subquery
        # select_related sobre los FK que el partial usa (foto, nombre,
        # numero de la sesión, foto del contacto). Sin esto, el render del
        # partial dispara N+1 queries por cada item del listado.
        qs = (
            ConversacionWhatsApp.objects.sin_expirar
            .filter(filtros)
            .select_related(
                'contacto',
                'contacto__sesion',
                'contacto__sesion__config_meta',
                'contacto__sesion__config_baileys',
                'asignado_a',
            )
            .distinct()
        )

        # Filtro "sin responder": antes iteraba toda la lista en Python y
        # hacía 1 query por conv para traer el último mensaje (N+1 enorme).
        # Ahora usamos Subquery para resolverlo en un solo SQL.
        if filtro_sin_responder:
            ultimo_remitente = (
                MensajeWhatsApp.objects
                .filter(conversacion=OuterRef('pk'))
                .order_by('-fecha')
                .values('remitente')[:1]
            )
            numero_sesion = SesionWhatsApp.objects.filter(
                pk=OuterRef('contacto__sesion_id')
            ).values('numero')[:1]
            qs = qs.annotate(
                _ultimo_remitente=Subquery(ultimo_remitente),
                _numero_sesion=Subquery(numero_sesion),
            ).exclude(_ultimo_remitente__isnull=True).exclude(
                _ultimo_remitente=django_models.F('_numero_sesion')
            )

        mostrar_supervisor = es_vista_completa(request.user, sesion_seleccionada)
        if mostrar_supervisor:
            ultimo_remitente_sup = (
                MensajeWhatsApp.objects
                .filter(conversacion=OuterRef('pk'))
                .order_by('-fecha')
                .values('remitente')[:1]
            )
            ultima_fecha_sup = (
                MensajeWhatsApp.objects
                .filter(conversacion=OuterRef('pk'))
                .order_by('-fecha')
                .values('fecha')[:1]
            )
            qs = qs.annotate(
                sup_ultimo_remitente=Subquery(ultimo_remitente_sup),
                sup_fecha_ultimo=Subquery(ultima_fecha_sup),
            )

        ultima_fecha_entrante = (
            MensajeWhatsApp.objects
            .filter(conversacion=OuterRef('pk'))
            .exclude(remitente=OuterRef('contacto__sesion__numero'))
            .order_by('-fecha')
            .values('fecha')[:1]
        )
        qs = qs.annotate(
            fecha_ultimo_entrante=Subquery(ultima_fecha_entrante),
        )

        from datetime import timedelta as _td
        ahora_ts = timezone.now()
        conv_list = list(qs)
        for _c in conv_list:
            if getattr(_c, 'atendida_por_meta', False) and getattr(_c, 'fecha_ultimo_entrante', None):
                _c.vence_meta_en = _c.fecha_ultimo_entrante + _td(hours=24)
                _c.vence_meta_expirada = _c.vence_meta_en <= ahora_ts
            else:
                _c.vence_meta_en = None
                _c.vence_meta_expirada = False

        return JsonResponse({
            'html': render_to_string('whatsapp/conversaciones/conversaciones_partial.html',
                                    {
                                        'conversaciones': conv_list,
                                        'today': ahora_ts.date(),
                                        'now': ahora_ts,
                                        'es_vista_completa': mostrar_supervisor,
                                        'sesion_numero': sesion_seleccionada.numero if sesion_seleccionada else '',
                                    },
                                    request=request)
        })

    # Pipelines disponibles para el modal "Asignar a pipeline"
    from .models import PipelineVenta as _PV
    data['pipelines_disponibles'] = (
        _PV.objects.filter(status=True).prefetch_related('etapas').order_by('-es_default', 'nombre')
    )
    return render(request, 'whatsapp/conversaciones/listado.html', data)
