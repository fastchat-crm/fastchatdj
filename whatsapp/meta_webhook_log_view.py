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

from core.funciones import secure_module, addData

from .models import EventoMetaRecibido, SesionWhatsApp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ── _hoy_local ────────────────────────────────────────────────────────────
# Devuelve la fecha (date) local de hoy según TIME_ZONE.
# Por qué existe: `timezone.localdate()` revienta cuando USE_TZ=False
# (en este proyecto está comentado en settings.py:191), porque
# `timezone.now()` devuelve naive y `localtime()` exige aware. Este
# helper detecta ambos casos y se queda con la fecha correcta sin crashear.
def _hoy_local():
    """Fecha local de hoy. Tolera USE_TZ True/False."""
    ahora = timezone.now()
    if timezone.is_aware(ahora):
        try:
            ahora = timezone.localtime(ahora)
        except Exception:
            pass
    return ahora.date()


# ── _ahora_local_str ──────────────────────────────────────────────────────
# Devuelve la hora actual local como string (default 'HH:MM:SS').
# Lo usa el endpoint poll para mandar al frontend la marca "última
# actualización" del indicador "en vivo" sin tener que formatear en JS.
def _ahora_local_str(fmt='%H:%M:%S'):
    """Hora actual local formateada. Tolera USE_TZ True/False igual que _hoy_local."""
    ahora = timezone.now()
    if timezone.is_aware(ahora):
        try:
            ahora = timezone.localtime(ahora)
        except Exception:
            pass
    return ahora.strftime(fmt)


# ── _fmt_dt ───────────────────────────────────────────────────────────────
# Formatea un datetime (de modelo) a string en hora local.
# Sirve tanto para datetimes aware como naive — en el segundo caso asume
# que el valor YA está en hora local (típico cuando USE_TZ=False y la BD
# tiene TIMESTAMP WITHOUT TIME ZONE). Lo usan _serializar_evento y el
# endpoint detalle para mandar la fecha lista para mostrar en el frontend.
def _fmt_dt(dt, fmt):
    """Formatea un datetime (naive o aware) en hora local sin crashear."""
    if dt is None:
        return ''
    if timezone.is_aware(dt):
        try:
            dt = timezone.localtime(dt)
        except Exception:
            pass
    return dt.strftime(fmt)


# ── _parse_fecha ──────────────────────────────────────────────────────────
# Parsea el query param `?fecha=YYYY-MM-DD`. Si viene vacío o con formato
# inválido cae a hoy — así la página se puede cargar sin filtros y la
# llamada nunca rompe por input mal formado del usuario o un bot.
def _parse_fecha(raw: str | None):
    """Parsea YYYY-MM-DD; cae a hoy si viene vacío o inválido."""
    hoy = _hoy_local()
    if not raw:
        return hoy
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return hoy


# ── _serializar_evento ────────────────────────────────────────────────────
# Convierte un EventoMetaRecibido en el dict ligero que devuelve el poll
# JSON. Deliberadamente NO incluye el payload crudo (puede ser grande):
# se pide on-demand vía /webhook-log/<evento_id>/ al abrir el modal.
# Mantiene un `payload_preview` corto para mostrar en la celda Preview.
def _serializar_evento(ev: EventoMetaRecibido) -> dict:
    """Dict ligero para polling (sin payload crudo)."""
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


# ── _filtrar ──────────────────────────────────────────────────────────────
# Aplica los filtros opcionales del usuario (tipo / firma / procesado)
# sobre cualquier queryset de EventoMetaRecibido. Compartido por la vista
# HTML y el endpoint poll para garantizar que el "live update" respete
# exactamente los mismos criterios que la primera carga.
def _filtrar(qs, request):
    """Aplica filtros tipo/firma/proc sobre el queryset (HTML + poll)."""
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

# ── meta_webhook_log ──────────────────────────────────────────────────────
# Vista HTML principal. Renderiza la página de auditoría con la tabla del
# día seleccionado (default: hoy), las métricas resumen y la lista de
# tipos de evento disponibles para el dropdown de filtros.
# Sólo aplica a sesiones con proveedor='meta' — si el id no existe o es
# Baileys, redirige al listado de sesiones.
# Llama addData(request, contexto) para que base.html tenga sidebar,
# header, nombre de empresa, ruta_val, etc. — sin esto la página
# renderiza con layout roto.
@login_required
@secure_module
def meta_webhook_log(request, sesion_id: int):
    """Render HTML de la página de auditoría (tabla + filtros + polling JS)."""
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
        'titulo':            f'Auditoría webhook · {sesion.nombre or sesion.numero or "sesión"}',
        'descripcion':       'Eventos recibidos desde Meta Cloud API en tiempo real.',
        'ruta':              request.path,
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
    addData(request, contexto)
    return render(request, 'whatsapp/sesiones/webhook_log.html', contexto)


# ---------------------------------------------------------------------------
# Endpoint poll (JSON)
# ---------------------------------------------------------------------------

# ── meta_webhook_log_poll ─────────────────────────────────────────────────
# Endpoint JSON que el frontend dispara cada 10s (visibility-aware).
# Devuelve solo eventos con `id > since_id` para la fecha indicada — así
# las requests son incrementales y baratas, no traen lo que ya está en
# pantalla. Tope de 100 eventos por respuesta: si el cliente estuvo
# desconectado mucho tiempo, hace varios polls hasta ponerse al día.
# También devuelve los totales del día para refrescar las stats arriba
# y la marca "now" para el reloj del indicador "en vivo".
@login_required
@secure_module
def meta_webhook_log_poll(request, sesion_id: int):
    """Eventos con id > since_id + totales + reloj. Para polling incremental."""
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

# ── meta_webhook_log_detalle ──────────────────────────────────────────────
# Endpoint JSON que devuelve el payload crudo de UN evento concreto.
# Se llama on-demand cuando el usuario hace click en una fila de la tabla
# y abre el modal con el JSON formateado. Separado del poll para no
# inflar cada request periódico con payloads que pueden pesar varios KB.
# Valida que el evento pertenezca a la ConfigMeta de la sesión — si no,
# devuelve 404 (defensa contra acceso cruzado entre sesiones).
@login_required
@secure_module
def meta_webhook_log_detalle(request, sesion_id: int, evento_id: int):
    """Payload crudo de un evento (on-demand al abrir el modal)."""
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
