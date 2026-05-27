"""Helpers compartidos por view_conversaciones y view_conversaciones_finalizadas.

Cada handler acá adentro recibe `request` y devuelve un `JsonResponse` listo
para que la vista lo retorne. La idea es no duplicar la misma lógica en dos
archivos cuando las acciones (cambiar nombre, cambiar clasificación, etc.)
funcionan idénticamente para conversaciones activas y finalizadas.

También centraliza utilidades que se consumen desde ambos archivos:
    - `_estadisticas_conversacion`, `_control_respuestas`, `_tokens_conversacion`
    - `_bloqueo_reactivar` + constante `HORAS_VENTANA_REACTIVAR`
"""

from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.template.loader import get_template, render_to_string
from django.utils import timezone

from core.funciones import log

from .forms import CambiarClasificacionForm, CambiarNombreContactoForm
from .models import ConversacionWhatsApp


HORAS_VENTANA_REACTIVAR = 23

HORAS_VENTANA_META_CUSTOMER_SERVICE = 24


def _bloqueo_ventana_meta(conversacion):
    """Regla de Meta: solo se pueden enviar mensajes de texto libre dentro de
    las 24h desde el último mensaje entrante del cliente. Fuera de esa ventana
    hay que usar plantilla aprobada para retomar la conversación.

    Aplica únicamente a sesiones Meta Cloud API. Para Baileys/Instagram/Messenger
    devolvemos `(False, None)` (sin bloqueo).

    Retorna `(bloqueada, vence_en)`. `bloqueada=True` significa que NO se puede
    enviar texto libre — hay que usar plantilla.
    """
    sesion = getattr(conversacion, 'sesion', None)
    if not sesion or not getattr(sesion, 'es_meta', False):
        return False, None

    from .models import MensajeWhatsApp
    ultimo_entrante = (
        MensajeWhatsApp.objects
        .filter(conversacion=conversacion)
        .exclude(remitente=sesion.numero)
        .order_by('-fecha')
        .first()
    )
    if not ultimo_entrante:
        return True, None
    vence_en = ultimo_entrante.fecha + timedelta(hours=HORAS_VENTANA_META_CUSTOMER_SERVICE)
    return timezone.now() > vence_en, vence_en


def reactivar_conversacion(conversacion):
    """Pone la conversación de vuelta en estado activo. Espejo de lo que hace
    `marcar-reactivar` pero invocable desde otras acciones (ej. `send`)."""
    conversacion.estado_conversacion = 0
    conversacion.fecha_fin_conversacion = None
    conversacion.despedida_enviado = False
    conversacion.conversacion_finalizada = False
    conversacion.save(update_fields=[
        'estado_conversacion', 'fecha_fin_conversacion',
        'despedida_enviado', 'conversacion_finalizada',
    ])


def _bloqueo_reactivar(conversacion):
    """Permite reactivar/enviar solo dentro de las primeras N horas desde fecha_registro.

    Retorna (bloqueada, vence_en). `bloqueada=True` cuando la conversación tiene
    más de N horas — fuera de la ventana de gracia ya no se puede revivir.
    """
    if not conversacion.fecha_registro:
        return False, None
    vence_en = conversacion.fecha_registro + timedelta(hours=HORAS_VENTANA_REACTIVAR)
    return timezone.now() > vence_en, vence_en


def _control_respuestas(conversacion):
    """Estadísticas de participación por tipo de remitente."""
    try:
        qs = conversacion.mensajes.filter(remitente=conversacion.sesion.numero)
        ia_count = qs.filter(ia_generado=True).count()
        agent_qs = qs.filter(ia_generado=False, agente__isnull=False)
        agent_count = agent_qs.count()
        agentes = list(
            agent_qs.values(
                'agente__id', 'agente__first_name', 'agente__last_name', 'agente__foto'
            ).annotate(total=Count('id')).order_by('-total')
        )
        return {
            'cr_ia': ia_count,
            'cr_agent': agent_count,
            'cr_agentes': agentes,
        }
    except Exception:
        return {'cr_ia': 0, 'cr_agent': 0, 'cr_agentes': []}


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


