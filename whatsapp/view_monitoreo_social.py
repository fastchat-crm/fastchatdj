"""Monitoreo de webhooks por canal social (Instagram/Messenger/TikTok).

Equivalente por app del monitor Meta de WhatsApp (`meta_webhook_hits_view.py` /
webhook-log por sesión): lista `EventoMetaRecibido` filtrado por el prefijo de
canal en `tipo_evento` (`instagram:`, `messenger:`, `tiktok:`) con stats,
filtros por estado y detalle de payload. Los wrappers viven en
`instagram/view_monitoreo.py`, `facebook/view_monitoreo.py` y
`tiktok/view_monitoreo.py`.
"""
from datetime import timedelta

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.funciones import addData
from .models import EventoMetaRecibido

BRANDING_MONITOREO = {
    'instagram': {
        'titulo': 'Monitoreo webhook Instagram',
        'nombre': 'Instagram',
        'icono': 'fab fa-instagram',
        'webhook': '/whatsapp/instagram_webhook/',
    },
    'messenger': {
        'titulo': 'Monitoreo webhook Facebook',
        'nombre': 'Facebook / Messenger',
        'icono': 'fab fa-facebook',
        'webhook': '/whatsapp/messenger_webhook/',
    },
    'tiktok': {
        'titulo': 'Monitoreo webhook TikTok',
        'nombre': 'TikTok',
        'icono': 'fab fa-tiktok',
        'webhook': '/whatsapp/tiktok_webhook/',
    },
}


def _con_error(qs):
    return qs.exclude(error_procesamiento__isnull=True).exclude(error_procesamiento='')


def monitoreo_webhook_canal(request, canal):
    branding = BRANDING_MONITOREO[canal]
    qs = EventoMetaRecibido.objects.filter(tipo_evento__startswith=f'{canal}:')

    if request.GET.get('action') == 'detalle':
        ev = qs.filter(pk=request.GET.get('id') or 0).first()
        if not ev:
            return JsonResponse({'ok': False, 'message': 'Evento no encontrado.'})
        return JsonResponse({
            'ok': True,
            'id': ev.id,
            'tipo_evento': ev.tipo_evento,
            'recibido_en': ev.recibido_en.strftime('%d/%m/%Y %H:%M:%S'),
            'firma_valida': ev.firma_valida,
            'procesado': ev.procesado,
            'error': ev.error_procesamiento or '',
            'payload': ev.payload_json,
        })

    filtro = (request.GET.get('estado') or '').strip()
    if filtro == 'error':
        qs_lista = _con_error(qs)
    elif filtro == 'firma':
        qs_lista = qs.filter(firma_valida=False)
    elif filtro == 'pendiente':
        qs_lista = qs.filter(procesado=False)
    else:
        qs_lista = qs

    ahora = timezone.now()
    data = {
        'titulo': branding['titulo'],
        'descripcion': 'Auditoría de cada webhook recibido del canal: firma, procesamiento y errores.',
        'ruta': request.path,
        'canal': canal,
        'branding': branding,
        'eventos': list(qs_lista[:200]),
        'stats': {
            'total': qs.count(),
            'ult_24h': qs.filter(recibido_en__gte=ahora - timedelta(hours=24)).count(),
            'firma_invalida': qs.filter(firma_valida=False).count(),
            'con_error': _con_error(qs).count(),
        },
        'filtro_estado': filtro,
    }
    addData(request, data)
    return render(request, 'whatsapp/monitoreo/monitoreo_webhook.html', data)
