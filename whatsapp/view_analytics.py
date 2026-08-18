"""Dashboard de analytics con gráficos.

Sirve datos JSON para Chart.js desde la misma view (?action=data).
Soporta filtros: ?dias=7|30|90  &  ?sesion=<id>
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.funciones import addData, secure_module, leer_sesion_id
from .permisos_sesion import sesiones_vista_completa
from .models import (
    Campana,
    ConversacionEnPipeline,
    ConversacionWhatsApp,
    EventoCAPI,
    EstadisticasConversacion,
    MensajeWhatsApp,
    SesionWhatsApp,
)


def _rango_fechas(request):
    """Devuelve (desde_dt, hasta_dt, dias_efectivos, modo).

    Acepta dos modos:
      - ?dias=7|30|90 (default 30)
      - ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD (rango personalizado)

    Si vienen ambos, prevalece desde/hasta.
    """
    from datetime import datetime, time as _time
    desde_str = (request.GET.get('desde') or '').strip()
    hasta_str = (request.GET.get('hasta') or '').strip()
    if desde_str:
        try:
            desde_d = datetime.strptime(desde_str, '%Y-%m-%d').date()
            hasta_d = (datetime.strptime(hasta_str, '%Y-%m-%d').date()
                       if hasta_str else timezone.now().date())
            tz = timezone.get_current_timezone()
            desde_dt = timezone.make_aware(datetime.combine(desde_d, _time.min), tz)
            hasta_dt = timezone.make_aware(datetime.combine(hasta_d, _time.max), tz)
            dias_eff = max(1, (hasta_d - desde_d).days + 1)
            return desde_dt, hasta_dt, dias_eff, 'custom'
        except Exception:
            pass
    dias = int(request.GET.get('dias', 30) or 30)
    desde_dt = timezone.now() - timedelta(days=dias)
    return desde_dt, timezone.now(), dias, 'preset'


def _sesion_filtro(request):
    """Devuelve el id de sesión del filtro (int) o None. Acepta token cifrado o crudo."""
    return leer_sesion_id(request)


@login_required
@secure_module
def analyticsView(request):
    data = {
        'titulo': 'Analytics',
        'descripcion': 'Dashboard con métricas, ROI y atribución de campañas',
        'ruta': request.path,
    }
    addData(request, data)

    desde_dt, hasta_dt, dias, modo = _rango_fechas(request)
    sesion_id = _sesion_filtro(request)

    # Scope multicanal: dueño de la sesión O supervisor (igual que /supervision/,
    # y todas las redes comparten esta vista). Antes se limitaba a las sesiones
    # propias, dejando ciegos a los supervisores. Superuser ve todo.
    sesiones_scope = sesiones_vista_completa(request.user)

    # Conversaciones del rango. ConversacionWhatsApp.sesion es @cached_property,
    # el campo real es contacto.sesion -> usamos contacto__sesion__*
    conv_qs = ConversacionWhatsApp.objects.filter(
        fecha_registro__gte=desde_dt, fecha_registro__lte=hasta_dt, status=True,
        contacto__sesion__in=sesiones_scope,
    )
    if sesion_id:
        conv_qs = conv_qs.filter(contacto__sesion_id=sesion_id)

    msgs_qs = MensajeWhatsApp.objects.filter(
        fecha__gte=desde_dt, fecha__lte=hasta_dt,
        conversacion__contacto__sesion__in=sesiones_scope,
    )
    if sesion_id:
        msgs_qs = msgs_qs.filter(conversacion__contacto__sesion_id=sesion_id)

    if request.GET.get('format') == 'json' or request.GET.get('action') == 'data':
        try:
            return _data_json(request, conv_qs, msgs_qs, sesion_id, dias, desde_dt, hasta_dt)
        except Exception as ex:
            import logging
            logging.getLogger(__name__).exception('Error generando data analytics')
            return JsonResponse({'error': True, 'message': str(ex)}, status=500)

    data['rango_dias'] = dias
    data['rango_modo'] = modo
    data['fecha_desde'] = desde_dt.date().isoformat()
    data['fecha_hasta'] = hasta_dt.date().isoformat()
    data['sesion_sel'] = sesion_id
    data['sesiones'] = sesiones_scope.order_by('nombre')
    if sesion_id:
        data['sesion_actual'] = data['sesiones'].filter(pk=sesion_id).first()
    return render(request, 'whatsapp/analytics/dashboard.html', data)


def _data_json(request, conv_qs, msgs_qs, sesion_id, dias, desde_dt, hasta_dt):
    # ----- KPIs cards -----
    total_conv = conv_qs.count()
    total_cerradas = conv_qs.filter(conversacion_finalizada=True).count()
    total_abiertas = total_conv - total_cerradas
    total_clientes = conv_qs.filter(clasificacion=4).count()
    total_leads = conv_qs.filter(clasificacion__in=[1, 2, 3]).count()
    total_msgs = msgs_qs.count()
    total_msgs_ia = msgs_qs.filter(ia_generado=True).count()

    # ----- Recepción / emisión -----
    q_saliente = Q(ia_generado=True) | Q(es_automatico=True) | Q(agente__isnull=False)
    total_entrantes = msgs_qs.filter(~q_saliente).count()
    total_salientes = msgs_qs.filter(q_saliente).count()
    total_humanos = msgs_qs.filter(agente__isnull=False).count()
    total_automaticos = msgs_qs.filter(
        es_automatico=True, ia_generado=False, agente__isnull=True,
    ).count()

    # ----- Consumo Meta Cloud API (conversaciones facturables) -----
    meta_conv_qs = conv_qs.filter(contacto__sesion__proveedor='meta')
    total_conv_meta = meta_conv_qs.count()
    total_msgs_meta = msgs_qs.filter(
        conversacion__contacto__sesion__proveedor='meta',
    ).count()
    total_plantillas_enviadas = msgs_qs.filter(
        conversacion__contacto__sesion__proveedor='meta',
        es_automatico=True,
    ).count()

    # ----- Tiempos de respuesta -----
    tiempos = EstadisticasConversacion.objects.filter(
        conversacion__in=conv_qs,
    ).aggregate(
        primera=Avg('tiempo_primera_respuesta'),
        promedio=Avg('tiempo_respuesta_promedio'),
    )

    def _tdsec(td):
        return round(td.total_seconds(), 1) if td else 0

    # ----- Consumo por sesión (path correcto: contacto__sesion__*) -----
    consumo_por_sesion = list(
        msgs_qs.values(
            'conversacion__contacto__sesion__id',
            'conversacion__contacto__sesion__nombre',
            'conversacion__contacto__sesion__numero',
            'conversacion__contacto__sesion__proveedor',
        ).annotate(
            mensajes=Count('id'),
            entrantes=Count('id', filter=~q_saliente),
            salientes=Count('id', filter=q_saliente),
            ia=Count('id', filter=Q(ia_generado=True)),
        ).order_by('-mensajes')[:15]
    )
    # Renombrar claves para que el frontend no tenga que llevar el prefijo largo
    consumo_por_sesion = [
        {
            'sesion_id':       r['conversacion__contacto__sesion__id'],
            'sesion_nombre':   r['conversacion__contacto__sesion__nombre'],
            'sesion_numero':   r['conversacion__contacto__sesion__numero'],
            'sesion_proveedor': r['conversacion__contacto__sesion__proveedor'],
            'mensajes':  r['mensajes'],
            'entrantes': r['entrantes'],
            'salientes': r['salientes'],
            'ia':        r['ia'],
        }
        for r in consumo_por_sesion
    ]

    # ----- Conversaciones por día -----
    por_dia = list(
        conv_qs.annotate(d=TruncDate('fecha_registro'))
               .values('d')
               .annotate(n=Count('id'))
               .order_by('d')
    )

    # ----- Por clasificación -----
    por_clasificacion = list(
        conv_qs.values('clasificacion').annotate(n=Count('id')).order_by('clasificacion')
    )

    # ----- Por canal de origen -----
    por_canal = list(
        conv_qs.values('origen_canal').annotate(n=Count('id')).order_by('origen_canal')
    )

    # ----- Sentimiento -----
    por_sentimiento = list(
        conv_qs.exclude(sentimiento='').values('sentimiento')
               .annotate(n=Count('id')).order_by('-n')
    )

    # ----- Ranking agentes -----
    ranking_agentes = list(
        msgs_qs.filter(agente__isnull=False)
               .values('agente__id', 'agente__username',
                       'agente__first_name', 'agente__last_name')
               .annotate(n=Count('id'))
               .order_by('-n')[:10]
    )

    # ----- ROI por campaña CTWA -----
    roi_ctwa = list(
        conv_qs.exclude(ctwa_clid__isnull=True).exclude(ctwa_clid='')
               .values('campaign_id', 'ad_id')
               .annotate(
                   total=Count('id'),
                   leads=Count('id', filter=Q(clasificacion__in=[1, 2, 3])),
                   clientes=Count('id', filter=Q(clasificacion=4)),
               )
               .order_by('-total')[:20]
    )
    # Enriquecer con nombres legibles desde la caché (sin pegarle a Meta).
    try:
        from .services_ads import nombres_de_anuncios
        _nombres = nombres_de_anuncios([r['ad_id'] for r in roi_ctwa if r.get('ad_id')])
        for r in roi_ctwa:
            info = _nombres.get(r.get('ad_id') or '', {})
            r['ad_name'] = info.get('ad_name', '')
            r['campaign_name'] = info.get('campaign_name', '')
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Error enriqueciendo roi_ctwa con nombres')

    # ----- Pipeline forecast -----
    sesiones_scope = sesiones_vista_completa(request.user)
    pipeline_qs = ConversacionEnPipeline.objects.filter(
        status=True,
        conversacion__contacto__sesion__in=sesiones_scope,
    )
    if sesion_id:
        pipeline_qs = pipeline_qs.filter(conversacion__contacto__sesion_id=sesion_id)
    pipeline_forecast = list(
        pipeline_qs.values('etapa__pipeline__nombre', 'etapa__nombre',
                           'etapa__probabilidad_cierre', 'moneda')
                  .annotate(total=Sum('valor_estimado'), n=Count('id'))
                  .order_by('etapa__pipeline__nombre', 'etapa__orden')
    )

    # ----- Campañas recientes -----
    camp_qs = Campana.objects.filter(
        status=True,
        fecha_registro__gte=desde_dt, fecha_registro__lte=hasta_dt,
        sesion__in=sesiones_scope,
    )
    if sesion_id:
        camp_qs = camp_qs.filter(sesion_id=sesion_id)
    campanas_recientes = list(
        camp_qs.values('id', 'nombre', 'estado', 'total_objetivo',
                       'total_enviados', 'total_fallidos', 'total_respondidos')
              .order_by('-fecha_registro')[:10]
    )

    # ----- CAPI events -----
    capi_qs = EventoCAPI.objects.filter(
        event_time__gte=desde_dt, event_time__lte=hasta_dt,
        conversacion__contacto__sesion__in=sesiones_scope,
    )
    if sesion_id:
        capi_qs = capi_qs.filter(conversacion__contacto__sesion_id=sesion_id)
    capi_stats = capi_qs.aggregate(
        total=Count('id'),
        ok=Count('id', filter=Q(exitoso=True)),
        valor_total=Sum('valor'),
    )

    return JsonResponse({
        'sesion_filtro': sesion_id,
        'rango_dias': dias,
        'kpis': {
            'total_conversaciones': total_conv,
            'cerradas':  total_cerradas,
            'abiertas':  total_abiertas,
            'clientes':  total_clientes,
            'leads':     total_leads,
            'mensajes':  total_msgs,
            'mensajes_ia': total_msgs_ia,
            'pct_ia': round(100 * total_msgs_ia / total_msgs, 1) if total_msgs else 0,
            'entrantes': total_entrantes,
            'salientes': total_salientes,
            'humanos':   total_humanos,
            'automaticos': total_automaticos,
            'pct_recepcion': round(100 * total_entrantes / total_msgs, 1) if total_msgs else 0,
            'meta_conversaciones': total_conv_meta,
            'meta_mensajes': total_msgs_meta,
            'meta_plantillas': total_plantillas_enviadas,
            'tiempo_primera_respuesta_seg': _tdsec(tiempos.get('primera')),
            'tiempo_respuesta_promedio_seg': _tdsec(tiempos.get('promedio')),
        },
        'consumo_por_sesion': consumo_por_sesion,
        'por_dia':           [{'d': str(r['d']), 'n': r['n']} for r in por_dia],
        'por_clasificacion': por_clasificacion,
        'por_canal':         por_canal,
        'por_sentimiento':   por_sentimiento,
        'ranking_agentes':   ranking_agentes,
        'roi_ctwa':          roi_ctwa,
        'pipeline_forecast': [
            {**r, 'total': float(r['total'] or 0)} for r in pipeline_forecast
        ],
        'campanas_recientes': campanas_recientes,
        'capi': {
            'total':       capi_stats.get('total') or 0,
            'ok':          capi_stats.get('ok') or 0,
            'valor_total': float(capi_stats.get('valor_total') or 0),
        },
    })
