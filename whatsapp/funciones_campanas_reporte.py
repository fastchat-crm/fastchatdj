"""Reporte de leads por campaña (vista `campanasView`, acción `reporte`).

Dos fuentes distintas de "campaña", que el reporte muestra por separado:

1. **Campañas del sistema** (`Campana`): los broadcasts que salen de fastchat.
   La conversación NO guarda FK a la campaña (`campana_origen` existe pero nadie
   la escribe), así que el vínculo se resuelve por el contacto al que se le
   envió: `EnvioCampana.contacto` → `Contacto.conversaciones`, acotado a las
   conversaciones que nacieron desde el envío en adelante.

2. **Campañas en redes** (Meta Ads): las conversaciones que entran por un
   anuncio traen `campaign_id`/`ad_id` del referral CTWA/CTIG. Se agrupan por
   `campaign_id` y los nombres salen de `AnuncioMetaCache` (o de la Marketing
   API con la acción `sync_campanas_meta`).

Para cada campaña se reporta: leads que llegaron, clasificación, etiquetas,
si están siendo atendidos y en qué etapa del pipeline están.
"""

from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone

from core.funciones import log

from .models import (
    Campana, ConversacionWhatsApp, EnvioCampana, AnuncioMetaCache,
    ESTADOS_CLASIFICACION,
)


# Clasificaciones que cuentan como lead trabajado (mismo criterio que analytics).
CLASIFICACIONES_LEAD = (1, 2, 3)
CLASIFICACION_CLIENTE = 4


def _resumen_conversaciones(conversaciones):
    """KPIs comunes de un queryset de conversaciones (leads de una campaña)."""
    agregados = conversaciones.aggregate(
        total=Count('id', distinct=True),
        asignados=Count('id', filter=Q(asignado_a__isnull=False), distinct=True),
        atendidos=Count('id', filter=Q(primer_agente__isnull=False), distinct=True),
        abiertas=Count('id', filter=Q(estado_conversacion=0), distinct=True),
        leads=Count('id', filter=Q(clasificacion__in=CLASIFICACIONES_LEAD), distinct=True),
        clientes=Count('id', filter=Q(clasificacion=CLASIFICACION_CLIENTE), distinct=True),
        en_pipeline=Count('id', filter=Q(pipelines__isnull=False), distinct=True),
    )
    agregados['sin_asesor'] = agregados['total'] - agregados['asignados']
    agregados['sin_atender'] = agregados['total'] - agregados['atendidos']
    return agregados


def _desglose_clasificacion(conversaciones):
    """[{'valor', 'label', 'total'}] por clasificación, en el orden del choice."""
    conteos = dict(
        conversaciones.values_list('clasificacion').annotate(
            n=Count('id', distinct=True)
        ).values_list('clasificacion', 'n')
    )
    return [
        {'valor': valor, 'label': label, 'total': conteos.get(valor, 0)}
        for valor, label in ESTADOS_CLASIFICACION
    ]


def _desglose_pipeline(conversaciones):
    """[{'pipeline', 'etapa', 'color', 'total'}] de las cards de esas conversaciones."""
    filas = (
        conversaciones
        .filter(pipelines__isnull=False, pipelines__status=True)
        .values(
            'pipelines__etapa__pipeline__nombre',
            'pipelines__etapa__nombre',
            'pipelines__etapa__color',
            'pipelines__etapa__orden',
        )
        .annotate(total=Count('id', distinct=True))
        .order_by('pipelines__etapa__pipeline__nombre', 'pipelines__etapa__orden')
    )
    return [
        {
            'pipeline': f['pipelines__etapa__pipeline__nombre'] or 'Sin pipeline',
            'etapa': f['pipelines__etapa__nombre'] or 'Sin etapa',
            'color': f['pipelines__etapa__color'] or '#6c757d',
            'total': f['total'],
        }
        for f in filas
    ]


def _desglose_etiquetas(conversaciones, limite=12):
    """Etiquetas del contacto de esas conversaciones, de mayor a menor."""
    filas = (
        conversaciones
        .filter(contacto__etiquetas__isnull=False, contacto__etiquetas__status=True)
        .values('contacto__etiquetas__nombre', 'contacto__etiquetas__color')
        .annotate(total=Count('id', distinct=True))
        .order_by('-total')[:limite]
    )
    return [
        {
            'nombre': f['contacto__etiquetas__nombre'],
            'color': f['contacto__etiquetas__color'] or '#0d6efd',
            'total': f['total'],
        }
        for f in filas
    ]


