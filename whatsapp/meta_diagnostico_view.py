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


def _numero_en_su_waba(config: ConfigMeta, timeout: int = 10) -> dict:
    """¿El phone_number_id pertenece realmente a la WABA guardada en el CRM?

    GET /{waba_id}/phone_numbers y busca el phone_number_id. Detecta el caso en
    que el CRM guardó la WABA equivocada (típico al copiar la de otro número).
    """
    if not (config.access_token and config.waba_id and config.phone_number_id):
        return {'ok': False, 'error': 'Falta waba_id, phone_number_id o access_token.'}
    try:
        r = requests.get(
            build_graph_url(f'/{config.waba_id}/phone_numbers'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            params={'fields': 'id,display_phone_number'},
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
    ids = [str(n.get('id')) for n in (r.json() or {}).get('data', [])]
    return {'ok': True, 'pertenece': str(config.phone_number_id) in ids, 'ids': ids}


def _business_id_org() -> str:
    """Business Manager ID del singleton CredencialMetaApp (para escanear WABAs)."""
    try:
        from seguridad.models import Configuracion as _Conf, CredencialMetaApp as _Cred
        confi = _Conf.get_instancia()
        cred = _Cred.objects.filter(configuracion=confi).first() if confi else None
        return (cred.business_id or '') if cred else ''
    except Exception:
        return ''


def _descubrir_waba_real(config: ConfigMeta, timeout: int = 15) -> dict:
    """Escanea las WABAs del negocio y devuelve la WABA real que contiene el
    phone_number_id. Útil cuando el waba_id del CRM es incorrecto.

    Devuelve {ok, waba_id, name} o {ok: False, error}.
    """
    business_id = _business_id_org()
    if not business_id:
        return {'ok': False, 'error': 'Falta Business Manager ID en Credenciales Meta App.'}
    objetivo = str(config.phone_number_id)
    for edge in ('owned_whatsapp_business_accounts', 'client_whatsapp_business_accounts'):
        try:
            r = requests.get(
                build_graph_url(f'/{business_id}/{edge}'),
                headers={'Authorization': f'Bearer {config.access_token}'},
                params={'fields': 'id,name,phone_numbers.limit(100){id,display_phone_number}'},
                timeout=timeout,
            )
        except Exception:
            continue
        if r.status_code != 200:
            continue
        for waba in (r.json() or {}).get('data', []):
            nums = (waba.get('phone_numbers') or {}).get('data', [])
            if any(str(n.get('id')) == objetivo for n in nums):
                return {'ok': True, 'waba_id': str(waba.get('id')), 'name': waba.get('name') or ''}
    return {'ok': False, 'error': f'No encontré el número {objetivo} en ninguna WABA del negocio.'}


def _validar_conexion(config: ConfigMeta) -> dict:
    """Corre los chequeos de conexión contra Graph y devuelve pasos estructurados
    (estilo el script prueba_conexion_meta) para mostrar en un modal: qué pasa y
    en qué punto falla. Identifica acciones correctivas disponibles en el diagnóstico.

    Devuelve {pasos: [{label, ok, detalle, accion}], waba_mal, waba_real, verdicto}.
    """
    pasos = []
    waba_mal = False
    waba_real = ''

    # 1) Estado del número en Meta
    info = _consultar_phone_number(config)
    if not info.get('ok'):
        pasos.append({'label': 'Número leído en Meta', 'ok': False,
                      'detalle': info.get('error') or 'No se pudo consultar el número.', 'accion': ''})
    else:
        d = info['data']
        status = (d.get('status') or '').upper()
        platform = d.get('platform_type') or '(no informado)'
        conectado = status == 'CONNECTED'
        detalle = f"status={status or '?'} · platform_type={platform} · calidad={d.get('quality_rating', '?')}"
        accion = '' if conectado else 'registrar'
        if conectado and platform not in ('CLOUD_API', '(no informado)'):
            detalle += ' — platform_type ≠ CLOUD_API: posible coexistencia con la app.'
        pasos.append({'label': 'Número CONNECTED en Cloud API', 'ok': conectado,
                      'detalle': detalle, 'accion': accion})

    # 2) El número pertenece a su WABA (detección del waba_id mal cargado)
    en_waba = _numero_en_su_waba(config)
    if not en_waba.get('ok'):
        pasos.append({'label': 'Número pertenece a su WABA', 'ok': None,
                      'detalle': en_waba.get('error') or 'No se pudo verificar.', 'accion': ''})
    elif en_waba.get('pertenece'):
        pasos.append({'label': 'Número pertenece a su WABA', 'ok': True,
                      'detalle': f'El número está en la WABA guardada ({config.waba_id}).', 'accion': ''})
    else:
        waba_mal = True
        real = _descubrir_waba_real(config)
        if real.get('ok'):
            waba_real = real['waba_id']
            detalle = (f'El número NO está en la WABA guardada ({config.waba_id}). '
                       f'WABA real: {waba_real} ("{real.get("name", "")}"). '
                       'Por eso los entrantes no llegan.')
        else:
            detalle = (f'El número NO está en la WABA guardada ({config.waba_id}). '
                       f'No pude detectar la real: {real.get("error", "")}')
        pasos.append({'label': 'Número pertenece a su WABA', 'ok': False,
                      'detalle': detalle, 'accion': 'corregir-waba'})

    # 3) WABA suscrita a la app
    subs = _consultar_subscribed_apps(config)
    if not subs.get('ok'):
        pasos.append({'label': 'WABA suscrita a la app', 'ok': None,
                      'detalle': subs.get('error') or 'No se pudo verificar.', 'accion': ''})
    else:
        suscrita = subs.get('count', 0) > 0
        pasos.append({'label': 'WABA suscrita a la app', 'ok': suscrita,
                      'detalle': (f'{subs.get("count", 0)} app(s) suscrita(s).' if suscrita
                                  else 'Ninguna app suscrita a esta WABA — los entrantes no llegan.'),
                      'accion': '' if suscrita else 'suscribir-waba'})

    # 4) Webhook verificado en Meta
    pasos.append({'label': 'Webhook verificado en Meta', 'ok': bool(config.webhook_verificado_en),
                  'detalle': (f'Verificado el {config.webhook_verificado_en:%Y-%m-%d %H:%M}'
                              if config.webhook_verificado_en else 'Pendiente — Meta nunca hizo handshake.'),
                  'accion': '' if config.webhook_verificado_en else 'configurar-webhook'})

    fallas = [p for p in pasos if p.get('ok') is False]
    if not fallas:
        verdicto = 'Todo OK. La conexión está bien configurada.'
    elif waba_mal:
        verdicto = ('La WABA guardada es incorrecta — es la causa típica de "envía pero no '
                    'recibe". Corregila desde el diagnóstico con un clic.')
    else:
        verdicto = f'Hay {len(fallas)} punto(s) a corregir. Andá al diagnóstico para ejecutarlos.'

    return {'pasos': pasos, 'waba_mal': waba_mal, 'waba_real': waba_real,
            'verdicto': verdicto, 'falla': bool(fallas)}


@login_required
def meta_validar_conexion_action(request, sesion_id: int):
    """Endpoint AJAX: corre la validación de conexión y devuelve los pasos para
    el modal. El front muestra qué punto falla y enlaza al diagnóstico."""
    from django.http import JsonResponse

    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'Sesión no encontrada o no es Meta.'})
    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'ok': False, 'error': 'La sesión no tiene ConfigMeta.'})

    res = _validar_conexion(config)
    res['ok'] = True
    res['sesion_id'] = sesion.id
    res['sesion_nombre'] = sesion.nombre or sesion.numero or f'Sesión {sesion.id}'
    res['diagnostico_url'] = f'/whatsapp/sesiones/{sesion.id}/diagnostico/'
    return JsonResponse(res)


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
    inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    inicio_mes_anterior = (inicio_mes - timedelta(days=1)).replace(day=1)

    # ── Métricas de eventos Meta (resumen) ──
    # El detalle por evento (tabla, payload, polling en vivo) vive en
    # /whatsapp/sesiones/<id>/webhook-log/. Acá guardamos solo los conteos
    # que alimentan el score de salud para evitar duplicar la auditoría.
    eventos_24h = 0
    eventos_firma_invalida = 0
    eventos_con_error_24h = 0
    if config:
        eventos_qs = EventoMetaRecibido.objects.filter(config_meta=config)
        eventos_24h = eventos_qs.filter(recibido_en__gte=hace_24h).count()
        eventos_firma_invalida = eventos_qs.filter(
            recibido_en__gte=hace_7d, firma_valida=False,
        ).count()
        eventos_con_error_24h = eventos_qs.filter(
            recibido_en__gte=hace_24h,
        ).exclude(error_procesamiento__isnull=True).exclude(error_procesamiento='').count()

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
    conv_mes_actual = conv_qs.filter(fecha_registro__gte=inicio_mes).count()
    conv_mes_anterior = conv_qs.filter(
        fecha_registro__gte=inicio_mes_anterior,
        fecha_registro__lt=inicio_mes,
    ).count()
    if conv_mes_anterior > 0:
        delta_mes_pct = int(round(((conv_mes_actual - conv_mes_anterior) / conv_mes_anterior) * 100))
    else:
        delta_mes_pct = None  # sin base de comparación
    counts = {
        'conversaciones_total':       conv_qs.count(),
        'conversaciones_24h':         conv_qs.filter(fecha_registro__gte=hace_24h).count(),
        'conversaciones_mes':         conv_mes_actual,
        'conversaciones_mes_ant':     conv_mes_anterior,
        'conversaciones_mes_delta':   delta_mes_pct,
        'mensajes_total':             msj_qs.count(),
        'mensajes_24h':               msj_qs.filter(fecha__gte=hace_24h).count(),
        'mensajes_mes':               msj_qs.filter(fecha__gte=inicio_mes).count(),
        'mensajes_entrantes_24h':     msj_qs.filter(fecha__gte=hace_24h).exclude(es_saliente).count(),
        'mensajes_salientes_24h':     msj_qs.filter(fecha__gte=hace_24h).filter(es_saliente).count(),
    }
    ultimo_entrante = msj_qs.exclude(es_saliente).order_by('-fecha').first()
    ultimo_saliente = msj_qs.filter(es_saliente).order_by('-fecha').first()

    # ── Estado del webhook + WABA en Meta (Graph API live) ──
    phone_info = _consultar_phone_number(config) if config else {'ok': False, 'error': 'Sesión sin ConfigMeta.'}
    subscribed = _consultar_subscribed_apps(config) if config else {'ok': False, 'error': 'Sesión sin ConfigMeta.'}
    en_waba = _numero_en_su_waba(config) if config else {'ok': False, 'error': 'Sesión sin ConfigMeta.'}
    # waba_mal: el número NO pertenece a la WABA guardada → routing de entrantes roto.
    waba_mal = bool(en_waba.get('ok') and not en_waba.get('pertenece'))

    # ── Business ID para deep-links de Meta (Insights + Billing) ──
    # Prioriza el de la sesión (ConfigMeta.business_account_id) y cae al
    # singleton org-level (CredencialMetaApp.business_id) si no está cargado.
    meta_business_id = ''
    if config and config.business_account_id:
        meta_business_id = config.business_account_id
    else:
        try:
            from seguridad.models import Configuracion as _Conf, CredencialMetaApp as _Cred
            _confi = _Conf.get_instancia()
            if _confi and _confi.pk:
                _cred = _Cred.objects.filter(configuracion=_confi).first()
                if _cred and _cred.business_id:
                    meta_business_id = _cred.business_id
        except Exception:
            pass

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
        'label': 'Número pertenece a su WABA',
        'ok': bool(en_waba.get('ok') and en_waba.get('pertenece')),
        'detalle': (
            'El número está en la WABA guardada.' if (en_waba.get('ok') and en_waba.get('pertenece'))
            else ('El número NO está en la WABA guardada — waba_id incorrecto. Los entrantes no llegan.'
                  if en_waba.get('ok') else (en_waba.get('error') or 'desconocido'))
        ),
        'fix': 'Usá el botón "Detectar y corregir WABA" para arreglarlo automáticamente.',
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
        'fix': (
            'App Secret desincronizado entre Meta y CredencialMetaApp. '
            'Copiá la "Clave secreta de la app" desde Meta for Developers '
            '(tu App → Configuración → Información básica → Mostrar) y pegala '
            'en Seguridad → Credenciales Meta App. Los eventos rechazados quedan '
            'guardados y se recuperan con: python manage.py reprocesar_eventos_meta'
        ),
        'fix_url': '/seguridad/credencial-meta/',
        'fix_url_label': 'Ir a Credenciales Meta App',
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

    # ── Datos para el panel de webhook (FIX 2) + detalle de la sesión ──
    from django.urls import reverse
    from meta.credenciales import get_meta_app_credentials

    webhook_url = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
    try:
        meta_app_id, _meta_app_secret = get_meta_app_credentials()
    except Exception:
        meta_app_id, _meta_app_secret = '', ''
    meta_app_secret_ok = bool(_meta_app_secret)

    def _mask_token(tok) -> str:
        """Enmascara credenciales: muestra solo los últimos 4 caracteres."""
        tok = str(tok or '')
        if not tok:
            return ''
        return f'••••{tok[-4:]}' if len(tok) > 4 else '••••'

    access_token_mask = _mask_token(config.access_token) if config else ''
    ads_access_token_mask = _mask_token(config.ads_access_token) if config else ''

    contexto = {
        'titulo':       f'Diagnóstico · {sesion.nombre or sesion.numero or "sesión"}',
        'descripcion':  'Estado completo de la conexión Meta Cloud API.',
        'ruta':         request.path,
        'sesion':       sesion,
        'config':       config,
        'webhook_url':            webhook_url,
        'meta_app_id':            meta_app_id,
        'meta_app_secret_ok':     meta_app_secret_ok,
        'access_token_mask':      access_token_mask,
        'ads_access_token_mask':  ads_access_token_mask,
        'phone_info':   phone_info,
        'subscribed':   subscribed,
        'en_waba':      en_waba,
        'waba_mal':     waba_mal,
        'eventos_24h':            eventos_24h,
        'eventos_firma_invalida': eventos_firma_invalida,
        'eventos_con_error_24h':  eventos_con_error_24h,
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
        'meta_business_id':  meta_business_id,
    }
    addData(request, contexto)
    return render(request, 'whatsapp/sesiones/diagnostico.html', contexto)