def _estadisticas_conversacion(conversacion):
    """Dict completo de estadísticas para el panel de la conversación."""
    try:
        tok = conversacion.consumos_token.aggregate(
            t_in=Sum('tokens_entrada'), t_out=Sum('tokens_salida'), t_total=Sum('tokens_total'),
        )
        tokens_in = tok['t_in'] or 0
        tokens_out = tok['t_out'] or 0
        tokens_tot = tok['t_total'] or 0
        modelo_top = (
            conversacion.consumos_token.values('modelo')
            .annotate(n=Count('id')).order_by('-n')
            .values_list('modelo', flat=True).first() or ''
        )
    except Exception:
        tokens_in = tokens_out = tokens_tot = 0
        modelo_top = ''

    try:
        stats = conversacion.estadisticas
        total_msgs = stats.total_mensajes
        msgs_cliente = stats.mensajes_cliente
        msgs_asesor = stats.mensajes_asesor
        msgs_ia = stats.mensajes_ia
    except Exception:
        total_msgs = msgs_cliente = msgs_asesor = msgs_ia = 0

    try:
        inicio = conversacion.fecha_registro
        fin = conversacion.fecha_fin_conversacion or timezone.now()
        if inicio and fin:
            if hasattr(fin, 'tzinfo') and fin.tzinfo and (not hasattr(inicio, 'tzinfo') or not inicio.tzinfo):
                fin = fin.replace(tzinfo=None)
            delta = fin - inicio
            mins = int(delta.total_seconds() // 60)
            horas = mins // 60
            mins_r = mins % 60
            duracion = f'{horas}h {mins_r}m' if horas else f'{mins_r} min'
        else:
            duracion = '—'
    except Exception:
        duracion = '—'

    if conversacion.estado_conversacion == 0:
        estado_badge = '<span class="badge bg-success">Activa</span>'
    else:
        estado_badge = '<span class="badge bg-secondary">Finalizada</span>'

    primer_agente = ''
    try:
        if conversacion.primer_agente:
            primer_agente = conversacion.primer_agente.get_full_name() or conversacion.primer_agente.username
    except Exception:
        pass

    cr = _control_respuestas(conversacion)

    return {
        'tokens_entrada': tokens_in,
        'tokens_salida': tokens_out,
        'tokens_total': tokens_tot,
        'modelo_ia': modelo_top,
        'total_mensajes': total_msgs,
        'mensajes_cliente': msgs_cliente,
        'mensajes_asesor': msgs_asesor,
        'mensajes_ia': msgs_ia,
        'duracion': duracion,
        'estado_badge': estado_badge,
        'primer_agente': primer_agente,
        **cr,
    }


def cambiar_clasificacion_get(request):
    try:
        filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
        form = CambiarClasificacionForm(instance=filtro)
        ctx = {
            'form': form,
            'filtro': filtro,
            'action': 'cambiar-clasificacion',
            'ruta': request.path,
        }
        return JsonResponse({
            'result': True,
            'data': render_to_string('whatsapp/conversaciones/form.html', ctx, request=request),
        })
    except Exception as ex:
        return JsonResponse({'result': False, 'message': str(ex)})


def cambiar_clasificacion_post(request):
    try:
        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
    except Exception as ex:
        return JsonResponse([{'error': True, 'message': f'No se encontró la conversación: {ex}'}], safe=False)

    form = CambiarClasificacionForm(request.POST, instance=filtro, request=request)
    if form.is_valid():
        form.save()
        log(f"Clasificación cambiada para la conversación {filtro.id}", request, 'edit', obj=filtro.id)
        messages.success(request, 'Clasificación cambiada correctamente.')
        return JsonResponse([{'error': False, 'reload': True}], safe=False)
    return JsonResponse(
        [{'error': True, 'message': f'Error al guardar la clasificación: {form.errors}'}],
        safe=False,
    )


def cambiar_nombre_contacto_get(request):
    try:
        filtro = ConversacionWhatsApp.objects.get(pk=int(request.GET['id']))
        form = CambiarNombreContactoForm(instance=filtro.contacto)
        ctx = {
            'form': form,
            'filtro': filtro,
            'action': 'cambiar-nombre-contacto',
            'ruta': request.path,
        }
        return JsonResponse({
            'result': True,
            'data': render_to_string('whatsapp/conversaciones/form.html', ctx, request=request),
        })
    except Exception as ex:
        return JsonResponse({'result': False, 'message': str(ex)})


def historial_cliente_list(request, conversacion):
    contacto = conversacion.contacto
    qs = (
        ConversacionWhatsApp.objects
        .filter(contacto=contacto, status=True)
        .order_by('-fecha_registro')
    )
    items = []
    for c in qs:
        finalizada = bool(c.conversacion_finalizada or c.estado_conversacion == 1)
        items.append({
            'id': c.id,
            'es_actual': c.id == conversacion.id,
            'finalizada': finalizada,
            'fecha_inicio': c.fecha_registro.strftime('%d/%m/%Y %H:%M') if c.fecha_registro else '',
            'fecha_inicio_corta': c.fecha_registro.strftime('%d/%m/%y') if c.fecha_registro else '',
            'fecha_fin': c.fecha_fin_conversacion.strftime('%d/%m/%Y %H:%M') if c.fecha_fin_conversacion else '',
            'total_mensajes': c.mensajes.filter(status=True).count(),
            'clasificacion': c.get_clasificacion_display() if c.clasificacion else '',
            'sentimiento': c.sentimiento or '',
            'resumen': (c.resumen_conversacion or '')[:240],
        })
    return JsonResponse({
        'error': False,
        'conversaciones': items,
        'contacto_nombre': contacto.contacto_nombre or contacto.contacto_numero or '',
        'contacto_numero': contacto.contacto_numero or '',
    })


def historial_cliente_mensajes(request, conversacion):
    from .models import MensajeWhatsApp
    mensajes = (
        MensajeWhatsApp.objects
        .filter(conversacion=conversacion, status=True)
        .order_by('fecha')
    )
    html = render_to_string(
        'whatsapp/conversaciones/mensajes_partial.html',
        {'conversacion': conversacion, 'mensajes': mensajes},
        request=request,
    )
    finalizada = bool(conversacion.conversacion_finalizada or conversacion.estado_conversacion == 1)
    return JsonResponse({
        'error': False,
        'html': html,
        'conversacion_id': conversacion.id,
        'finalizada': finalizada,
        'fecha_inicio': conversacion.fecha_registro.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_registro else '',
        'fecha_fin': conversacion.fecha_fin_conversacion.strftime('%d/%m/%Y %H:%M') if conversacion.fecha_fin_conversacion else '',
        'total_mensajes': mensajes.count(),
        'clasificacion': conversacion.get_clasificacion_display() if conversacion.clasificacion else '',
        'resumen': conversacion.resumen_conversacion or '',
    })


def cambiar_nombre_contacto_post(request):
    try:
        filtro = ConversacionWhatsApp.objects.get(pk=int(request.POST['pk']))
    except Exception as ex:
        return JsonResponse([{'error': True, 'message': f'No se encontró la conversación: {ex}'}], safe=False)

    contacto = filtro.contacto
    form = CambiarNombreContactoForm(request.POST, instance=contacto, request=request)
    if form.is_valid():
        form.save()
        log(
            f"Nombre de contacto {contacto.__str__()} cambiado para la conversación {filtro.id}",
            request, 'change', obj=filtro.id,
        )
        messages.success(request, 'Nombre de contacto cambiado correctamente.')
        return JsonResponse([{'error': False, 'reload': True}], safe=False)
    return JsonResponse(
        [{'error': True, 'message': f'Error al guardar el nombre: {form.errors}'}],
        safe=False,
    )


def listar_plantillas_meta(request):
    """GET: lista plantillas Meta APPROVED de la sesión de una conversación.

    Compartido por las vistas de finalizadas y pendiente-reconexión para poblar
    el panel de plantillas.
    """
    from django.shortcuts import get_object_or_404
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


def enviar_plantilla_reconexion(request):
    """POST: envía una plantilla Meta a una conversación finalizada como sonda
    de reconexión.

    La conversación NO se reactiva: queda finalizada (estado 1) marcada con
    `pendiente_reconexion=True`. Si el cliente responde, el webhook entrante
    crea una conversación nueva enlazada por `conv_origen` (ver
    `ConversacionWhatsApp.obtener_o_crear_activa`). Compartido por las vistas de
    finalizadas y pendiente-reconexión.
    """
    import json as _json
    from django.shortcuts import get_object_or_404
    from .models import PlantillaWhatsApp, MensajeWhatsApp
    from .services import get_whatsapp_service

    pk = int(request.POST['pk'])
    plantilla_id = int(request.POST['plantilla_id'])
    params_cuerpo = _json.loads(request.POST.get('params_cuerpo_json') or '[]')
    params_header = _json.loads(request.POST.get('params_header_json') or '[]')

    conversacion = get_object_or_404(ConversacionWhatsApp, pk=pk)

    sesion = conversacion.sesion
    if not getattr(sesion, 'es_meta', False):
        return JsonResponse({'error': True, 'message': 'The session is not Meta.'})
    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'error': True, 'message': 'Meta configuration not found.'})
    plantilla = PlantillaWhatsApp.objects.filter(
        pk=plantilla_id, config_meta=config, status=True, estado_meta='APPROVED'
    ).first()
    if not plantilla:
        return JsonResponse({'error': True, 'message': 'Template unavailable or not approved.'})

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
            'message': f"Error sending template: {response.get('error', 'Unknown error')}",
        })

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

    conversacion.pendiente_reconexion = True
    conversacion.reconectada = False
    conversacion.save(update_fields=['pendiente_reconexion', 'reconectada'])

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

    if not conversacion.primer_agente:
        conversacion.primer_agente = request.user
        conversacion.save(update_fields=['primer_agente'])

    log(
        f"Reconnection template '{plantilla.nombre}' sent on conversation {conversacion.id}; marked pending reconnection",
        request, "add", obj=conversacion.id,
    )

    return JsonResponse({
        'error': False,
        'pendiente': True,
        'message': 'Template sent. Conversation marked as pending reconnection.',
        'mensaje_html': render_to_string(
            'whatsapp/conversaciones/mensaje_enviado_partial.html',
            {'mensaje': mensaje}, request=request,
        ),
    })
