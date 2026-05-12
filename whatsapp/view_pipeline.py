"""Vista Kanban del pipeline de ventas."""
import json
import logging
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

logger = logging.getLogger(__name__)


def _generar_pipeline_con_ia(request):
    """Wrapper HTTP: la logica IA vive en `agents_ai/ai_actions/pipeline_wa.py`."""
    from agents_ai.ai_actions import IAActionError
    from agents_ai.ai_actions import pipeline_wa
    from crm.models import ApiKeyIA, PerfilNegocioIA

    perfil = PerfilNegocioIA.objects.filter(usuario=request.user).first()
    if not perfil:
        return JsonResponse({'error': True, 'message': 'No tenes perfil de negocio. Configuralo primero en CRM.'})

    qs = ApiKeyIA.objects.filter(perfil=perfil, estado=True, status=True).order_by('-id')
    apikey_id = (request.POST.get('apikey_id') or '').strip()
    if apikey_id:
        apikey_obj = qs.filter(pk=apikey_id).first()
    else:
        apikey_obj = qs.first()
    if not apikey_obj or not (apikey_obj.descripcion or '').strip():
        return JsonResponse({'error': True, 'message': 'No tenes API Key activa con clave del proveedor LLM. Configura una en CRM → Entrenamiento.'})

    contexto_key = f'[ApiKey #{apikey_obj.id} "{apikey_obj.alias or "sin alias"}" · {apikey_obj.get_proveedor_display()} · modelo={apikey_obj.modelo or "(default)"}]'
    try:
        resultado = pipeline_wa.generar(
            descripcion=request.POST.get('descripcion'),
            n_etapas=request.POST.get('n_etapas') or 5,
            apikey_obj=apikey_obj,
            request=request,
        )
    except IAActionError as ex:
        return JsonResponse({'error': True, 'message': f'{ex} — {contexto_key}'})
    except Exception as ex:
        return JsonResponse({'error': True, 'message': f'El LLM fallo: {str(ex)[:400]} — {contexto_key}'})

    log(
        f"Pipeline '{resultado['nombre']}' generado por IA con {resultado['etapas_creadas']} etapas (api_key={apikey_obj.id})",
        request, "add", obj=resultado['pipeline_id'],
    )
    return JsonResponse({
        'error': False,
        'pipeline_id': resultado['pipeline_id'],
        'message': resultado['message'],
        'etapas_creadas': resultado['etapas_creadas'],
    })


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
                    nota = (request.POST.get('nota') or '').strip()[:1000]
                    conv = ConversacionWhatsApp.objects.get(pk=conv_id)
                    card, creado = ConversacionEnPipeline.objects.get_or_create(
                        conversacion=conv, etapa_id=etapa_id,
                        defaults={
                            'valor_estimado': Decimal(request.POST.get('valor_estimado', '0') or '0'),
                            'moneda': request.POST.get('moneda', 'USD'),
                            'nota': nota,
                            'usuario_creacion': request.user,
                        }
                    )
                    if not creado and nota:
                        card.nota = nota
                        card.save(update_fields=['nota'])
                    return JsonResponse({'error': False, 'card_id': card.id, 'nuevo': creado})

                if action == 'ver_card':
                    card_id = int(request.POST.get('card_id') or 0)
                    card = (
                        ConversacionEnPipeline.objects
                        .select_related('conversacion__contacto', 'conversacion__sesion', 'etapa', 'usuario_creacion')
                        .filter(pk=card_id).first()
                    )
                    if not card:
                        return JsonResponse({'error': True, 'message': 'Card no encontrada.'})
                    conv = card.conversacion
                    contacto = conv.contacto
                    mensajes_qs = (
                        conv.mensajes.filter(status=True)
                        .order_by('-fecha')[:50]
                    )
                    mensajes = []
                    contacto_numero = contacto.contacto_numero
                    for m in reversed(list(mensajes_qs)):
                        es_entrante = (m.remitente == contacto_numero)
                        tipo_msg = 'in' if es_entrante else ('ia' if m.ia_generado else 'out')
                        contenido = m.mensaje or ''
                        if m.tipo and m.tipo != 'texto':
                            contenido = f'[{m.tipo}] {contenido}' if contenido else f'[{m.tipo}]'
                        mensajes.append({
                            'tipo': tipo_msg,
                            'contenido': contenido[:500],
                            'fecha': m.fecha.strftime('%d/%m/%Y %H:%M') if m.fecha else '',
                        })
                    finalizada = bool(conv.conversacion_finalizada)
                    if finalizada:
                        url_ir = f'/whatsapp/conversaciones-finalizadas/?conv={conv.id}'
                    else:
                        url_ir = f'/whatsapp/conversaciones/?conv={conv.id}'
                    return JsonResponse({
                        'error': False,
                        'card': {
                            'id': card.id,
                            'nota': card.nota or '',
                            'valor_estimado': str(card.valor_estimado),
                            'moneda': card.moneda,
                            'fecha_creacion': card.fecha_creacion.strftime('%d/%m/%Y %H:%M') if card.fecha_creacion else '',
                            'fecha_cambio_etapa': card.fecha_cambio_etapa.strftime('%d/%m/%Y %H:%M') if card.fecha_cambio_etapa else '',
                            'etapa': card.etapa.nombre,
                            'etapa_color': card.etapa.color,
                            'usuario': (card.usuario_creacion.get_full_name() if card.usuario_creacion else '—') or (card.usuario_creacion.username if card.usuario_creacion else '—'),
                        },
                        'conversacion': {
                            'id': conv.id,
                            'nombre': contacto.contacto_nombre or contacto_numero,
                            'numero': contacto_numero,
                            'estado': 'Finalizada' if finalizada else 'Activa',
                            'finalizada': finalizada,
                            'url_ir': url_ir,
                            'resumen': conv.resumen_conversacion or '',
                            'fecha_inicio': conv.fecha_creacion.strftime('%d/%m/%Y %H:%M') if conv.fecha_creacion else '',
                            'fecha_fin': conv.fecha_fin_conversacion.strftime('%d/%m/%Y %H:%M') if conv.fecha_fin_conversacion else '',
                            'sesion': conv.sesion.nombre if conv.sesion_id else '',
                        },
                        'mensajes': mensajes,
                    })

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

                if action == 'generar_pipeline_ia':
                    return _generar_pipeline_con_ia(request)

                if action == 'delete_pipeline':
                    # Compat con eliminarajax global: usa `id` en vez de `pipeline_id`
                    pid = int(request.POST.get('id') or request.POST.get('pipeline_id') or 0)
                    pipe = PipelineVenta.objects.filter(pk=pid).first()
                    if not pipe:
                        return JsonResponse({'error': True, 'message': 'Pipeline no encontrado.'})
                    n_cards = ConversacionEnPipeline.objects.filter(etapa__pipeline=pipe, status=True).count()
                    pipe.status = False
                    pipe.save(update_fields=['status'])
                    log(f"Pipeline '{pipe.nombre}' (id={pid}) eliminado (soft). Cards activas: {n_cards}",
                        request, "del", obj=pid)
                    return JsonResponse({
                        'error': False,
                        'message': f'Pipeline "{pipe.nombre}" eliminado.' + (f' Tenia {n_cards} tarjeta(s) activa(s).' if n_cards else ''),
                        'reload': True,
                    })

                if action == 'editar_pipeline':
                    pid = int(request.POST['pipeline_id'])
                    pipe = PipelineVenta.objects.filter(pk=pid).first()
                    if not pipe:
                        return JsonResponse({'error': True, 'message': 'Pipeline no encontrado.'})
                    nombre = (request.POST.get('nombre') or '').strip()
                    descripcion = (request.POST.get('descripcion') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'El nombre es obligatorio.'})
                    pipe.nombre = nombre[:100]
                    pipe.descripcion = descripcion[:500]
                    pipe.save(update_fields=['nombre', 'descripcion'])
                    log(f"Pipeline {pid} renombrado a '{nombre}'", request, "change", obj=pid)
                    return JsonResponse({'error': False, 'message': 'Pipeline actualizado.', 'nombre': pipe.nombre})

                if action == 'editar_etapa':
                    eid = int(request.POST['etapa_id'])
                    et = EtapaPipeline.objects.filter(pk=eid).first()
                    if not et:
                        return JsonResponse({'error': True, 'message': 'Etapa no encontrada.'})
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'Nombre obligatorio.'})
                    et.nombre = nombre[:80]
                    et.color = (request.POST.get('color') or et.color or '#6c757d')[:7]
                    try:
                        et.probabilidad_cierre = max(0, min(int(request.POST.get('probabilidad_cierre') or 0), 100))
                    except (TypeError, ValueError):
                        pass
                    et.es_ganado = request.POST.get('es_ganado') == 'true'
                    et.es_perdido = request.POST.get('es_perdido') == 'true'
                    if 'orden' in request.POST:
                        try:
                            et.orden = int(request.POST['orden'])
                        except (TypeError, ValueError):
                            pass
                    et.save()
                    log(f"Etapa {eid} ({nombre}) actualizada", request, "change", obj=eid)
                    return JsonResponse({'error': False, 'message': 'Etapa actualizada.'})

                if action == 'delete_etapa':
                    eid = int(request.POST.get('id') or request.POST.get('etapa_id') or 0)
                    et = EtapaPipeline.objects.filter(pk=eid).first()
                    if not et:
                        return JsonResponse({'error': True, 'message': 'Etapa no encontrada.'})
                    n_cards = ConversacionEnPipeline.objects.filter(etapa=et, status=True).count()
                    if n_cards > 0:
                        return JsonResponse({
                            'error': True,
                            'message': f'No se puede eliminar: la etapa tiene {n_cards} tarjeta(s) activa(s). Movelas a otra etapa primero.',
                        })
                    et.status = False
                    et.save(update_fields=['status'])
                    log(f"Etapa '{et.nombre}' (id={eid}) eliminada", request, "del", obj=eid)
                    return JsonResponse({'error': False, 'message': 'Etapa eliminada.', 'reload': True})

        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    pipeline_id = request.GET.get('pipeline')
    pipelines = PipelineVenta.objects.filter(status=True).order_by('-es_default', 'nombre')
    pipeline_actual = None
    if pipeline_id:
        pipeline_actual = pipelines.filter(pk=pipeline_id).first()
    if not pipeline_actual:
        pipeline_actual = pipelines.first()

    from crm.models import ApiKeyIA, PerfilNegocioIA
    perfil_ia = PerfilNegocioIA.objects.filter(usuario=request.user).first()
    if perfil_ia:
        data['apikeys_ia'] = ApiKeyIA.objects.filter(
            perfil=perfil_ia, estado=True, status=True,
        ).exclude(descripcion='').order_by('-id')
    else:
        data['apikeys_ia'] = ApiKeyIA.objects.none()

    data['pipelines'] = pipelines
    data['pipeline_actual'] = pipeline_actual

    if pipeline_actual:
        etapas = list(pipeline_actual.etapas.filter(status=True).order_by('orden'))
        cards_por_etapa = []
        for et in etapas:
            cards = (
                ConversacionEnPipeline.objects
                .filter(etapa=et, status=True)
                .select_related('conversacion__contacto', 'usuario_creacion')
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