def conversaciones_de_campana(campana):
    """Conversaciones atribuibles a una campaña del sistema.

    Sin FK directa: se toma el contacto de cada `EnvioCampana` y sus
    conversaciones registradas desde el primer envío de la campaña en adelante,
    para no contar conversaciones anteriores al broadcast.
    """
    contactos = EnvioCampana.objects.filter(campana=campana).values('contacto_id')
    conversaciones = ConversacionWhatsApp.objects.filter(
        status=True, contacto_id__in=contactos,
    )
    desde = campana.fecha_inicio_real or campana.programada_para
    if desde:
        conversaciones = conversaciones.filter(fecha_registro__gte=desde)
    return conversaciones


def reporte_campanas_sistema(sesiones):
    """Una fila por campaña del sistema con sus KPIs de leads."""
    campanas = Campana.objects.filter(
        status=True, sesion__in=sesiones,
    ).select_related('sesion').order_by('-fecha_registro')

    filas = []
    for campana in campanas:
        conversaciones = conversaciones_de_campana(campana)
        resumen = _resumen_conversaciones(conversaciones)
        filas.append({
            'campana': campana,
            'enviados': campana.total_enviados,
            'fallidos': campana.total_fallidos,
            'objetivo': campana.total_objetivo,
            'resumen': resumen,
            'etiquetas': _desglose_etiquetas(conversaciones, limite=5),
            'pipeline': _desglose_pipeline(conversaciones),
        })
    return filas


def reporte_campanas_meta(sesiones):
    """Una fila por campaña de Meta Ads que haya generado conversaciones.

    Agrupa por `campaign_id` del referral CTWA/CTIG y completa el nombre desde
    `AnuncioMetaCache` (que se llena al abrir conversaciones o con la acción
    `sync_campanas_meta`).
    """
    base = ConversacionWhatsApp.objects.filter(
        status=True, contacto__sesion__in=sesiones,
    ).exclude(campaign_id__isnull=True).exclude(campaign_id='')

    ids = list(
        base.values_list('campaign_id', flat=True).distinct()
    )
    if not ids:
        return []

    nombres = dict(
        AnuncioMetaCache.objects.filter(campaign_id__in=ids)
        .exclude(campaign_name='')
        .values_list('campaign_id', 'campaign_name')
    )

    filas = []
    for campaign_id in ids:
        conversaciones = base.filter(campaign_id=campaign_id)
        filas.append({
            'campaign_id': campaign_id,
            'campaign_name': nombres.get(campaign_id) or f'Campaña {campaign_id}',
            'resumen': _resumen_conversaciones(conversaciones),
            'etiquetas': _desglose_etiquetas(conversaciones, limite=5),
            'pipeline': _desglose_pipeline(conversaciones),
        })
    filas.sort(key=lambda f: f['resumen']['total'], reverse=True)
    return filas


def reporte_leads_context(request, sesiones):
    """Contexto de `whatsapp/campanas/reporte.html`."""
    filas_sistema = reporte_campanas_sistema(sesiones)
    filas_meta = reporte_campanas_meta(sesiones)

    conversaciones_todas = ConversacionWhatsApp.objects.filter(
        status=True, contacto__sesion__in=sesiones,
    )
    return {
        'reporte_sistema': filas_sistema,
        'reporte_meta': filas_meta,
        'reporte_totales': _resumen_conversaciones(conversaciones_todas),
        'reporte_clasificaciones': _desglose_clasificacion(conversaciones_todas),
        'reporte_generado': timezone.now(),
    }


