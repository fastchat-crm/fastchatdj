"""Vista de debug: lista los últimos N hits HTTP a /whatsapp/meta_webhook/.

Útil para verificar SI Meta está pegando (independiente de si guardó evento).
Captura GET handshakes, POST con JSON inválido, 4xx, etc.

URL: /whatsapp/meta/webhook-hits/
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import secure_module, addData
from .models import MetaWebhookHit


@login_required
@secure_module
def meta_webhook_hits(request):
    qs = MetaWebhookHit.objects.all()

    # Filtros
    metodo = (request.GET.get('metodo') or '').upper()
    if metodo in ('GET', 'POST'):
        qs = qs.filter(method=metodo)
    status = request.GET.get('status') or ''
    if status.isdigit():
        qs = qs.filter(status_code=int(status))
    direccion = (request.GET.get('direccion') or '').lower()
    if direccion in ('in', 'out'):
        qs = qs.filter(direccion=direccion)

    hits = list(qs[:200])

    # Stats
    total = MetaWebhookHit.objects.count()
    from django.utils import timezone
    from datetime import timedelta
    ahora = timezone.now()
    ult_24h = MetaWebhookHit.objects.filter(fecha__gte=ahora - timedelta(hours=24)).count()
    inbound = MetaWebhookHit.objects.filter(direccion='in').count()
    outbound = MetaWebhookHit.objects.filter(direccion='out').count()
    errores = MetaWebhookHit.objects.filter(status_code__gte=400).count()

    contexto = {
        'titulo': 'Hits HTTP Meta (in + out)',
        'descripcion': 'Auditoría raw de cada request relacionado con Meta — entrante (webhook) y saliente (envíos).',
        'ruta': request.path,
        'hits': hits,
        'stats': {
            'total': total,
            'ult_24h': ult_24h,
            'inbound': inbound,
            'outbound': outbound,
            'errores': errores,
        },
        'filtro_metodo': metodo,
        'filtro_status': status,
        'filtro_direccion': direccion,
    }
    addData(request, contexto)
    return render(request, 'whatsapp/sesiones/webhook_hits.html', contexto)


@login_required
def meta_webhook_hits_poll(request):
    """JSON de polling — devuelve hits con id > since_id."""
    since_id = int(request.GET.get('since_id') or 0)
    qs = MetaWebhookHit.objects.filter(id__gt=since_id).order_by('-id')[:50]
    data = [{
        'id': h.id,
        'fecha': h.fecha.strftime('%H:%M:%S'),
        'direccion': h.direccion,
        'method': h.method,
        'url': h.url,
        'status_code': h.status_code,
        'ip': h.ip,
        'user_agent': (h.user_agent or '')[:80],
        'signature_presente': h.signature_presente,
        'body_length': h.body_length,
        'latencia_ms': h.latencia_ms,
        'nota': h.nota,
    } for h in qs]
    max_id = MetaWebhookHit.objects.order_by('-id').values_list('id', flat=True).first() or 0
    return JsonResponse({
        'ok': True,
        'data': data,
        'max_id': max_id,
    })


@login_required
@secure_module
def meta_webhook_hit_detalle(request, hit_id: int):
    """Detalle JSON de un hit (body_preview completo)."""
    h = MetaWebhookHit.objects.filter(id=hit_id).first()
    if not h:
        return JsonResponse({'ok': False, 'error': 'No existe'})
    return JsonResponse({
        'ok': True,
        'id': h.id,
        'fecha': h.fecha.isoformat(),
        'direccion': h.direccion,
        'direccion_display': h.get_direccion_display(),
        'method': h.method,
        'url': h.url,
        'status_code': h.status_code,
        'ip': h.ip,
        'user_agent': h.user_agent,
        'query_string': h.query_string,
        'signature_presente': h.signature_presente,
        'body_length': h.body_length,
        'body_preview': h.body_preview,
        'response_preview': h.response_preview,
        'latencia_ms': h.latencia_ms,
        'nota': h.nota,
    })
