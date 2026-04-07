from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.db.models import Q, Sum
from django.contrib import messages
from django.template.loader import render_to_string, get_template
from django.utils import timezone
from django.http import JsonResponse

from autenticacion.models import Usuario
from core.funciones import addData, paginador, secure_module, log
from seguridad.templatetags.templatefunctions import encrypt
from .forms import CambiarClasificacionForm, CambiarNombreContactoForm, AsignarAgenteForm
from .models import ConversacionWhatsApp, MensajeWhatsApp, SesionWhatsApp, SENTIMIENTO_CHOICES
from .services import WhatsAppService

def _tokens_conversacion(conversacion):
    """Agrega tokens IA consumidos en una conversación."""
    try:
        agg = conversacion.consumos_token.aggregate(
            t_in=Sum('tokens_entrada'),
            t_out=Sum('tokens_salida'),
            t_total=Sum('tokens_total'),
        )
        return {
            'tokens_entrada': agg['t_in'] or 0,
            'tokens_salida': agg['t_out'] or 0,
            'tokens_total': agg['t_total'] or 0,
        }
    except Exception:
        return {'tokens_entrada': 0, 'tokens_salida': 0, 'tokens_total': 0}


@login_required
@secure_module
def conversacionesView(request):
    data = {
        'titulo': 'Conversaciones WhatsApp',
        'modulo': 'Conversaciones WhatsApp',
        'ruta': request.path
    }
    addData(request, data)

    # Obtener todas las sesiones activas
    sesiones = SesionWhatsApp.objects.filter(usuario_id=request.user.id, status=True, estado='conectado').order_by('-ultima_conexion')
    data['sesiones'] = sesiones

    # Sesión seleccionada (por defecto la primera)
    sesion_id = request.GET.get('sesion_id')
    contactoId = request.session.pop('contactoId', None)
    conversacion_selected = None
    if contactoId:
        try:
            conversacion_selected = ConversacionWhatsApp.objects.get(pk=int(encrypt(contactoId)))
            sesion_id = conversacion_selected.sesion.id
        except Exception as ex:
            raise NameError(f'No se encontró la conversación: {ex}')
    if sesion_id:
        sesion_seleccionada = get_object_or_404(SesionWhatsApp, id=sesion_id)
    elif sesiones.exists():
        sesion_seleccionada = sesiones.first()
    else:
        sesion_seleccionada = None

    data['sesion_seleccionada'] = sesion_seleccionada

    # ====================== VER MENSAJES =========================
    if request.method == 'GET' and 'action' in request.GET:
        data['action'] = action = request.GET['action']
        if action == 'ver_mensajes':
            pk = int(request.GET['pk'])
            conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)
            mensajes = MensajeWhatsApp.objects.filter(conversacion=conversacion).order_by('fecha')
            data['conversacion'] = conversacion
            data['mensajes'] = mensajes
            return JsonResponse({
                'html': render_to_string('whatsapp/conversaciones/mensajes_partial.html', data, request=request),
                'conversacion_id': conversacion.id,
                'contacto_nombre': conversacion.contacto_nombre or '',
                'contacto_numero': conversacion.contacto_numero,
                'contacto_foto': conversacion.contacto_foto or '',
                'hashed_id': conversacion.hashed_id or '',
                'estado_active': conversacion.estado_conversacion == 0,
                'ai_activo': conversacion.ai_activo,
                'asignado_a': conversacion.asignado_a.get_full_name() if conversacion.asignado_a else '',
                'asignado_foto': conversacion.asignado_a.get_foto_url() if conversacion.asignado_a else '',
                'nota_interna': conversacion.nota_interna or '',
                'fecha_asignacion': conversacion.fecha_asignacion.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_asignacion else '',
                'fecha_inicio': conversacion.fecha_registro.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_registro else '',
                **_tokens_conversacion(conversacion),
            })
        elif action == 'cambiar-clasificacion':
            try:
                filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
                form = CambiarClasificacionForm(instance=filtro)
                data.update({
                    'form': form,
                    'filtro': filtro,
                })
                template = get_template("whatsapp/conversaciones/form.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})
        elif action == 'cambiar-nombre-contacto':
            try:
                filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
                form = CambiarNombreContactoForm(instance=filtro.contacto)
                data.update({
                    'form': form,
                    'filtro': filtro,
                })
                template = get_template("whatsapp/conversaciones/form.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})
        elif action == 'asignar-conversacion':
            try:
                filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
                form = AsignarAgenteForm(instance=filtro)
                data.update({'form': form, 'filtro': filtro})
                template = get_template("whatsapp/conversaciones/form.html")
                return JsonResponse({"result": True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({"result": False, 'message': str(ex)})

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

                    # Crear instancia del servicio
                    service = WhatsAppService()

                    if archivo:
                        response = service.send_media_message(
                            conversacion.sesion.session_id, conversacion.from_number, caption=texto,
                            file_content=archivo.read(), filename=archivo.name
                        )
                    else:
                        response = service.send_text_message(
                            conversacion.sesion.session_id, conversacion.from_number, texto
                        )

                    if not response.get('success', False):
                        return JsonResponse({
                            'error': True,
                            'message': f"Error al enviar mensaje: {response.get('message', 'Error desconocido')}"
                        })

                    # Determinar tipo de mensaje
                    tipo_mensaje = 'texto'
                    archivo_url = None

                    if archivo:
                        # Determinar tipo basado en el content_type
                        content_type = archivo.content_type
                        if 'image' in content_type:
                            tipo_mensaje = 'imagen'
                        elif 'audio' in content_type:
                            tipo_mensaje = 'audio'
                        elif 'video' in content_type:
                            tipo_mensaje = 'video'
                        else:
                            tipo_mensaje = 'documento'

                        # Si la respuesta incluye una URL del archivo, guardarla
                        archivo_url = response.get('media_url')

                    # Guardamos en BD
                    mensaje = MensajeWhatsApp(
                        mensaje_id_externo=response.get('message_id'),
                        conversacion=conversacion,
                        remitente=conversacion.sesion.numero,
                        mensaje=texto,
                        tipo=tipo_mensaje,
                        archivo_url=archivo_url,
                        fecha=timezone.now(),
                        leido=True,
                        fecha_leido=timezone.now()
                    )
                    mensaje.save()

                    log(f"Mensaje enviado a {conversacion.contacto_numero}", request, "add", obj=conversacion.id)

                    # Devolver el HTML del mensaje para añadirlo al chat
                    return JsonResponse({
                        'error': False,
                        'mensaje_html': render_to_string('whatsapp/conversaciones/mensaje_enviado_partial.html',
                                                        {'mensaje': mensaje},
                                                        request=request)
                    })
                elif action == 'cambiar-clasificacion':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    form = CambiarClasificacionForm(request.POST, instance=filtro, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Clasificación cambiada para la conversación {filtro.id}", request, "edit", obj=filtro.id)
                        res_json.append({'error': False, 'reload': True})
                        messages.success(request, 'Clasificación cambiada correctamente.')
                        return JsonResponse(res_json, safe=False)
                    else:
                        raise NameError(f'Error al guardar la clasificación: {form.errors}')
                elif action == 'cambiar-nombre-contacto':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    contacto = filtro.contacto
                    form = CambiarNombreContactoForm(request.POST, instance=contacto, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Nombre de contacto {contacto.__str__()} cambiado para la conversación {filtro.id}", request, "change", obj=filtro.id)
                        res_json.append({'error': False, 'reload': True})
                        messages.success(request, 'Nombre de contacto cambiada correctamente.')
                        return JsonResponse(res_json, safe=False)
                    else:
                        raise NameError(f'Error al guardar la clasificación: {form.errors}')
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
                        # Notificar al agente asignado vía Notificacion
                        if asignado:
                            try:
                                from seguridad.models import Notificacion
                                contacto_nombre = filtro.contacto.contacto_nombre or filtro.contacto.from_number
                                Notificacion.objects.create(
                                    usuario=asignado,
                                    titulo='Conversación asignada',
                                    mensaje=f'Se te asignó la conversación con {contacto_nombre}.',
                                    url='/whatsapp/conversaciones/',
                                    prioridad=2,
                                    tipo=1,
                                )
                            except Exception:
                                pass
                        nombre_asignado = asignado.get_full_name() if asignado else ''
                        # Mensaje de handoff al cliente (si la sesión tiene mensaje configurado)
                        if asignado:
                            try:
                                sesion = filtro.contacto.sesion
                                handoff_msg = getattr(sesion, 'mensaje_handoff', None)
                                if not handoff_msg:
                                    handoff_msg = f'Hola, te atenderá {nombre_asignado}. En breve te contactamos.'
                                service = WhatsAppService()
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
                elif action == 'marcar-resuelto':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    contacto = filtro.contacto
                    if contacto.sesion.mensaje_despedida:
                        from_number = contacto.from_number
                        session_id = contacto.sesion.session_id
                        # Crear instancia del servicio
                        service = WhatsAppService()
                        result = service.send_text_message(session_id, from_number, contacto.sesion.mensaje_despedida, conversacion_id=filtro.id, simularEscritura=True)
                        if not result.get('success'):
                            raise NameError(f'{result.get("error", "Error desconocido")}')
                        filtro.despedida_enviado = True
                    filtro.estado_conversacion = 1
                    filtro.fecha_fin_conversacion = timezone.now()
                    res_json.append({ 'error':False, 'url': f'/whatsapp/conversaciones-finalizadas/' })
                    request.session['contactoId'] = encrypt(filtro.id)
                    filtro.resumir_conversacion()
                    filtro.save(request)
                    log(f"Conversación marcada como resuelta {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse(res_json, safe=False)
                elif action == 'terminar-sin-despedida':
                    try:
                        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['id']))
                    except Exception as ex:
                        raise NameError(f'No se encontró la conversación: {ex}')
                    filtro.estado_conversacion = 1
                    filtro.fecha_fin_conversacion = timezone.now()
                    res_json.append({ 'error':False, 'url': f'/whatsapp/conversaciones-finalizadas/' })
                    request.session['contactoId'] = encrypt(filtro.id)
                    filtro.resumir_conversacion()
                    filtro.save(request)
                    log(f"Conversación marcada como resuelta {filtro.id}", request, "change", obj=filtro.id)
                    return JsonResponse(res_json, safe=False)
                elif action == 'transcribe_audio':
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

                    # Si es incorrecto y hay corrección → agregar al vectorstore
                    if not es_correcto and correccion and pregunta:
                        agente = msg.conversacion.sesion.agente_ia
                        if agente and agente.vectorstore_path and agente.apikey.filter(estado=True).exists():
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
                                # Invalidar caché de FAISS del agente
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
            return JsonResponse({'error': True, 'message': str(ex)})

    # ====================== LISTADO CONVERSACIONES =========================
    criterio = request.GET.get('criterio', '').strip()
    filtro_clasificacion = request.GET.get('clasificacion', '')
    filtro_sin_responder = request.GET.get('sin_responder', '')
    filtro_mis_conv = request.GET.get('mis_conv', '')

    filtros = Q(
        contacto__status=True, status=True,
        contacto__sesion__usuario__id=request.user.id,
        contacto__sesion__status=True,
        estado_conversacion=0
    )
    url_vars = ''

    if sesion_seleccionada:
        filtros = filtros & Q(contacto__sesion=sesion_seleccionada)
        url_vars += f'&sesion_id={sesion_seleccionada.id}'

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
    data["total_sin_leer"] = ConversacionWhatsApp.objects.filter(
        contacto__status=True, status=True,
        contacto__sesion__usuario__id=request.user.id,
        estado_conversacion=0,
        mensajes__leido=False,
        mensajes__remitente=models.F('contacto__contacto_numero')
    ).distinct().count()

    # Si es una solicitud AJAX para cargar conversaciones
    if request.GET.get('load_conversations'):
        from django.db import models as django_models
        qs = ConversacionWhatsApp.objects.sin_expirar.filter(filtros).distinct()

        # Filtro sin responder via Python post-query (más seguro)
        if filtro_sin_responder:
            ids_sin_resp = []
            for conv in qs:
                ultimo = conv.mensajes.order_by('-fecha').first()
                if ultimo and ultimo.remitente != conv.sesion.numero:
                    ids_sin_resp.append(conv.id)
            qs = qs.filter(id__in=ids_sin_resp)

        return JsonResponse({
            'html': render_to_string('whatsapp/conversaciones/conversaciones_partial.html',
                                    {'conversaciones': qs, 'today': timezone.now().date()},
                                    request=request)
        })

    return render(request, 'whatsapp/conversaciones/listado.html', data)