@login_required
def meta_cambiar_nombre_action(request, sesion_id: int):
    """Endpoint AJAX: solicita el cambio de Display Name del número a Meta.

    POST /{phone_number_id} con new_display_name. La respuesta exitosa solo
    significa "enviado a revisión" (name_status pasa a PENDING_REVIEW), NO
    aprobado. Por eso NO sobreescribimos el verified_name del CRM acá — eso lo
    hace la sync con Graph cuando Meta aprueba (name_status=APPROVED).
    """
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Solo POST.'})

    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'Sesión no encontrada o no es Meta.'})
    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'ok': False, 'error': 'La sesión no tiene ConfigMeta.'})
    if not (config.access_token and config.phone_number_id):
        return JsonResponse({'ok': False, 'error': 'Falta access_token o phone_number_id.'})

    nuevo = (request.POST.get('nombre') or '').strip()
    if len(nuevo) < 3:
        return JsonResponse({'ok': False, 'error': 'El nombre debe tener al menos 3 caracteres.'})

    try:
        r = requests.post(
            build_graph_url(f'/{config.phone_number_id}'),
            headers={'Authorization': f'Bearer {config.access_token}'},
            json={'new_display_name': nuevo},
            timeout=20,
        )
    except Exception as ex:
        return JsonResponse({'ok': False, 'error': f'No pude llamar a Graph: {ex}'})

    if r.status_code != 200:
        try:
            err = r.json().get('error', {}).get('message', r.text[:300])
        except Exception:
            err = r.text[:300]
        return JsonResponse({'ok': False, 'error': f'Meta rechazó el cambio: {err}'})

    logger.info("Display name solicitado: '%s' para phone_number_id=%s (sesión %s)",
                nuevo, config.phone_number_id, sesion.id)
    return JsonResponse({
        'ok': True,
        'message': f'Cambio a "{nuevo}" enviado a revisión de Meta. El número sigue operando '
                   'con el nombre actual hasta que Meta lo apruebe (name_status PENDING_REVIEW).',
        'meta_url': _url_meta_numero(config),
    })


