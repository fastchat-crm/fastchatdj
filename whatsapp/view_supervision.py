from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Q, Sum
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, secure_module
from .models import (
    ConversacionEnPipeline,
    ConversacionWhatsApp,
    EstadisticasConversacion,
)
from .permisos_sesion import sesiones_vista_completa
from .view_analytics import _rango_fechas, _sesion_filtro


def _tdsec(td):
    return round(td.total_seconds(), 1) if td else 0


@login_required
@secure_module
def supervisionView(request):
    data = {
        'titulo': 'Supervision',
        'descripcion': 'Funnel, forecast and per-agent performance',
        'ruta': request.path,
    }
    addData(request, data)

    desde_dt, hasta_dt, dias, modo = _rango_fechas(request)
    sesion_id = _sesion_filtro(request)
    sesiones_scope = sesiones_vista_completa(request.user)

    conv_qs = ConversacionWhatsApp.objects.filter(
        status=True,
        contacto__sesion__in=sesiones_scope,
        fecha_registro__gte=desde_dt, fecha_registro__lte=hasta_dt,
    )
    if sesion_id:
        conv_qs = conv_qs.filter(contacto__sesion_id=sesion_id)

    if request.GET.get('action') == 'data' or request.GET.get('format') == 'json':
        try:
            return _data_json(request, conv_qs, sesiones_scope, sesion_id)
        except Exception as ex:
            import logging
            logging.getLogger(__name__).exception('Error generando data supervision')
            return JsonResponse({'error': True, 'message': str(ex)}, status=500)

    data['rango_dias'] = dias
    data['rango_modo'] = modo
    data['fecha_desde'] = desde_dt.date().isoformat()
    data['fecha_hasta'] = hasta_dt.date().isoformat()
    data['sesion_sel'] = sesion_id
    data['sesiones'] = sesiones_scope.order_by('nombre')
    if sesion_id:
        data['sesion_actual'] = data['sesiones'].filter(pk=sesion_id).first()
    return render(request, 'whatsapp/supervision/dashboard.html', data)


def _data_json(request, conv_qs, sesiones_scope, sesion_id):
    recibidos = conv_qs.count()
    atendidos = conv_qs.filter(asignado_a__isnull=False).count()
    respondidos = conv_qs.filter(primer_agente__isnull=False).count()
    clasificados = conv_qs.filter(clasificacion__gt=0).count()
    clientes = conv_qs.filter(clasificacion=4).count()

    def _pct(num, den):
        return round(100 * num / den, 1) if den else 0

    funnel = [
        {'clave': 'recibidos',   'etiqueta': 'Received',   'n': recibidos, 'pct': 100.0},
        {'clave': 'atendidos',   'etiqueta': 'Attended',   'n': atendidos, 'pct': _pct(atendidos, recibidos)},
        {'clave': 'respondidos', 'etiqueta': 'Responded',  'n': respondidos, 'pct': _pct(respondidos, recibidos)},
        {'clave': 'clasificados', 'etiqueta': 'Classified', 'n': clasificados, 'pct': _pct(clasificados, recibidos)},
        {'clave': 'clientes',    'etiqueta': 'Clients',     'n': clientes, 'pct': _pct(clientes, recibidos)},
    ]

    por_asesor = list(
        conv_qs.filter(asignado_a__isnull=False)
        .values('asignado_a__id', 'asignado_a__first_name',
                'asignado_a__last_name', 'asignado_a__username')
        .annotate(
            asignadas=Count('id', distinct=True),
            respondidas=Count('id', filter=Q(primer_agente=F('asignado_a')), distinct=True),
            clientes=Count('id', filter=Q(clasificacion=4), distinct=True),
            sin_responder=Count('id', filter=Q(primer_agente__isnull=True), distinct=True),
        )
        .order_by('-asignadas')
    )

    tiempos_asesor = dict(
        EstadisticasConversacion.objects
        .filter(conversacion__in=conv_qs, conversacion__asignado_a__isnull=False)
        .values_list('conversacion__asignado_a_id')
        .annotate(p=Avg('tiempo_primera_respuesta'))
        .values_list('conversacion__asignado_a_id', 'p')
    )

    asesores = []
    for r in por_asesor:
        nombre = f"{r['asignado_a__first_name'] or ''} {r['asignado_a__last_name'] or ''}".strip()
        if not nombre:
            nombre = r['asignado_a__username'] or '—'
        asesores.append({
            'agente_id':    r['asignado_a__id'],
            'agente':       nombre,
            'asignadas':    r['asignadas'],
            'respondidas':  r['respondidas'],
            'clientes':     r['clientes'],
            'sin_responder': r['sin_responder'],
            'pct_respuesta': round(100 * r['respondidas'] / r['asignadas'], 1) if r['asignadas'] else 0,
            'tiempo_primera_respuesta_seg': _tdsec(tiempos_asesor.get(r['asignado_a__id'])),
        })

    pipeline_qs = ConversacionEnPipeline.objects.filter(
        status=True, conversacion__contacto__sesion__in=sesiones_scope,
    )
    if sesion_id:
        pipeline_qs = pipeline_qs.filter(conversacion__contacto__sesion_id=sesion_id)
    forecast_rows = list(
        pipeline_qs.values('etapa__pipeline__nombre', 'etapa__nombre',
                           'etapa__probabilidad_cierre', 'moneda')
                  .annotate(total=Sum('valor_estimado'), n=Count('id'))
                  .order_by('etapa__pipeline__nombre', 'etapa__orden')
    )
    forecast = []
    total_bruto = 0.0
    total_ponderado = 0.0
    for r in forecast_rows:
        bruto = float(r['total'] or 0)
        prob = (r['etapa__probabilidad_cierre'] or 0)
        ponderado = bruto * prob / 100
        total_bruto += bruto
        total_ponderado += ponderado
        forecast.append({
            'pipeline':    r['etapa__pipeline__nombre'],
            'etapa':       r['etapa__nombre'],
            'probabilidad': prob,
            'moneda':      r['moneda'],
            'n':           r['n'],
            'total':       round(bruto, 2),
            'ponderado':   round(ponderado, 2),
        })

    return JsonResponse({
        'sesion_filtro': sesion_id,
        'funnel': funnel,
        'asesores': asesores,
        'forecast': forecast,
        'forecast_total_bruto': round(total_bruto, 2),
        'forecast_total_ponderado': round(total_ponderado, 2),
    })
