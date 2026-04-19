"""API REST para integraciones externas.

Todos los endpoints esperan header `X-API-Key: <NODE_SECRET_KEY>` (reusamos la
misma llave que usa Node para hablar con Django — si un cliente la tiene, es
de confianza). Rate-limited básico por cache.

Endpoints:
    GET  /api/v1/contactos/                    → lista paginada + filtros
    GET  /api/v1/contactos/<id>/               → detalle
    POST /api/v1/contactos/                    → crear
    GET  /api/v1/conversaciones/               → lista paginada + filtros
    GET  /api/v1/conversaciones/<id>/mensajes/ → historial
    POST /api/v1/conversaciones/<id>/asignar/  → asignar agente
    POST /api/v1/conversaciones/<id>/etapa/    → mover en pipeline
    POST /api/v1/mensajes/enviar/              → enviar mensaje texto/media
    POST /api/v1/etiquetas/aplicar/            → bulk tag a contactos
    POST /api/v1/capi/evento/                  → disparar evento CAPI manual
    GET  /api/v1/campanas/<id>/stats/          → estadísticas campaña
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import (
    Campana,
    Contacto,
    ConversacionEnPipeline,
    ConversacionWhatsApp,
    EnvioCampana,
    EtiquetaContacto,
    MensajeWhatsApp,
    SesionWhatsApp,
)
from .services import get_whatsapp_service


# ---------------------------------------------------------------------------
# Auth + rate limiting
# ---------------------------------------------------------------------------

def _autorizar(request):
    key = request.headers.get('X-API-Key') or request.META.get('HTTP_X_API_KEY')
    if not key or key != getattr(settings, 'NODE_SECRET_KEY', None):
        return JsonResponse({'error': 'unauthorized'}, status=401)
    # Rate limit simple: 120 req/min por key
    bucket = f'api_rl_{key[:16]}_{int(time.time() // 60)}'
    count = cache.get(bucket) or 0
    if count >= 120:
        return JsonResponse({'error': 'rate_limited'}, status=429)
    cache.set(bucket, count + 1, timeout=65)
    return None


def api_endpoint(func):
    """Decorator que aplica auth + captura excepciones."""
    def wrapper(request, *args, **kwargs):
        err = _autorizar(request)
        if err:
            return err
        try:
            return func(request, *args, **kwargs)
        except (Contacto.DoesNotExist, ConversacionWhatsApp.DoesNotExist,
                EtiquetaContacto.DoesNotExist, Campana.DoesNotExist,
                SesionWhatsApp.DoesNotExist):
            return JsonResponse({'error': 'not_found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    wrapper.__name__ = func.__name__
    return csrf_exempt(wrapper)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _ser_contacto(c: Contacto) -> dict:
    return {
        'id':               c.id,
        'nombre':           c.contacto_nombre,
        'numero':           c.numero_telefono or c.contacto_numero,
        'canal':            c.canal,
        'external_id':      c.external_id,
        'sesion_id':        c.sesion_id,
        'estado':           c.estado,
        'ultimo_mensaje':   c.ultimo_mensaje,
        'fecha_ultimo':     c.fecha_ultimo_mensaje.isoformat() if c.fecha_ultimo_mensaje else None,
        'etiquetas':        list(c.etiquetas.values('id', 'nombre', 'color')),
    }


def _ser_conversacion(conv: ConversacionWhatsApp) -> dict:
    return {
        'id':                conv.id,
        'contacto_id':       conv.contacto_id,
        'contacto_nombre':   conv.contacto_nombre,
        'clasificacion':     conv.clasificacion,
        'clasificacion_display': conv.get_clasificacion_display(),
        'finalizada':        conv.conversacion_finalizada,
        'asignado_a':        conv.asignado_a_id,
        'sentimiento':       conv.sentimiento,
        'origen_canal':      conv.origen_canal,
        'ctwa_clid':         conv.ctwa_clid,
        'ad_id':             conv.ad_id,
        'campaign_id':       conv.campaign_id,
        'fecha_registro':    conv.fecha_registro.isoformat() if conv.fecha_registro else None,
    }


def _ser_mensaje(m: MensajeWhatsApp) -> dict:
    return {
        'id':        m.id,
        'remitente': m.remitente,
        'mensaje':   m.mensaje,
        'tipo':      m.tipo,
        'archivo':   m.archivo.url if m.archivo else m.archivo_url,
        'fecha':     m.fecha.isoformat() if m.fecha else None,
        'ia_generado': m.ia_generado,
        'es_automatico': m.es_automatico,
        'agente_id': m.agente_id,
    }


# ---------------------------------------------------------------------------
# Contactos
# ---------------------------------------------------------------------------

@api_endpoint
@require_http_methods(['GET', 'POST'])
def contactos(request):
    if request.method == 'GET':
        qs = Contacto.objects.filter(status=True)
        if request.GET.get('sesion'):
            qs = qs.filter(sesion_id=request.GET['sesion'])
        if request.GET.get('canal'):
            qs = qs.filter(canal=request.GET['canal'])
        if request.GET.get('q'):
            qs = qs.filter(contacto_nombre__icontains=request.GET['q'])
        if request.GET.get('etiqueta'):
            qs = qs.filter(etiquetas__id=request.GET['etiqueta'])
        page = int(request.GET.get('page', 1))
        size = min(int(request.GET.get('size', 50)), 200)
        total = qs.count()
        qs = qs.order_by('-fecha_ultimo_mensaje', '-id')[(page - 1) * size:page * size]
        return JsonResponse({
            'total': total, 'page': page, 'size': size,
            'items': [_ser_contacto(c) for c in qs],
        })

    body = json.loads(request.body or '{}')
    sesion = SesionWhatsApp.objects.get(pk=int(body['sesion_id']))
    numero = ''.join(c for c in body['numero'] if c.isdigit())
    c, created = Contacto.objects.get_or_create(
        sesion=sesion, contacto_numero=numero,
        defaults={
            'contacto_nombre': body.get('nombre', ''),
            'from_number': f'{numero}@s.whatsapp.net',
            'numero_telefono': numero,
            'canal': body.get('canal', 'whatsapp'),
        }
    )
    if not created and body.get('nombre'):
        c.contacto_nombre = body['nombre']
        c.save(update_fields=['contacto_nombre'])
    return JsonResponse({'created': created, 'contacto': _ser_contacto(c)})


@api_endpoint
@require_GET
def contacto_detalle(request, pk):
    c = Contacto.objects.get(pk=pk, status=True)
    return JsonResponse({'contacto': _ser_contacto(c)})


# ---------------------------------------------------------------------------
# Conversaciones
# ---------------------------------------------------------------------------

@api_endpoint
@require_GET
def conversaciones(request):
    qs = ConversacionWhatsApp.objects.filter(status=True).select_related('contacto')
    if request.GET.get('sesion'):
        qs = qs.filter(contacto__sesion_id=request.GET['sesion'])
    if request.GET.get('estado') == 'abierta':
        qs = qs.filter(conversacion_finalizada=False)
    elif request.GET.get('estado') == 'cerrada':
        qs = qs.filter(conversacion_finalizada=True)
    if request.GET.get('clasificacion') is not None:
        qs = qs.filter(clasificacion=int(request.GET['clasificacion']))
    if request.GET.get('canal'):
        qs = qs.filter(origen_canal=request.GET['canal'])
    if request.GET.get('ctwa'):
        qs = qs.exclude(ctwa_clid__isnull=True).exclude(ctwa_clid='')
    page = int(request.GET.get('page', 1))
    size = min(int(request.GET.get('size', 50)), 200)
    total = qs.count()
    qs = qs.order_by('-order')[(page - 1) * size:page * size]
    return JsonResponse({
        'total': total, 'page': page, 'size': size,
        'items': [_ser_conversacion(x) for x in qs],
    })


@api_endpoint
@require_GET
def conversacion_mensajes(request, pk):
    conv = ConversacionWhatsApp.objects.get(pk=pk, status=True)
    limit = min(int(request.GET.get('limit', 50)), 200)
    msgs = conv.mensajes.order_by('-fecha')[:limit]
    return JsonResponse({
        'conversacion': _ser_conversacion(conv),
        'mensajes': [_ser_mensaje(m) for m in reversed(list(msgs))],
    })


@api_endpoint
@require_POST
def conversacion_asignar(request, pk):
    body = json.loads(request.body or '{}')
    conv = ConversacionWhatsApp.objects.get(pk=pk)
    if body.get('auto'):
        from .services_round_robin import asignar_automaticamente
        agente = asignar_automaticamente(conv)
        return JsonResponse({'asignado_a': agente})
    agente_id = int(body['usuario_id'])
    conv.asignado_a_id = agente_id
    from django.utils import timezone
    conv.fecha_asignacion = timezone.now()
    conv.save(update_fields=['asignado_a', 'fecha_asignacion'])
    return JsonResponse({'asignado_a': agente_id})


@api_endpoint
@require_POST
def conversacion_etapa(request, pk):
    body = json.loads(request.body or '{}')
    etapa_id = int(body['etapa_id'])
    conv = ConversacionWhatsApp.objects.get(pk=pk)
    card, _ = ConversacionEnPipeline.objects.get_or_create(
        conversacion=conv, etapa_id=etapa_id,
        defaults={
            'valor_estimado': body.get('valor_estimado', 0),
            'moneda': body.get('moneda', 'USD'),
        }
    )
    return JsonResponse({'card_id': card.id, 'etapa_id': etapa_id})


# ---------------------------------------------------------------------------
# Envío de mensajes
# ---------------------------------------------------------------------------

@api_endpoint
@require_POST
def enviar_mensaje(request):
    body = json.loads(request.body or '{}')
    sesion = SesionWhatsApp.objects.get(pk=int(body['sesion_id']))
    destino = body['destino']
    texto = body.get('texto', '')
    service = get_whatsapp_service(sesion)
    if sesion.es_baileys and '@' not in destino:
        destino = service.format_phone_number(destino)
    res = service.send_text_message(
        sesion.session_id, destino, texto, simularEscritura=False,
    )
    return JsonResponse(res)


# ---------------------------------------------------------------------------
# Etiquetas: aplicar bulk
# ---------------------------------------------------------------------------

@api_endpoint
@require_POST
def etiquetas_aplicar(request):
    body = json.loads(request.body or '{}')
    contacto_ids = body.get('contacto_ids') or []
    etiqueta_ids = body.get('etiqueta_ids') or []
    remover = body.get('remover', False)
    afectados = 0
    for cid in contacto_ids:
        try:
            c = Contacto.objects.get(pk=cid)
            if remover:
                c.etiquetas.remove(*etiqueta_ids)
            else:
                c.etiquetas.add(*etiqueta_ids)
            afectados += 1
        except Contacto.DoesNotExist:
            pass
    return JsonResponse({'afectados': afectados})


# ---------------------------------------------------------------------------
# CAPI manual
# ---------------------------------------------------------------------------

@api_endpoint
@require_POST
def capi_evento(request):
    body = json.loads(request.body or '{}')
    conv = ConversacionWhatsApp.objects.get(pk=int(body['conversacion_id']))
    from .services_capi import enviar_evento
    res = enviar_evento(
        conv,
        event_name=body.get('event_name', 'Lead'),
        value=float(body.get('value', 0) or 0),
        currency=body.get('currency', 'USD'),
        custom_data_extra=body.get('custom_data_extra'),
    )
    return JsonResponse(res)


# ---------------------------------------------------------------------------
# Stats campaña
# ---------------------------------------------------------------------------

@api_endpoint
@require_GET
def campana_stats(request, pk):
    camp = Campana.objects.get(pk=pk)
    from django.db.models import Count
    por_estado = dict(
        EnvioCampana.objects.filter(campana=camp)
            .values_list('estado')
            .annotate(n=Count('id'))
    )
    return JsonResponse({
        'id': camp.id,
        'nombre': camp.nombre,
        'estado': camp.estado,
        'total_objetivo': camp.total_objetivo,
        'total_enviados': camp.total_enviados,
        'total_fallidos': camp.total_fallidos,
        'total_respondidos': camp.total_respondidos,
        'progreso_pct': camp.progreso_pct,
        'tasa_respuesta_pct': camp.tasa_respuesta_pct,
        'por_estado': por_estado,
    })