def _url_meta_numero(config: ConfigMeta) -> str:
    """Deep-link al número en WhatsApp Manager (para revisar/validar el nombre)."""
    business_id = config.business_account_id or _business_id_org()
    url = 'https://business.facebook.com/latest/whatsapp_manager/phone_numbers/?'
    if business_id:
        url += f'business_id={business_id}&'
    url += f'asset_id={config.waba_id}&nav_ref=whatsapp_manager&tab=phone-numbers'
    if config.phone_number_id:
        url += f'&phone_number_id={config.phone_number_id}'
    return url


@login_required
def meta_corregir_waba_action(request, sesion_id: int):
    """Endpoint AJAX: detecta la WABA real del número y corrige el CRM.

    Cuando el número no pertenece a la WABA guardada (waba_id mal cargado), los
    entrantes nunca llegan. Esta acción:
      1. Escanea las WABAs del negocio y encuentra la real que contiene el número.
      2. Actualiza ConfigMeta.waba_id (y business_account_id si aplica).
      3. Suscribe esa WABA real a la Meta App (subscribed_apps).
    """
    from django.http import JsonResponse
    from .meta_manual_view import _suscribir_waba_a_app

    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Solo POST.'})

    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'Sesión no encontrada o no es Meta.'})
    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'ok': False, 'error': 'La sesión no tiene ConfigMeta.'})

    real = _descubrir_waba_real(config)
    if not real.get('ok'):
        return JsonResponse({'ok': False, 'error': real.get('error') or 'No pude detectar la WABA real.'})

    waba_real = real['waba_id']
    waba_anterior = config.waba_id

    if str(waba_real) == str(config.waba_id):
        # Ya estaba bien; igual aseguramos la suscripción.
        sub = _suscribir_waba_a_app(waba_real, config.access_token)
        if sub.get('ok'):
            return JsonResponse({'ok': True, 'message': f'El waba_id ya era correcto ({waba_real}). '
                                                        'WABA suscrita a la app.'})
        return JsonResponse({'ok': False, 'error': sub.get('error') or 'Meta rechazó la suscripción.'})

    config.waba_id = waba_real
    config.save(request)

    sub = _suscribir_waba_a_app(waba_real, config.access_token)
    logger.info("Corregido waba_id de sesión %s: %s → %s (suscripción ok=%s)",
                sesion.id, waba_anterior, waba_real, sub.get('ok'))

    if sub.get('ok'):
        return JsonResponse({
            'ok': True,
            'message': f'WABA corregida: {waba_anterior} → {waba_real} ("{real.get("name", "")}") '
                       'y suscrita a la app. Probá recibir un mensaje ahora.',
        })
    return JsonResponse({
        'ok': True,
        'message': f'WABA corregida: {waba_anterior} → {waba_real}, pero la suscripción falló: '
                   f'{sub.get("error")}. Probá el botón "Suscribir WABA".',
    })


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


