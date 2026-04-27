"""Auditoría en tiempo real de eventos webhook recibidos desde Meta Cloud API.

Por sesión Meta, lista cada `EventoMetaRecibido` con filtros (fecha, tipo,
firma, procesado) y un endpoint JSON de polling para incorporar eventos
nuevos sin recargar la página. Por defecto muestra el día actual.

URLs:
- /whatsapp/sesiones/<sesion_id>/webhook-log/        (HTML)
- /whatsapp/sesiones/<sesion_id>/webhook-log/poll/   (JSON)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.funciones import secure_module

from .models import EventoMetaRecibido, SesionWhatsApp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hoy_local():
    """Fecha local de hoy. Tolera USE_TZ True/False (en este proyecto está
    comentado, default False, así que `timezone.now()` devuelve naive y
    `timezone.localdate()` revienta)."""
    ahora = timezone.now()
    if timezone.is_aware(ahora):
        try:
            ahora = timezone.localtime(ahora)
        except Exception:
            pass
    return ahora.date()


def _ahora_local_str(fmt='%H:%M:%S'):
    ahora = timezone.now()
    if timezone.is_aware(ahora):
        try:
            ahora = timezone.localtime(ahora)
        except Exception:
            pass
    return ahora.strftime(fmt)


def _fmt_dt(dt, fmt):
    """Formatea un datetime (naive o aware) en hora local. Si es aware, lo
    convierte a TIME_ZONE; si es naive, lo asume ya en hora local (caso típico
    cuando USE_TZ=False)."""
    if dt is None:
        return ''
    if timezone.is_aware(dt):
        try:
            dt = timezone.localtime(dt)
        except Exception:
            pass
    return dt.strftime(fmt)


def _parse_fecha(raw: str | None):
    """Parsea YYYY-MM-DD; cae a hoy si viene vacío o inválido."""
    hoy = _hoy_local()
    if not raw:
        return hoy
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return hoy


def _serializar_evento(ev: EventoMetaRecibido) -> dict:
    """Forma JSON ligera para el polling (sin payload crudo, que se pide aparte
    al hacer click en la fila)."""
    return {
        'id':                  ev.id,
        'tipo_evento':         ev.tipo_evento,
        'firma_valida':        ev.firma_valida,
        'procesado':           ev.procesado,
        'error_procesamiento': (ev.error_procesamiento or '')[:200],
        'recibido_en':         _fmt_dt(ev.recibido_en, '%H:%M:%S'),
        'recibido_en_full':    _fmt_dt(ev.recibido_en, '%Y-%m-%d %H:%M:%S'),
        'payload_preview':     json.dumps(ev.payload_json, ensure_ascii=False)[:120],
    }


def _filtrar(qs, request):
    """Aplica filtros opcionales sobre el queryset (compartido entre HTML y poll)."""
    tipo = request.GET.get('tipo') or ''
    firma = request.GET.get('firma') or ''  # '', 'ok', 'mal'
    proc = request.GET.get('proc') or ''    # '', 'si', 'no', 'error'

    if tipo:
        qs = qs.filter(tipo_evento=tipo)
    if firma == 'ok':
        qs = qs.filter(firma_valida=True)
    elif firma == 'mal':
        qs = qs.filter(firma_valida=False)
    if proc == 'si':
        qs = qs.filter(procesado=True)
    elif proc == 'no':
        qs = qs.filter(procesado=False)
    elif proc == 'error':
        qs = qs.exclude(error_procesamiento__isnull=True).exclude(error_procesamiento='')
    return qs


# ---------------------------------------------------------------------------
# Vista principal (HTML)
# ---------------------------------------------------------------------------

@login_required
@secure_module
def meta_webhook_log(request, sesion_id: int):
    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return HttpResponseRedirect('/whatsapp/sesiones/')

    config = getattr(sesion, 'config_meta', None)
    fecha = _parse_fecha(request.GET.get('fecha'))
    hoy = _hoy_local()

    if config:
        qs = EventoMetaRecibido.objects.filter(
            config_meta=config,
            recibido_en__date=fecha,
        )
        qs = _filtrar(qs, request)
        qs = qs.order_by('-recibido_en', '-id')
        eventos = list(qs[:500])

        # Métricas del día (sobre el queryset sin filtros, para barra de resumen)
        qs_dia = EventoMetaRecibido.objects.filter(config_meta=config, recibido_en__date=fecha)
        total_dia        = qs_dia.count()
        total_ok         = qs_dia.filter(firma_valida=True, procesado=True).count()
        total_firma_mal  = qs_dia.filter(firma_valida=False).count()
        total_error      = qs_dia.exclude(error_procesamiento__isnull=True).exclude(error_procesamiento='').count()
        tipos_disponibles = list(
            qs_dia.values_list('tipo_evento', flat=True).distinct().order_by('tipo_evento')
        )
        ultimo_id = eventos[0].id if eventos else 0
    else:
        eventos = []
        total_dia = total_ok = total_firma_mal = total_error = 0
        tipos_disponibles = []
        ultimo_id = 0

    contexto = {
        'sesion':            sesion,
        'config':            config,
        'eventos':           eventos,
        'fecha':             fecha,
        'fecha_str':         fecha.strftime('%Y-%m-%d'),
        'es_hoy':            fecha == hoy,
        'tipos_disponibles': tipos_disponibles,
        'total_dia':         total_dia,
        'total_ok':          total_ok,
        'total_firma_mal':   total_firma_mal,
        'total_error':       total_error,
        'ultimo_id':         ultimo_id,
        'filtro_tipo':       request.GET.get('tipo') or '',
        'filtro_firma':      request.GET.get('firma') or '',
        'filtro_proc':       request.GET.get('proc') or '',
    }
    return render(request, 'whatsapp/sesiones/webhook_log.html', contexto)


# ---------------------------------------------------------------------------
# Endpoint poll (JSON)
# ---------------------------------------------------------------------------

@login_required
@secure_module
def meta_webhook_log_poll(request, sesion_id: int):
    """Devuelve eventos con id > since_id para la fecha indicada (default: hoy).

    Pensado para polling cada 5s desde la página de auditoría. Limita a 100
    eventos por respuesta — si el cliente quedó muy atrás, hace varios polls.
    """
    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'sesion_no_encontrada'}, status=404)

    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'ok': True, 'eventos': [], 'ultimo_id': 0, 'totales': {}})

    fecha = _parse_fecha(request.GET.get('fecha'))
    try:
        since_id = int(request.GET.get('since_id') or 0)
    except (TypeError, ValueError):
        since_id = 0

    qs = EventoMetaRecibido.objects.filter(
        config_meta=config,
        recibido_en__date=fecha,
        id__gt=since_id,
    )
    qs = _filtrar(qs, request).order_by('id')[:100]
    eventos = [_serializar_evento(e) for e in qs]

    qs_dia = EventoMetaRecibido.objects.filter(config_meta=config, recibido_en__date=fecha)
    totales = {
        'total':       qs_dia.count(),
        'ok':          qs_dia.filter(firma_valida=True, procesado=True).count(),
        'firma_mal':   qs_dia.filter(firma_valida=False).count(),
        'con_error':   qs_dia.exclude(error_procesamiento__isnull=True).exclude(error_procesamiento='').count(),
    }

    ultimo_id = eventos[-1]['id'] if eventos else since_id
    return JsonResponse({
        'ok':         True,
        'eventos':    eventos,
        'ultimo_id':  ultimo_id,
        'totales':    totales,
        'now':        _ahora_local_str('%H:%M:%S'),
    })


# ---------------------------------------------------------------------------
# Endpoint detalle payload (JSON)
# ---------------------------------------------------------------------------

@login_required
@secure_module
def meta_webhook_log_detalle(request, sesion_id: int, evento_id: int):
    """Devuelve el payload crudo de un evento — pedido on demand al abrir
    el modal, para no saturar el render inicial ni el polling."""
    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'sesion_no_encontrada'}, status=404)
    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'ok': False, 'error': 'sin_config_meta'}, status=404)

    ev = EventoMetaRecibido.objects.filter(id=evento_id, config_meta=config).first()
    if not ev:
        return JsonResponse({'ok': False, 'error': 'evento_no_encontrado'}, status=404)

    return JsonResponse({
        'ok': True,
        'evento': {
            'id':                  ev.id,
            'tipo_evento':         ev.tipo_evento,
            'firma_valida':        ev.firma_valida,
            'procesado':           ev.procesado,
            'error_procesamiento': ev.error_procesamiento or '',
            'recibido_en':         _fmt_dt(ev.recibido_en, '%Y-%m-%d %H:%M:%S'),
            'payload_json':        ev.payload_json,
        },
    })
