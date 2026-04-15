from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from core.funciones import addData, paginador, secure_module
from .models import TrazaMensajeIA, SesionWhatsApp, ETAPAS_TRAZA


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
        conv_id = request.GET.get('conversacion_id')
        msg_id = request.GET.get('mensaje_id')
        numero = request.GET.get('numero')
        filtros = Q()
        if msg_id:
            filtros &= Q(mensaje_id=msg_id)
        elif conv_id:
            filtros &= Q(conversacion_id=conv_id)
        elif numero:
            filtros &= Q(numero__icontains=numero)
        trazas = TrazaMensajeIA.objects.filter(filtros).order_by('fecha', 'id')[:500]
        template = get_template('whatsapp/trazas/timeline.html')
        return JsonResponse({
            'result': True,
            'data': template.render({'trazas': trazas, 'request': request}),
        })

    # ===== LISTADO PRINCIPAL =====
    # Filtrar a las sesiones del usuario actual
    sesiones_usuario = SesionWhatsApp.objects.filter(
        usuario_id=request.user.id, status=True
    ).values_list('id', flat=True)

    filtros = Q(sesion_id__in=list(sesiones_usuario))

    numero = (request.GET.get('numero') or '').strip()
    sesion_filtro = request.GET.get('sesion') or ''
    etapa_filtro = request.GET.get('etapa') or ''
    nivel_filtro = request.GET.get('nivel') or ''
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
        url_vars += f'&sesion={sesion_filtro}'
    if etapa_filtro:
        filtros &= Q(etapa=etapa_filtro)
        data['etapa_sel'] = etapa_filtro
        url_vars += f'&etapa={etapa_filtro}'
    if nivel_filtro:
        filtros &= Q(nivel=nivel_filtro)
        data['nivel_sel'] = nivel_filtro
        url_vars += f'&nivel={nivel_filtro}'
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
        'sesion', 'conversacion', 'conversacion__contacto', 'mensaje'
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
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    paginador(request, listado, 30, data, url_vars)
    return render(request, 'whatsapp/trazas/listado.html', data)
