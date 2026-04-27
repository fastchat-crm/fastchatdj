"""Página de diagnóstico de una sesión Meta Cloud API.

Muestra todo lo necesario para que un operador entienda el estado real de
una conexión sin abrir Meta Business: webhook configurado, suscripción WABA,
salud del número en Meta, últimos eventos recibidos, últimas trazas, conteos
de mensajes y conversaciones activas.

URL: /whatsapp/sesiones/<sesion_id>/diagnostico/
"""
from __future__ import annotations

import logging
from datetime import timedelta

import requests
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.utils import timezone

from core.funciones import secure_module, addData
from meta.urls import build_graph_url

from .models import (
    SesionWhatsApp,
    ConfigMeta,
    MensajeWhatsApp,
    ConversacionWhatsApp,
    EventoMetaRecibido,
    TrazaMensajeIA,
)

logger = logging.getLogger(__name__)


def _consultar_phone_number(config: ConfigMeta, timeout: int = 10) -> dict:
    """GET /{phone_number_id} → estado actual del número en Meta."""
    if not (config.access_token and config.phone_number_id):
        return {'ok': False, 'error': 'Falta access_token o phone_number_id.'}
    try:
        r = requests.get(
            build_graph_url(f'/{config.phone_number_id}'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            params={'fields': 'display_phone_number,verified_name,quality_rating,'
                              'messaging_limit_tier,status,name_status,throughput'},
            timeout=timeout,
        )
    except Exception as ex:
        return {'ok': False, 'error': f'Error de red: {ex}'}
    if r.status_code != 200:
        try:
            err = r.json().get('error', {}).get('message', r.text[:200])
        except Exception:
            err = r.text[:200]
        return {'ok': False, 'error': err}
    return {'ok': True, 'data': r.json() or {}}


def _consultar_subscribed_apps(config: ConfigMeta, timeout: int = 10) -> dict:
    """GET /{waba_id}/subscribed_apps → lista de apps suscritas a la WABA."""
    if not (config.access_token and config.waba_id):
        return {'ok': False, 'error': 'Falta access_token o waba_id.'}
    try:
        r = requests.get(
            build_graph_url(f'/{config.waba_id}/subscribed_apps'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            timeout=timeout,
        )
    except Exception as ex:
        return {'ok': False, 'error': f'Error de red: {ex}'}
    if r.status_code != 200:
        try:
            err = r.json().get('error', {}).get('message', r.text[:200])
        except Exception:
            err = r.text[:200]
        return {'ok': False, 'error': err}
    payload = r.json() or {}
    apps = payload.get('data') or []
    return {'ok': True, 'apps': apps, 'count': len(apps)}


@login_required
@secure_module
def meta_diagnostico(request, sesion_id: int):
    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return HttpResponseRedirect('/whatsapp/sesiones/')

    config = getattr(sesion, 'config_meta', None)

    ahora = timezone.now()
    hace_24h = ahora - timedelta(hours=24)
    hace_7d = ahora - timedelta(days=7)

    # ── Eventos Meta recibidos (últimos 20) ──
    eventos_recientes = []
    eventos_24h = 0
    eventos_firma_invalida = 0
    if config:
        eventos_qs = EventoMetaRecibido.objects.filter(config_meta=config)
        eventos_recientes = list(eventos_qs.order_by('-recibido_en')[:20])
        eventos_24h = eventos_qs.filter(recibido_en__gte=hace_24h).count()
        eventos_firma_invalida = eventos_qs.filter(
            recibido_en__gte=hace_7d, firma_valida=False,
        ).count()

    # ── Trazas IA (últimas 30) ──
    trazas_recientes = list(
        TrazaMensajeIA.objects.filter(sesion=sesion).order_by('-fecha')[:30]
    )
    trazas_error_24h = TrazaMensajeIA.objects.filter(
        sesion=sesion, nivel='error', fecha__gte=hace_24h,
    ).count()

    # ── Conteos de mensajes ──
    # ConversacionWhatsApp → Contacto → SesionWhatsApp (no FK directo).
    # Entrantes: sin agente humano y no IA y no automático → escribió el cliente.
    # Salientes: cualquier mensaje con agente, IA o sistema.
    from django.db.models import Q
    conv_qs = ConversacionWhatsApp.objects.filter(contacto__sesion=sesion)
    msj_qs = MensajeWhatsApp.objects.filter(conversacion__contacto__sesion=sesion)
    es_saliente = Q(ia_generado=True) | Q(es_automatico=True) | Q(agente__isnull=False)
    counts = {
        'conversaciones_total':       conv_qs.count(),
        'conversaciones_24h':         conv_qs.filter(fecha_registro__gte=hace_24h).count(),
        'mensajes_total':             msj_qs.count(),
        'mensajes_24h':               msj_qs.filter(fecha__gte=hace_24h).count(),
        'mensajes_entrantes_24h':     msj_qs.filter(fecha__gte=hace_24h).exclude(es_saliente).count(),
        'mensajes_salientes_24h':     msj_qs.filter(fecha__gte=hace_24h).filter(es_saliente).count(),
    }
    ultimo_entrante = msj_qs.exclude(es_saliente).order_by('-fecha').first()
    ultimo_saliente = msj_qs.filter(es_saliente).order_by('-fecha').first()

    # ── Estado del webhook + WABA en Meta (Graph API live) ──
    phone_info = _consultar_phone_number(config) if config else {'ok': False, 'error': 'Sesión sin ConfigMeta.'}
    subscribed = _consultar_subscribed_apps(config) if config else {'ok': False, 'error': 'Sesión sin ConfigMeta.'}

    # ── Health summary ──
    salud = []
    salud.append({
        'label': 'WABA suscrita a la app',
        'ok': subscribed.get('ok') and subscribed.get('count', 0) > 0,
        'detalle': (
            f'{subscribed.get("count", 0)} app(s) suscrita(s)' if subscribed.get('ok') else (subscribed.get('error') or 'desconocido')
        ),
        'fix': 'Ejecutá el curl del modal "Datos del webhook" para suscribirla.',
    })
    salud.append({
        'label': 'Webhook verificado en Meta',
        'ok': bool(config and config.webhook_verificado_en),
        'detalle': (
            f'Verificado el {config.webhook_verificado_en:%Y-%m-%d %H:%M}' if (config and config.webhook_verificado_en)
            else 'Pendiente — Meta nunca hizo handshake.'
        ),
        'fix': 'En developers.facebook.com → tu app → Webhooks → Verify and Save.',
    })
    salud.append({
        'label': 'Eventos recibidos (últimas 24h)',
        'ok': eventos_24h > 0,
        'detalle': f'{eventos_24h} evento(s) en 24h',
        'fix': 'Si tenés 0, el webhook no está llegando. Revisá HTTPS y firewall.',
    })
    salud.append({
        'label': 'Firma HMAC válida (últimos 7d)',
        'ok': eventos_firma_invalida == 0,
        'detalle': (
            f'{eventos_firma_invalida} eventos con firma inválida' if eventos_firma_invalida else 'Todas las firmas OK'
        ),
        'fix': 'App Secret desincronizado entre Meta y CredencialMetaApp.',
    })
    quality = (config.quality_rating if config else 'UNKNOWN') or 'UNKNOWN'
    salud.append({
        'label': 'Calidad del número',
        'ok': quality in ('GREEN', 'UNKNOWN'),
        'detalle': quality,
        'fix': 'Si está YELLOW o RED, mejorá el contenido (menos spam-like).',
    })
    salud.append({
        'label': 'Errores IA (últimas 24h)',
        'ok': trazas_error_24h == 0,
        'detalle': f'{trazas_error_24h} error(es)',
        'fix': 'Revisá las trazas para ver el error específico.',
    })

    salud_total_ok = sum(1 for s in salud if s['ok'])
    salud_total = len(salud)

    contexto = {
        'titulo':       f'Diagnóstico · {sesion.nombre or sesion.numero or "sesión"}',
        'descripcion':  'Estado completo de la conexión Meta Cloud API.',
        'ruta':         request.path,
        'sesion':       sesion,
        'config':       config,
        'phone_info':   phone_info,
        'subscribed':   subscribed,
        'eventos_recientes': eventos_recientes,
        'eventos_24h':       eventos_24h,
        'eventos_firma_invalida': eventos_firma_invalida,
        'trazas_recientes':  trazas_recientes,
        'trazas_error_24h':  trazas_error_24h,
        'counts':            counts,
        'ultimo_entrante':   ultimo_entrante,
        'ultimo_saliente':   ultimo_saliente,
        'salud':             salud,
        'salud_total_ok':    salud_total_ok,
        'salud_total':       salud_total,
        'salud_pct':         int((salud_total_ok / salud_total) * 100) if salud_total else 0,
        'now':               ahora,
    }
    addData(request, contexto)
    return render(request, 'whatsapp/sesiones/diagnostico.html', contexto)


@login_required
def meta_suscribir_waba_action(request, sesion_id: int):
    """Endpoint AJAX: suscribe la WABA a la Meta App (POST /{waba_id}/subscribed_apps).

    Reemplaza el curl manual del modal de webhook. Ideal cuando el operador
    cargó la sesión manual y olvidó la auto-suscripción, o cuando Meta perdió
    el binding por algún motivo (re-emisión de token, etc).
    """
    from django.http import JsonResponse
    from django.views.decorators.http import require_POST
    from .meta_manual_view import _suscribir_waba_a_app

    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Solo POST.'})

    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'Sesión no encontrada o no es Meta.'})
    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'ok': False, 'error': 'La sesión no tiene ConfigMeta.'})

    res = _suscribir_waba_a_app(config.waba_id, config.access_token)
    if res.get('ok'):
        return JsonResponse({'ok': True, 'message': 'WABA suscrita correctamente.'})
    return JsonResponse({'ok': False, 'error': res.get('error') or 'Meta rechazó la suscripción.'})
