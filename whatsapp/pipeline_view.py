"""Vista Kanban del pipeline de ventas."""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Count
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.funciones import addData, secure_module, log
from .models import (
    PipelineVenta, EtapaPipeline, ConversacionEnPipeline,
    HistorialEtapaPipeline, ConversacionWhatsApp,
)


@login_required
@secure_module
def pipelineView(request):
    data = {
        'titulo': 'Pipeline de Ventas',
        'descripcion': 'Tablero Kanban de oportunidades',
        'ruta': request.path,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add_pipeline':
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'Nombre obligatorio.'})
                    pipe = PipelineVenta.objects.create(
                        nombre=nombre, usuario_creacion=request.user,
                        descripcion=request.POST.get('descripcion', ''),
                    )
                    return JsonResponse({'error': False, 'pipeline_id': pipe.id, 'reload': True})

                if action == 'add_etapa':
                    pipe_id = int(request.POST['pipeline_id'])
                    pipe = PipelineVenta.objects.get(pk=pipe_id)
                    orden_max = pipe.etapas.aggregate(m=Sum('orden')).get('m') or 0
                    et = EtapaPipeline.objects.create(
                        pipeline=pipe,
                        nombre=(request.POST.get('nombre') or 'Nueva etapa').strip(),
                        orden=int(request.POST.get('orden', orden_max + 1)),
                        color=request.POST.get('color', '#6c757d'),
                        probabilidad_cierre=int(request.POST.get('probabilidad_cierre', 0) or 0),
                        es_ganado=request.POST.get('es_ganado') == 'true',
                        es_perdido=request.POST.get('es_perdido') == 'true',
                        usuario_creacion=request.user,
                    )
                    return JsonResponse({'error': False, 'etapa_id': et.id})

                if action == 'mover_card':
                    card_id = int(request.POST['card_id'])
                    nueva_etapa_id = int(request.POST['etapa_id'])
                    card = ConversacionEnPipeline.objects.select_related('etapa').get(pk=card_id)
                    etapa_anterior = card.etapa
                    card.etapa_id = nueva_etapa_id
                    card.fecha_cambio_etapa = timezone.now()
                    card.save(update_fields=['etapa', 'fecha_cambio_etapa'])
                    HistorialEtapaPipeline.objects.create(
                        card=card, etapa_anterior=etapa_anterior,
                        etapa_nueva_id=nueva_etapa_id, usuario=request.user,
                    )
                    nueva = EtapaPipeline.objects.get(pk=nueva_etapa_id)
                    # Si la nueva etapa es de tipo "ganado" → reportar Purchase a CAPI
                    if nueva.es_ganado:
                        try:
                            from .services_capi import reportar_purchase
                            reportar_purchase(
                                card.conversacion,
                                value=float(card.valor_estimado or 0),
                                currency=card.moneda or 'USD',
                            )
                        except Exception:
                            pass
                    return JsonResponse({'error': False})

                if action == 'agregar_card':
                    conv_id = int(request.POST['conversacion_id'])
                    etapa_id = int(request.POST['etapa_id'])
                    conv = ConversacionWhatsApp.objects.get(pk=conv_id)
                    card, _ = ConversacionEnPipeline.objects.get_or_create(
                        conversacion=conv, etapa_id=etapa_id,
                        defaults={
                            'valor_estimado': Decimal(request.POST.get('valor_estimado', '0') or '0'),
                            'moneda': request.POST.get('moneda', 'USD'),
                            'usuario_creacion': request.user,
                        }
                    )
                    return JsonResponse({'error': False, 'card_id': card.id})

                if action == 'editar_card':
                    card_id = int(request.POST['card_id'])
                    card = ConversacionEnPipeline.objects.get(pk=card_id)
                    if 'valor_estimado' in request.POST:
                        card.valor_estimado = Decimal(request.POST['valor_estimado'] or '0')
                    if 'moneda' in request.POST:
                        card.moneda = request.POST['moneda']
                    if 'fecha_cierre_esperado' in request.POST:
                        card.fecha_cierre_esperado = request.POST['fecha_cierre_esperado'] or None
                    if 'nota' in request.POST:
                        card.nota = request.POST['nota']
                    card.save()
                    return JsonResponse({'error': False})

                if action == 'eliminar_card':
                    ConversacionEnPipeline.objects.filter(
                        pk=int(request.POST['card_id'])
                    ).delete()
                    return JsonResponse({'error': False})

        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    pipeline_id = request.GET.get('pipeline')
    pipelines = PipelineVenta.objects.filter(status=True).order_by('-es_default', 'nombre')
    pipeline_actual = None
    if pipeline_id:
        pipeline_actual = pipelines.filter(pk=pipeline_id).first()
    if not pipeline_actual:
        pipeline_actual = pipelines.first()

    data['pipelines'] = pipelines
    data['pipeline_actual'] = pipeline_actual

    if pipeline_actual:
        etapas = list(pipeline_actual.etapas.filter(status=True).order_by('orden'))
        cards_por_etapa = []
        for et in etapas:
            cards = (
                ConversacionEnPipeline.objects
                .filter(etapa=et, status=True)
                .select_related('conversacion__contacto')
                .order_by('orden_en_etapa', '-fecha_cambio_etapa')
            )
            agg = cards.aggregate(total=Sum('valor_estimado'), n=Count('id'))
            cards_por_etapa.append({
                'etapa': et,
                'cards': cards,
                'total_valor': agg.get('total') or 0,
                'n': agg.get('n') or 0,
            })
        data['columnas'] = cards_por_etapa

    return render(request, 'whatsapp/pipeline/listado.html', data)
