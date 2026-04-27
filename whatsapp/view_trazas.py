from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from core.funciones import addData, paginador, secure_module, leer_sesion_id, encrypt_sesion_id
from .models import TrazaMensajeIA, SesionWhatsApp, ETAPAS_TRAZA

WS_ETAPAS = ('ws_request', 'ws_respuesta', 'ws_sin_agente', 'ws_error')


@login_required
@secure_module
def trazasView(request):
    """Vista de diagnostico: muestra el pipeline IA agrupado por mensaje del cliente.
    Permite filtrar por numero, sesion, conversacion, estado y rango de fecha.
    Objetivo: saber por que un numero no recibio respuesta del bot.
    """
    data = {
        'titulo': 'Trazas de mensajes IA',
        'descripcion': 'Diagnostico end-to-end del pipeline del bot',
        'ruta': request.path,
    }
    addData(request, data)

    # AJAX: ver timeline completo de un mensaje o conversacion
    if request.GET.get('action') == 'ver_timeline':
        try:
            conv_id = request.GET.get('conversacion_id')
            msg_id = request.GET.get('mensaje_id')
            numero = (request.GET.get('numero') or '').strip()
            # Validacion: ignorar literal 'null'/'None' que llegan del template
            # cuando los FK estan vacios — sino filtraria por string 'null'.
            def _id_valido(v):
                if not v:
                    return False
                if str(v).lower() in ('null', 'none', 'undefined'):
                    return False
                try:
                    int(v)
                    return True
                except (TypeError, ValueError):
                    return False

            filtros = Q()
            if _id_valido(msg_id):
                filtros &= Q(mensaje_id=int(msg_id))
            elif _id_valido(conv_id):
                filtros &= Q(conversacion_id=int(conv_id))
            elif numero:
                filtros &= Q(numero__icontains=numero)
            else:
                # Sin criterio no devolvemos las 500 ultimas — no tiene sentido
                # como "timeline" de un evento puntual.
                return JsonResponse({
                    'result': False,
                    'message': 'Sin criterio (mensaje/conversacion/numero) para construir el timeline.',
                })

            trazas = (
                TrazaMensajeIA.objects
                .filter(filtros)
                .select_related('sesion', 'conversacion', 'mensaje', 'apikey')
                .order_by('fecha', 'id')[:500]
            )
            template = get_template('whatsapp/trazas/timeline.html')
            return JsonResponse({
                'result': True,
                'data': template.render({'trazas': trazas}, request=request),
            })
        except Exception as ex:
            import traceback
            return JsonResponse({
                'result': False,
                'message': f'Error al construir el timeline: {ex}',
                'debug': traceback.format_exc().splitlines()[-3:],
            })

    # ===== LISTADO PRINCIPAL =====
    # Scope: sesiones del usuario + trazas del webservice (apikey del perfil del usuario)
    from crm.models import ApiKeyIA
    sesiones_usuario = SesionWhatsApp.objects.filter(
        usuario_id=request.user.id, status=True
    ).values_list('id', flat=True)

    apikeys_usuario = ApiKeyIA.objects.filter(
        perfil__usuario=request.user, status=True
    ).order_by('alias', 'descripcion')
    apikeys_ids = list(apikeys_usuario.values_list('id', flat=True))

    filtros = (
        Q(sesion_id__in=list(sesiones_usuario))
        | Q(apikey_id__in=apikeys_ids, etapa__in=WS_ETAPAS)
    )

    numero = (request.GET.get('numero') or '').strip()
    sesion_filtro = leer_sesion_id(request)
    etapa_filtro = request.GET.get('etapa') or ''
    nivel_filtro = request.GET.get('nivel') or ''
    apikey_filtro = request.GET.get('apikey') or ''
    solo_webservice = request.GET.get('solo_webservice') == '1'
    solo_problemas = request.GET.get('solo_problemas') == '1'
    fecha_desde = (request.GET.get('fecha_desde') or '').strip()
    fecha_hasta = (request.GET.get('fecha_hasta') or '').strip()

    url_vars = ''
    if numero:
        filtros &= Q(numero__icontains=numero)
        data['numero'] = numero
        url_vars += f'&numero={numero}'
    if sesion_filtro:
        filtros &= Q(sesion_id=sesion_filtro)
        data['sesion_sel'] = int(sesion_filtro)
        url_vars += f'&sesion={encrypt_sesion_id(sesion_filtro)}'
    if etapa_filtro:
        filtros &= Q(etapa=etapa_filtro)
        data['etapa_sel'] = etapa_filtro
        url_vars += f'&etapa={etapa_filtro}'
    if nivel_filtro:
        filtros &= Q(nivel=nivel_filtro)
        data['nivel_sel'] = nivel_filtro
        url_vars += f'&nivel={nivel_filtro}'
    if apikey_filtro:
        try:
            apikey_pk = int(apikey_filtro)
            if apikey_pk in apikeys_ids:
                filtros &= Q(apikey_id=apikey_pk)
                data['apikey_sel'] = apikey_pk
                url_vars += f'&apikey={apikey_pk}'
        except (TypeError, ValueError):
            pass
    if solo_webservice:
        filtros &= Q(etapa__in=WS_ETAPAS)
        data['solo_webservice'] = True
        url_vars += '&solo_webservice=1'
    if solo_problemas:
        filtros &= Q(nivel__in=['error', 'warning'])
        data['solo_problemas'] = True
        url_vars += '&solo_problemas=1'
    if fecha_desde:
        filtros &= Q(fecha__date__gte=fecha_desde)
        data['fecha_desde'] = fecha_desde
        url_vars += f'&fecha_desde={fecha_desde}'
    if fecha_hasta:
        filtros &= Q(fecha__date__lte=fecha_hasta)
        data['fecha_hasta'] = fecha_hasta
        url_vars += f'&fecha_hasta={fecha_hasta}'

    listado = TrazaMensajeIA.objects.filter(filtros).select_related(
        'sesion', 'conversacion', 'conversacion__contacto', 'mensaje', 'apikey'
    ).order_by('-fecha', '-id')

    # Estadisticas del rango filtrado
    stats_qs = TrazaMensajeIA.objects.filter(filtros)
    stats_niveles = {row['nivel']: row['total'] for row in stats_qs.values('nivel').annotate(total=Count('id'))}
    data['stats'] = {
        'total': stats_qs.count(),
        'info': stats_niveles.get('info', 0),
        'success': stats_niveles.get('success', 0),
        'warning': stats_niveles.get('warning', 0),
        'error': stats_niveles.get('error', 0),
    }

    data['etapas'] = ETAPAS_TRAZA
    data['niveles'] = [('info', 'Info'), ('success', 'Exito'), ('warning', 'Advertencia'), ('error', 'Error')]
    data['sesiones'] = SesionWhatsApp.objects.filter(usuario_id=request.user.id, status=True).order_by('numero')
    data['apikeys'] = apikeys_usuario
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    paginador(request, listado, 30, data, url_vars)
    return render(request, 'whatsapp/trazas/listado.html', data)