def detalle_leads_campana(request, sesiones):
    """GET `?action=reporte_detalle`: conversaciones de una campaña, para la tabla
    expandible. `origen=sistema&pk=<id>` o `origen=meta&campaign_id=<id>`."""
    origen = request.GET.get('origen') or 'sistema'
    if origen == 'meta':
        campaign_id = (request.GET.get('campaign_id') or '').strip()
        if not campaign_id:
            return JsonResponse({'error': True, 'message': 'Falta la campaña de Meta.'})
        conversaciones = ConversacionWhatsApp.objects.filter(
            status=True, contacto__sesion__in=sesiones, campaign_id=campaign_id,
        )
        titulo = f'Campaña Meta {campaign_id}'
    else:
        campana = Campana.objects.filter(
            pk=request.GET.get('pk'), sesion__in=sesiones, status=True,
        ).first()
        if not campana:
            return JsonResponse({'error': True, 'message': 'Campaña no encontrada.'})
        conversaciones = conversaciones_de_campana(campana)
        titulo = campana.nombre

    conversaciones = conversaciones.select_related(
        'contacto', 'asignado_a', 'primer_agente',
    ).prefetch_related('contacto__etiquetas', 'pipelines__etapa')[:200]

    listado = []
    for conv in conversaciones:
        card = conv.pipelines.filter(status=True).first()
        listado.append({
            'id': conv.id,
            'contacto': conv.contacto.contacto_nombre or conv.contacto.contacto_numero,
            'numero': conv.contacto.contacto_numero,
            'clasificacion': conv.get_clasificacion_display() if hasattr(conv, 'get_clasificacion_display') else '',
            'estado': 'Abierta' if conv.estado_conversacion == 0 else 'Cerrada',
            'asesor': conv.asignado_a.get_full_name() if conv.asignado_a else '',
            'atendida': bool(conv.primer_agente_id),
            'etiquetas': [
                {'nombre': e.nombre, 'color': e.color}
                for e in conv.contacto.etiquetas.all() if e.status
            ],
            'pipeline': card.etapa.pipeline.nombre if card and card.etapa_id else '',
            'etapa': card.etapa.nombre if card and card.etapa_id else '',
            'fecha': conv.fecha_registro.strftime('%d/%m/%Y %H:%M') if conv.fecha_registro else '',
        })
    return JsonResponse({'error': False, 'titulo': titulo, 'listado': listado})


def sincronizar_campanas_meta(request, sesiones):
    """POST `action=sync_campanas_meta`: trae las campañas de la cuenta
    publicitaria de Meta para conocerlas y cachea sus nombres.

    Las campañas viven en la cuenta de anuncios, no en fastchat: se listan por
    la Marketing API y se guardan los nombres en `AnuncioMetaCache` para que el
    reporte deje de mostrar IDs crudos.
    """
    from .services_ads import ads_service_para_sesion

    sesion_pk = request.POST.get('sesion_id') or request.POST.get('pk')
    sesion = None
    if sesion_pk:
        sesion = sesiones.filter(pk=sesion_pk).first()
    if not sesion:
        sesion = sesiones.filter(proveedor='meta').first()
    if not sesion:
        return JsonResponse({'error': True, 'message': 'No hay una sesión de Meta disponible.'})

    servicio = ads_service_para_sesion(sesion)
    if not servicio or not servicio.configurado:
        return JsonResponse({
            'error': True,
            'message': 'La sesión no tiene configurada la cuenta publicitaria (act_XXXX) ni el token de anuncios.',
        })

    respuesta = servicio.listar_campanas()
    if respuesta.get('error'):
        return JsonResponse({'error': True, 'message': respuesta.get('message') or 'Meta rechazó la consulta.'})

    campanas = respuesta.get('rows') or []
    actualizadas = 0
    for fila in campanas:
        campaign_id = (fila.get('id') or '').strip()
        nombre = (fila.get('name') or '').strip()
        if not campaign_id or not nombre:
            continue
        # Los nombres se guardan sobre las filas de anuncios ya conocidas de esa
        # campaña; si todavía no hay ninguna, se deja una fila puente por
        # campaña para que el reporte pueda mostrar el nombre.
        filas_cache = AnuncioMetaCache.objects.filter(campaign_id=campaign_id)
        if filas_cache.exists():
            actualizadas += filas_cache.update(
                campaign_name=nombre[:300],
                effective_status=(fila.get('effective_status') or '')[:40],
                ultima_sync=timezone.now(),
            )
        else:
            AnuncioMetaCache.objects.update_or_create(
                ad_id=f'campaign:{campaign_id}',
                defaults={
                    'campaign_id': campaign_id,
                    'campaign_name': nombre[:300],
                    'effective_status': (fila.get('effective_status') or '')[:40],
                    'ultima_sync': timezone.now(),
                },
            )
            actualizadas += 1

    log(f"Campañas de Meta sincronizadas ({actualizadas} filas)", request, "change")
    return JsonResponse({
        'error': False,
        'message': f'Se trajeron {len(campanas)} campañas de la cuenta publicitaria.',
        'total': len(campanas),
        'campanas': [
            {
                'id': f.get('id'),
                'nombre': f.get('name'),
                'objetivo': f.get('objective'),
                'estado': f.get('effective_status') or f.get('status'),
                'inicio': f.get('start_time'),
                'fin': f.get('stop_time'),
            }
            for f in campanas
        ],
    })
