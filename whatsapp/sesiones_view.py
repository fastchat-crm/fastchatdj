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
from .forms import SesionWhatsAppForm, ConfigMetaForm, ConfigInstagramForm, ConfigMessengerForm
from .models import SesionWhatsApp, ConfigMeta, ConfigInstagram, ConfigMessenger
from .services import WhatsAppService, get_whatsapp_service
from .sesiones_common import (
    hint_error_meta as _hint_error_meta_shared,
    hint_como_texto as _hint_como_texto_shared,
    sincronizar_meta_desde_graph as _sincronizar_meta_desde_graph_shared,
)
from .sesiones_meta_view import handle_meta_action as _handle_meta_action
from .sesiones_baileys_view import handle_baileys_action as _handle_baileys_action


# Wrappers locales para retrocompat con los usos internos de este archivo.
# Cuando se terminen de mover las acciones Meta a sesiones_meta_view.py estos
# wrappers dejan de ser necesarios; por ahora evitan tener 2 copias del codigo.
def _hint_error_meta(error_text):
    return _hint_error_meta_shared(error_text)


def _hint_como_texto(hint):
    return _hint_como_texto_shared(hint)


def _sincronizar_meta_desde_graph(session, config, timeout=10):
    return _sincronizar_meta_desde_graph_shared(session, config, timeout)


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
        # Delegacion: acciones Meta viven en sesiones_meta_view.py,
        # acciones Baileys en sesiones_baileys_view.py.
        # Si la accion matchea, devuelven JsonResponse; si no, None.
        _meta_resp = _handle_meta_action(request, action, perfil)
        if _meta_resp is not None:
            return _meta_resp
        _bail_resp = _handle_baileys_action(request, action)
        if _bail_resp is not None:
            return _bail_resp
        try:
            with transaction.atomic():
                # Las acciones Baileys (add, create_session, verificar_conexion,
                # reconectar, delete) las maneja `_handle_baileys_action()` arriba.
                # Las acciones Meta las maneja `_handle_meta_action()` arriba.
                if action == 'probar_envio_mensaje':
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
                    err_raw = resultado.get('error') or 'No se pudo enviar el mensaje de prueba.'
                    hint = _hint_error_meta(err_raw) if filtro.es_meta else {}
                    return JsonResponse({
                        'error':          True,
                        'message':        str(err_raw) + _hint_como_texto(hint),
                        'hint':           (hint or {}).get('text') or None,
                        'hint_link':      (hint or {}).get('link') or None,
                        'hint_link_label': (hint or {}).get('link_label') or None,
                        'raw':            err_raw,
                        'destino':        destino_fmt,
                    })
                # NOTA: 'probar_envio_plantilla_meta' se maneja via _handle_meta_action()
                # al inicio del bloque POST. Ya no vive aqui — vive en sesiones_meta_view.py.
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

                # Las acciones Meta (guardar_config_meta, regenerar_verify_token,
                # verificar_meta_conexion, add_meta, probar_envio_plantilla_meta)
                # se manejan via `_handle_meta_action()` al comienzo del POST.
                # Si llegaron aqui es porque no matchearon — tratamos como "accion desconocida".

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
        # IG + Messenger forms (mismo patron — null-safe si no hay config aun)
        data['config_instagram'] = config_ig = getattr(instance, 'config_instagram', None)
        data['config_instagram_form'] = ConfigInstagramForm(instance=config_ig) if config_ig else ConfigInstagramForm()
        data['config_messenger'] = config_fb = getattr(instance, 'config_messenger', None)
        data['config_messenger_form'] = ConfigMessengerForm(instance=config_fb) if config_fb else ConfigMessengerForm()
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
            data['config_instagram'] = config_ig = getattr(instance, 'config_instagram', None) if instance else None
            data['config_instagram_form'] = ConfigInstagramForm(instance=config_ig) if config_ig else ConfigInstagramForm()
            data['config_messenger'] = config_fb = getattr(instance, 'config_messenger', None) if instance else None
            data['config_messenger_form'] = ConfigMessengerForm(instance=config_fb) if config_fb else ConfigMessengerForm()
            data['meta_webhook_url'] = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
            template = get_template("whatsapp/sesiones/form_modal.html")
            return JsonResponse({"result": True, 'data': template.render(data)})
        except Exception as ex:
            return JsonResponse({"result": False, 'message': str(ex)})
    if action == 'historial_de_sesiones':
        data['instance'] = instance = SesionWhatsApp.objects.get(id=request.GET['pk'])
        data['listado'] = instance.get_log_entries().filter(change_message__istartswith='HS: ')
        return render(request, 'whatsapp/sesiones/historial_de_sesiones.html', data)
    if action == 'resumen_meta':
        # Modal-resumen de configuración Meta: qué está configurado y qué falta
        try:
            instance = SesionWhatsApp.objects.get(id=request.GET['pk'], usuario=request.user)
        except SesionWhatsApp.DoesNotExist:
            return JsonResponse({'result': False, 'message': 'Sesión no encontrada'})
        if instance.proveedor != 'meta':
            return JsonResponse({'result': False, 'message': 'Esta vista solo aplica a sesiones Meta.'})

        cfg = getattr(instance, 'config_meta', None)
        checks = []
        # 1. Credenciales Meta
        checks.append({
            'nombre': 'Credenciales Meta Cloud API',
            'ok':     bool(cfg and cfg.waba_id and cfg.phone_number_id and cfg.access_token),
            'detalle': (
                f'WABA: {cfg.waba_id} · Phone: {cfg.display_phone_number or cfg.phone_number_id}'
                if cfg and cfg.waba_id else 'Sin WABA/Phone Number ID/Access Token configurados.'
            ),
            'accion_url': f'/whatsapp/sesiones/?action=change_modal&pk={instance.id}',
            'accion_label': 'Configurar credenciales',
        })
        # 2. Webhook verificado
        checks.append({
            'nombre': 'Webhook Meta verificado',
            'ok':     bool(cfg and cfg.webhook_verificado_en),
            'detalle': (
                f'Verificado el {cfg.webhook_verificado_en:%Y-%m-%d %H:%M}'
                if cfg and cfg.webhook_verificado_en
                else 'El callback en Meta Developer Portal aún no validó el verify_token.'
            ),
            'accion_url': 'https://developers.facebook.com/apps',
            'accion_label': 'Abrir Meta Developer',
        })
        # 3. App secret (firma HMAC)
        checks.append({
            'nombre': 'App Secret configurado (firma HMAC)',
            'ok':     bool(cfg and cfg.app_secret),
            'detalle': 'Valida la autenticidad de cada webhook entrante.' if cfg and cfg.app_secret else 'Sin app_secret: los webhooks se aceptan sin validación HMAC.',
            'accion_url': f'/whatsapp/sesiones/?action=change_modal&pk={instance.id}',
            'accion_label': 'Editar sesión',
        })
        # 4. Quality rating
        checks.append({
            'nombre': 'Quality rating',
            'ok':     bool(cfg and cfg.quality_rating in ('GREEN', 'YELLOW')),
            'detalle': f'Meta reporta: {cfg.get_quality_rating_display() if cfg else "Desconocida"}',
            'accion_url': None,
            'accion_label': None,
        })
        # 5. Agente IA
        checks.append({
            'nombre': 'Agente IA asignado',
            'ok':     bool(instance.agente_ia),
            'detalle': f'Agente: {instance.agente_ia.nombre}' if instance.agente_ia else 'Sin agente IA: las conversaciones no se responden automáticamente.',
            'accion_url': f'/whatsapp/sesiones/?action=change_modal&pk={instance.id}',
            'accion_label': 'Asignar agente',
        })
        # 6. Plantillas aprobadas
        from .models import PlantillaWhatsApp
        plantillas_ok = PlantillaWhatsApp.objects.filter(
            config_meta=cfg, estado_meta='APPROVED', status=True,
        ).count() if cfg else 0
        checks.append({
            'nombre': 'Plantillas aprobadas por Meta',
            'ok':     plantillas_ok > 0,
            'detalle': f'{plantillas_ok} plantilla(s) aprobadas.' if plantillas_ok else 'Sin plantillas aprobadas: no podrás iniciar conversaciones fuera de la ventana de 24h.',
            'accion_url': f'/whatsapp/plantillas/?sesion={instance.id}',
            'accion_label': 'Gestionar plantillas',
        })
        # 7. Horarios de atención
        horarios_n = instance.horarios.filter(status=True, activo=True).count()
        checks.append({
            'nombre': 'Horarios de atención',
            'ok':     horarios_n > 0,
            'detalle': f'{horarios_n} franja(s) horaria(s) activa(s).' if horarios_n else 'Sin horarios: la sesión responde 24/7.',
            'accion_url': f'/whatsapp/horarios/?sesion={instance.id}',
            'accion_label': 'Configurar horarios',
        })
        # 8. Pixel Meta / CAPI
        checks.append({
            'nombre': 'Pixel Meta (CAPI) para atribución Ads',
            'ok':     bool(instance.pixel_meta_id),
            'detalle': f'Pixel: {instance.pixel_meta.nombre}' if instance.pixel_meta_id else 'Sin pixel vinculado: no se reportarán conversiones a Meta Ads.',
            'accion_url': '/admin/whatsapp/pixelmeta/',
            'accion_label': 'Crear/vincular pixel',
        })
        # 9. Campañas
        campanas_n = instance.campanas.filter(status=True).count()
        checks.append({
            'nombre': 'Campañas creadas',
            'ok':     campanas_n > 0,
            'detalle': f'{campanas_n} campaña(s) creada(s) en esta sesión.' if campanas_n else 'Aún no has creado campañas para esta sesión.',
            'accion_url': f'/whatsapp/campanas/?sesion={instance.id}',
            'accion_label': 'Ver campañas',
        })
        # 10. Round-robin
        checks.append({
            'nombre': 'Asignación automática (round-robin)',
            'ok':     bool(instance.auto_asignar_round_robin),
            'detalle': 'Activado: nuevas conversaciones se asignan a agentes disponibles.' if instance.auto_asignar_round_robin else 'Desactivado: las conversaciones requieren asignación manual.',
            'accion_url': f'/whatsapp/sesiones/?action=change_modal&pk={instance.id}',
            'accion_label': 'Activar',
        })

        total_ok = sum(1 for c in checks if c['ok'])
        data['sesion'] = instance
        data['config_meta'] = cfg
        data['checks'] = checks
        data['total_ok'] = total_ok
        data['total_checks'] = len(checks)
        data['completitud_pct'] = int(100 * total_ok / len(checks))
        data['webhook_url'] = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
        template = get_template("whatsapp/sesiones/resumen_meta.html")
        return JsonResponse({"result": True, 'data': template.render(data)})
    criterio, filtros, url_vars = request.GET.get('criterio', '').strip(), Q(status=True, usuario_id=request.user.id), ''
    estado = request.GET.get('estado', '')
    # Filtro por proveedor: lo inyectan sesionesMetaView / sesionesBaileysView
    # para que cada URL muestre solo sus sesiones. Si no viene, muestra todas.
    proveedor_filtro = request.GET.get('proveedor', '').strip()
    if criterio:
        filtros = filtros & (Q(numero__icontains=criterio))
        data["criterio"] = criterio
        url_vars += '&criterio=' + criterio
    if estado:
        filtros &= Q(estado=estado)
        data["estado"] = estado
        url_vars += '&estado=' + estado
    if proveedor_filtro in ('baileys', 'meta', 'instagram', 'messenger'):
        filtros &= Q(proveedor=proveedor_filtro)
        data["proveedor_filtro"] = proveedor_filtro
        url_vars += '&proveedor=' + proveedor_filtro

    listado = model.objects.filter(filtros)
    data["list_count"] = listado.count()
    data["url_vars"] = url_vars

    base_qs = model.objects.filter(status=True, usuario_id=request.user.id)
    stats_raw = {row['estado']: row['total'] for row in base_qs.values('estado').annotate(total=Count('id'))}
    # Conteo por proveedor para los cards de "elegir camino" arriba del listado.
    prov_raw = {row['proveedor']: row['total'] for row in base_qs.values('proveedor').annotate(total=Count('id'))}
    data['stats_proveedor'] = {
        'baileys':   prov_raw.get('baileys',   0),
        'meta':      prov_raw.get('meta',      0),
        'instagram': prov_raw.get('instagram', 0),
        'messenger': prov_raw.get('messenger', 0),
    }
    data['stats'] = {
        'total': sum(stats_raw.values()),
        'conectado': stats_raw.get('conectado', 0),
        'pendiente': stats_raw.get('pendiente', 0),
        'desconectado': stats_raw.get('desconectado', 0),
        'error': stats_raw.get('error', 0),
    }

    paginador(request, listado.order_by('numero'), 12, data, url_vars)
    return render(request, 'whatsapp/sesiones/listado.html', data)