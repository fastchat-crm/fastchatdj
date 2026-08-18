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
from .models import (
    ConfigInstagram,
    ConfigMessenger,
    ConfigTikTok,
    EventoMetaRecibido,
)
from .permisos_sesion import sesiones_visibles

BRANDING_MONITOREO = {
    'whatsapp': {
        'titulo': 'Monitoreo webhook WhatsApp',
        'nombre': 'WhatsApp Cloud',
        'icono': 'fab fa-whatsapp',
        'webhook': '/whatsapp/meta_webhook/',
    },
    'instagram': {
        'titulo': 'Monitoreo webhook Instagram',
        'nombre': 'Instagram',
        'icono': 'fab fa-instagram',
        'webhook': '/instagram/webhook/',
    },
    'messenger': {
        'titulo': 'Monitoreo webhook Facebook',
        'nombre': 'Facebook / Messenger',
        'icono': 'fab fa-facebook',
        'webhook': '/facebook/webhook/',
    },
    'tiktok': {
        'titulo': 'Monitoreo webhook TikTok',
        'nombre': 'TikTok',
        'icono': 'fab fa-tiktok',
        'webhook': '/tiktok/webhook/',
    },
}


def _con_error(qs):
    return qs.exclude(error_procesamiento__isnull=True).exclude(error_procesamiento='')


def _ids_visibles(request, canal):
    """Ids destino (page/ig/business) de las sesiones que el usuario puede ver.

    Los eventos sociales se guardan con `config_meta=None`, así que el tenant no
    se puede filtrar por FK: se deriva del id destino del payload. Devuelve el
    conjunto de ids propios del usuario para acotar qué eventos puede ver.
    """
    ses = sesiones_visibles(request.user)
    ids = set()
    if canal == 'instagram':
        for c in ConfigInstagram.objects.filter(sesion__in=ses).values_list('ig_user_id', 'page_id'):
            ids.update(str(v) for v in c if v)
    elif canal == 'messenger':
        for v in ConfigMessenger.objects.filter(sesion__in=ses).values_list('page_id', flat=True):
            if v:
                ids.add(str(v))
    elif canal == 'tiktok':
        for c in ConfigTikTok.objects.filter(sesion__in=ses).values_list('business_id', 'open_id'):
            ids.update(str(v) for v in c if v)
    ids.discard('')
    return ids


def _ids_del_payload(payload, canal):
    ids = set()
    if not isinstance(payload, dict):
        return ids
    if canal in ('instagram', 'messenger'):
        for e in payload.get('entry') or []:
            if isinstance(e, dict) and e.get('id'):
                ids.add(str(e['id']))
    elif canal == 'tiktok':
        for clave in ('business_id', 'to_business_id', 'recipient_id'):
            if payload.get(clave):
                ids.add(str(payload[clave]))
        for e in payload.get('events') or []:
            if not isinstance(e, dict):
                continue
            for clave in ('business_id', 'to_business_id', 'recipient_id'):
                if e.get(clave):
                    ids.add(str(e[clave]))
    return ids


def monitoreo_webhook_canal(request, canal):
    branding = BRANDING_MONITOREO[canal]
    es_super = request.user.is_superuser
    if canal == 'whatsapp':
        qs = EventoMetaRecibido.objects.all()
        for prefijo in ('instagram:', 'messenger:', 'tiktok:'):
            qs = qs.exclude(tipo_evento__startswith=prefijo)
        # Los eventos WhatsApp Cloud sí tienen config_meta → scoping por FK.
        if not es_super:
            qs = qs.filter(config_meta__sesion__in=sesiones_visibles(request.user))
    else:
        qs = EventoMetaRecibido.objects.filter(tipo_evento__startswith=f'{canal}:')

    # Para canales sociales (config_meta=None) el scoping por tenant se hace en
    # Python contra el id destino del payload.
    scoping_social = (canal != 'whatsapp') and not es_super
    ids_ok = _ids_visibles(request, canal) if scoping_social else None

    def _visible(ev):
        if not scoping_social:
            return True
        if not ids_ok:
            return False
        return bool(_ids_del_payload(ev.payload_json, canal) & ids_ok)

    if request.GET.get('action') == 'detalle':
        ev = qs.filter(pk=request.GET.get('id') or 0).first()
        if not ev or not _visible(ev):
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

    if scoping_social:
        eventos_todos = [e for e in qs.order_by('-recibido_en')[:1000] if _visible(e)]
    else:
        eventos_todos = list(qs.order_by('-recibido_en')[:1000])

    filtro = (request.GET.get('estado') or '').strip()
    if filtro == 'error':
        eventos_f = [e for e in eventos_todos if e.error_procesamiento]
    elif filtro == 'firma':
        eventos_f = [e for e in eventos_todos if not e.firma_valida]
    elif filtro == 'pendiente':
        eventos_f = [e for e in eventos_todos if not e.procesado]
    else:
        eventos_f = eventos_todos

    ahora = timezone.now()
    corte_24h = ahora - timedelta(hours=24)
    data = {
        'titulo': branding['titulo'],
        'descripcion': 'Auditoría de cada webhook recibido del canal: firma, procesamiento y errores.',
        'ruta': request.path,
        'canal': canal,
        'branding': branding,
        'eventos': eventos_f[:200],
        'stats': {
            'total': len(eventos_todos),
            'ult_24h': sum(1 for e in eventos_todos if e.recibido_en and e.recibido_en >= corte_24h),
            'firma_invalida': sum(1 for e in eventos_todos if not e.firma_valida),
            'con_error': sum(1 for e in eventos_todos if e.error_procesamiento),
        },
        'filtro_estado': filtro,
    }
    addData(request, data)
    return render(request, 'whatsapp/monitoreo/monitoreo_webhook.html', data)