@login_required
def meta_configurar_webhook_action(request, sesion_id: int):
    """Endpoint AJAX: configura el webhook de la Meta App vía Graph (FIX 2).

    Hace POST /{app_id}/subscriptions con object=whatsapp_business_account,
    callback_url y verify_token. Esto equivale al botón "Verify and Save" del
    panel de Meta: al recibirlo, Meta dispara el handshake GET contra nuestro
    endpoint, que marca todas las sesiones como verificadas.

    El webhook es a nivel APP, así que con configurarlo una vez alcanza para
    todos los números. Usa las credenciales App-level (app_id/app_secret) del
    singleton CredencialMetaApp.
    """
    from django.http import JsonResponse
    from django.urls import reverse
    from meta.credenciales import get_meta_app_credentials

    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Solo POST.'})

    sesion = SesionWhatsApp.objects.filter(id=sesion_id, proveedor='meta').first()
    if not sesion:
        return JsonResponse({'ok': False, 'error': 'Sesión no encontrada o no es Meta.'})
    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'ok': False, 'error': 'La sesión no tiene ConfigMeta.'})
    if not config.webhook_verify_token:
        return JsonResponse({'ok': False, 'error': 'La sesión no tiene verify token.'})

    app_id, app_secret = get_meta_app_credentials()
    if not (app_id and app_secret):
        return JsonResponse({
            'ok': False,
            'error': 'Faltan App ID / App Secret de la Meta App. Cargalos en Seguridad → Credenciales Meta App.',
        })

    callback_url = request.build_absolute_uri(reverse('whatsapp_meta_webhook'))
    try:
        r = requests.post(
            build_graph_url(f'/{app_id}/subscriptions'),
            params={
                'object': 'whatsapp_business_account',
                'callback_url': callback_url,
                'verify_token': config.webhook_verify_token,
                'fields': 'messages,message_template_status_update',
                'access_token': f'{app_id}|{app_secret}',
            },
            timeout=15,
        )
    except Exception as ex:
        return JsonResponse({'ok': False, 'error': f'No pude llamar a Graph: {ex}'})

    if r.status_code != 200:
        try:
            err = r.json().get('error', {}).get('message', r.text[:300])
        except Exception:
            err = r.text[:300]
        return JsonResponse({'ok': False, 'error': f'Meta rechazó la configuración: {err}'})

    logger.info("Webhook app-level configurado vía Graph (app_id=%s, callback=%s)", app_id, callback_url)
    return JsonResponse({
        'ok': True,
        'message': 'Webhook configurado en Meta. El handshake debería marcar las sesiones como verificadas.',
    })
