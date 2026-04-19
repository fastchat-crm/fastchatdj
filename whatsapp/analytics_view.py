"""Dashboard de analytics con gráficos. Sirve datos JSON para Chart.js
desde la misma view (action=data)."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.funciones import addData, secure_module
from .models import (
    Campana,
    ConversacionEnPipeline,
    ConversacionWhatsApp,
    EnvioCampana,
    EstadisticasConversacion,
    EventoCAPI,
    MensajeWhatsApp,
    SesionWhatsApp,
)


def _rango_fechas(request):
    dias = int(request.GET.get('dias', 30) or 30)
    desde = timezone.now() - timedelta(days=dias)
    return desde, dias


@login_required
@secure_module
def analyticsView(request):
    data = {
        'titulo': 'Analytics',
        'descripcion': 'Dashboard con métricas, ROI y atribución de campañas',
        'ruta': request.path,
    }
    addData(request, data)

    desde, dias = _rango_fechas(request)
    base_qs = ConversacionWhatsApp.objects.filter(fecha_registro__gte=desde, status=True)

    if request.GET.get('format') == 'json' or request.GET.get('action') == 'data':
        # ----- KPIs cards -----
        total_conv = base_qs.count()
        total_cerradas = base_qs.filter(conversacion_finalizada=True).count()
        total_abiertas = total_conv - total_cerradas
        total_clientes = base_qs.filter(clasificacion=4).count()
        total_leads = base_qs.filter(clasificacion__in=[1, 2, 3]).count()
        msgs_qs = MensajeWhatsApp.objects.filter(fecha__gte=desde)
        total_msgs = msgs_qs.count()
        total_msgs_ia = msgs_qs.filter(ia_generado=True).count()

        # ----- Recepción / emisión -----
        q_saliente = Q(ia_generado=True) | Q(es_automatico=True) | Q(agente__isnull=False)
        total_entrantes = msgs_qs.filter(~q_saliente).count()
        total_salientes = msgs_qs.filter(q_saliente).count()
        total_humanos = msgs_qs.filter(agente__isnull=False).count()
        total_automaticos = msgs_qs.filter(es_automatico=True, ia_generado=False, agente__isnull=True).count()

        # ----- Consumo Meta Cloud API (conversaciones facturables) -----
        meta_conv_qs = base_qs.filter(sesion__proveedor='meta')
        total_conv_meta = meta_conv_qs.count()
        total_msgs_meta = msgs_qs.filter(conversacion__sesion__proveedor='meta').count()
        total_plantillas_enviadas = msgs_qs.filter(
            conversacion__sesion__proveedor='meta',
            es_automatico=True,
        ).count()

        # ----- Tiempos de respuesta (segundos) -----
        tiempos = EstadisticasConversacion.objects.filter(
            conversacion__in=base_qs,
        ).aggregate(
            primera=Avg('tiempo_primera_respuesta'),
            promedio=Avg('tiempo_respuesta_promedio'),
        )
        def _tdsec(td):
            return round(td.total_seconds(), 1) if td else 0

        # ----- Consumo por sesión -----
        consumo_por_sesion = list(
            msgs_qs.values(
                'conversacion__sesion__id',
                'conversacion__sesion__nombre',
                'conversacion__sesion__numero',
                'conversacion__sesion__proveedor',
            ).annotate(
                mensajes=Count('id'),
                entrantes=Count('id', filter=~q_saliente),
                salientes=Count('id', filter=q_saliente),
                ia=Count('id', filter=Q(ia_generado=True)),
            ).order_by('-mensajes')[:15]
        )

        # ----- Conversaciones por día -----
        from django.db.models.functions import TruncDate
        por_dia = list(
            base_qs.annotate(d=TruncDate('fecha_registro'))
                   .values('d')
                   .annotate(n=Count('id'))
                   .order_by('d')
        )

        # ----- Por clasificación -----
        por_clasificacion = list(
            base_qs.values('clasificacion').annotate(n=Count('id')).order_by('clasificacion')
        )

        # ----- Por canal de origen -----
        por_canal = list(
            base_qs.values('origen_canal').annotate(n=Count('id')).order_by('origen_canal')
        )

        # ----- Sentimiento -----
        por_sentimiento = list(
            base_qs.exclude(sentimiento='').values('sentimiento')
                   .annotate(n=Count('id')).order_by('-n')
        )

        # ----- Ranking agentes -----
        ranking_agentes = list(
            MensajeWhatsApp.objects.filter(fecha__gte=desde, agente__isnull=False)
                .values('agente__id', 'agente__username', 'agente__first_name', 'agente__last_name')
                .annotate(n=Count('id'))
                .order_by('-n')[:10]
        )

        # ----- ROI por campaña CTWA -----
        roi_ctwa = list(
            base_qs.exclude(ctwa_clid__isnull=True).exclude(ctwa_clid='')
                   .values('campaign_id', 'ad_id')
                   .annotate(
                       total=Count('id'),
                       leads=Count('id', filter=Q(clasificacion__in=[1, 2, 3])),
                       clientes=Count('id', filter=Q(clasificacion=4)),
                   )
                   .order_by('-total')[:20]
        )

        # ----- Pipeline forecast -----
        pipeline_forecast = list(
            ConversacionEnPipeline.objects.filter(status=True)
                .values('etapa__pipeline__nombre', 'etapa__nombre',
                        'etapa__probabilidad_cierre', 'moneda')
                .annotate(
                    total=Sum('valor_estimado'),
                    n=Count('id'),
                )
                .order_by('etapa__pipeline__nombre', 'etapa__orden')
        )

        # ----- Campañas -----
        campanas_recientes = list(
            Campana.objects.filter(status=True, fecha_registro__gte=desde)
                .values('id', 'nombre', 'estado', 'total_objetivo',
                        'total_enviados', 'total_fallidos', 'total_respondidos')
                .order_by('-fecha_registro')[:10]
        )

        # ----- CAPI events -----
        capi_stats = EventoCAPI.objects.filter(event_time__gte=desde).aggregate(
            total=Count('id'),
            ok=Count('id', filter=Q(exitoso=True)),
            valor_total=Sum('valor'),
        )

        return JsonResponse({
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
            'rango_dias': dias,
        })

    data['rango_dias'] = dias
    return render(request, 'whatsapp/analytics/dashboard.html', data)
