"""OAuth Embedded Signup para WhatsApp Cloud API (Meta).

Flujo:
1. Usuario toca "Continuar" en el panel WhatsApp del modal "Agregar conexion".
2. JS abre popup a /whatsapp/meta/oauth/start/ -> redirige a Facebook OAuth
   con config_id de Embedded Signup WhatsApp Business.
3. Usuario selecciona su WABA + numero en el dialogo de Meta.
4. Meta redirige a /whatsapp/meta/oauth/callback/?code=...&state=...
5. Callback canjea code -> access_token, descubre WABA + phone_number_id via
   Graph API, crea SesionWhatsApp(proveedor='meta') + ConfigMeta.
6. Popup notifica a window.opener con postMessage y se cierra; el tablero
   refresca y muestra la nueva sesion.
"""
from __future__ import annotations

import json
import logging
import secrets
import urllib.parse
import uuid

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from core.funciones import log, secure_module

from .models import ConfigMeta, SesionWhatsApp
from .sesiones_common import sincronizar_meta_desde_graph

logger = logging.getLogger(__name__)


# ---------- Helpers ----------

def _graph(path: str) -> str:
    return f'https://graph.facebook.com/{settings.META_API_VERSION}{path}'


def _fb(path: str) -> str:
    return f'https://www.facebook.com/{settings.META_API_VERSION}{path}'


def _creds_listas() -> bool:
    return bool(settings.META_APP_ID and settings.META_APP_SECRET and settings.META_CONFIG_ID)


def _popup_html(payload: dict) -> HttpResponse:
    """Devuelve HTML mini que hace postMessage(payload) al opener y cierra."""
    body = f"""<!doctype html><html><head><meta charset="utf-8"><title>Conectando...</title></head>
<body style="font-family:system-ui;padding:2rem;text-align:center">
<p>Procesando conexion con WhatsApp...</p>
<script>
  (function(){{
    var data = {json.dumps(payload)};
    try {{
      if (window.opener) window.opener.postMessage({{source:'meta_oauth', payload:data}}, '*');
    }} catch(e){{}}
    setTimeout(function(){{ window.close(); }}, 400);
  }})();
</script>
</body></html>"""
    return HttpResponse(body)


# ---------- Endpoints ----------

@login_required
@secure_module
@require_GET
def meta_oauth_start(request):
    """Arma URL de Facebook OAuth + state y redirige al popup alli."""
    if not _creds_listas():
        return _popup_html({
            'ok': False,
            'error': 'Faltan credenciales META en el servidor (META_APP_ID / META_APP_SECRET / META_CONFIG_ID).',
        })

    state = secrets.token_urlsafe(24)
    request.session['meta_oauth_state'] = state
    request.session['meta_oauth_user_id'] = request.user.id

    redirect_uri = request.build_absolute_uri(reverse('whatsapp_meta_oauth_callback'))

    extras = {
        'features': [
            {'name': 'marketing_messages_lite'},
            {'name': 'cloud_api'},
            {'name': 'conversions_api'},
        ],
        'version': 'v4',
        'featureType': 'whatsapp_business_app_onboarding',
    }

    params = {
        'app_id':        settings.META_APP_ID,
        'client_id':     settings.META_APP_ID,
        'config_id':     settings.META_CONFIG_ID,
        'display':       'popup',
        'response_type': 'code',
        'redirect_uri':  redirect_uri,
        'state':         state,
        'extras':        json.dumps(extras, separators=(',', ':')),
    }
    url = _fb('/dialog/oauth') + '?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return HttpResponseRedirect(url)


@require_GET
def meta_oauth_callback(request):
    """Canjea code -> token, descubre WABA + phone_number_id y crea la sesion."""
    err = request.GET.get('error') or request.GET.get('error_reason')
    if err:
        return _popup_html({'ok': False, 'error': f'Meta rechazo la conexion: {err}'})

    code = request.GET.get('code', '').strip()
    state = request.GET.get('state', '').strip()
    if not code:
        return _popup_html({'ok': False, 'error': 'No llego code de Meta.'})

    if state != request.session.get('meta_oauth_state'):
        return _popup_html({'ok': False, 'error': 'State invalido (posible CSRF).'})

    user_id = request.session.get('meta_oauth_user_id')
    if not user_id:
        return _popup_html({'ok': False, 'error': 'Sesion del usuario perdida. Volve a iniciar el flujo.'})

    from autenticacion.models import Usuario
    try:
        usuario = Usuario.objects.get(id=user_id)
    except Usuario.DoesNotExist:
        return _popup_html({'ok': False, 'error': 'Usuario no existe.'})

    redirect_uri = request.build_absolute_uri(reverse('whatsapp_meta_oauth_callback'))

    # 1) code -> access_token (token de usuario de FB)
    try:
        r = requests.get(
            _graph('/oauth/access_token'),
            params={
                'client_id':     settings.META_APP_ID,
                'client_secret': settings.META_APP_SECRET,
                'redirect_uri':  redirect_uri,
                'code':          code,
            }, timeout=15,
        )
    except Exception as ex:
        return _popup_html({'ok': False, 'error': f'Error llamando Graph oauth: {ex}'})
    if r.status_code != 200:
        return _popup_html({'ok': False, 'error': f'Graph oauth fallo: {r.status_code} {r.text[:300]}'})
    user_token = r.json().get('access_token', '')
    if not user_token:
        return _popup_html({'ok': False, 'error': 'Graph oauth no devolvio access_token.'})

    # 1b) Exchange short-lived -> long-lived (~60 dias para user token)
    try:
        rl = requests.get(
            _graph('/oauth/access_token'),
            params={
                'grant_type':        'fb_exchange_token',
                'client_id':         settings.META_APP_ID,
                'client_secret':     settings.META_APP_SECRET,
                'fb_exchange_token': user_token,
            }, timeout=15,
        )
        if rl.status_code == 200:
            ll = rl.json().get('access_token')
            if ll:
                user_token = ll
                logger.info("Token long-lived obtenido para OAuth callback.")
    except Exception as ex:
        logger.warning("Exchange long-lived token fallo (sigo con short-lived): %s", ex)

    # 2) debug_token -> sacar WABA id de los granular_scopes
    waba_id = ''
    try:
        d = requests.get(
            _graph('/debug_token'),
            params={
                'input_token':  user_token,
                'access_token': f'{settings.META_APP_ID}|{settings.META_APP_SECRET}',
            }, timeout=15,
        )
        if d.status_code == 200:
            granular = d.json().get('data', {}).get('granular_scopes', []) or []
            for scope in granular:
                if scope.get('scope') in ('whatsapp_business_management', 'whatsapp_business_messaging'):
                    ids = scope.get('target_ids') or []
                    if ids:
                        waba_id = str(ids[0])
                        break
    except Exception as ex:
        logger.warning("debug_token fallo: %s", ex)

    if not waba_id:
        return _popup_html({'ok': False, 'error': 'No se pudo determinar el WABA ID desde debug_token.'})

    # 3) phone_numbers del WABA
    try:
        p = requests.get(
            _graph(f'/{waba_id}/phone_numbers'),
            params={'access_token': user_token}, timeout=15,
        )
    except Exception as ex:
        return _popup_html({'ok': False, 'error': f'Error listando phone_numbers: {ex}'})
    if p.status_code != 200:
        return _popup_html({'ok': False, 'error': f'Listar phone_numbers fallo: {p.status_code} {p.text[:300]}'})
    phones = (p.json() or {}).get('data', []) or []
    if not phones:
        return _popup_html({'ok': False, 'error': 'El WABA autorizado no tiene numeros. Agrega uno en Meta Business.'})
    phone = phones[0]
    phone_number_id = str(phone.get('id', ''))
    display_phone   = phone.get('display_phone_number', '') or ''
    verified_name   = phone.get('verified_name', '') or ''

    # 4) Crear sesion + ConfigMeta
    existing = ConfigMeta.objects.filter(phone_number_id=phone_number_id).first()
    if existing:
        return _popup_html({
            'ok': False,
            'error': f'Este numero ({display_phone or phone_number_id}) ya esta conectado en otra sesion.',
            'sesion_id': existing.sesion_id,
        })

    sesion = SesionWhatsApp.objects.create(
        nombre=verified_name or display_phone or f'WA {phone_number_id[-6:]}',
        proveedor='meta',
        estado='pendiente',
        usuario=usuario,
        session_id=str(uuid.uuid4()),
        qr_code='',
        whatsapp_id='',
    )
    config = ConfigMeta.objects.create(
        sesion=sesion,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        display_phone_number=display_phone,
        access_token=user_token,
        app_id=settings.META_APP_ID,
        app_secret=settings.META_APP_SECRET,
        webhook_verify_token=secrets.token_urlsafe(32),
    )

    # 5) Suscribir la App al WABA para recibir webhooks (mensajes entrantes).
    #    Sin esto, Meta acepta envios salientes pero no reenvia los eventos a
    #    nuestro /whatsapp/meta_webhook/. Idempotente — Meta devuelve 200 si
    #    ya estaba suscrito.
    try:
        s = requests.post(
            _graph(f'/{waba_id}/subscribed_apps'),
            headers={'Authorization': f'Bearer {user_token}'},
            timeout=15,
        )
        if s.status_code in (200, 201):
            logger.info("App suscrita al WABA %s (webhook listo).", waba_id)
        else:
            logger.warning("subscribed_apps %s fallo: %s %s", waba_id, s.status_code, s.text[:200])
    except Exception as ex:
        logger.warning("subscribed_apps excepcion: %s", ex)

    # 6) Sync contra Graph para quality/limit/numero
    try:
        sincronizar_meta_desde_graph(sesion, config)
        sesion.refresh_from_db()
    except Exception as ex:
        logger.warning("Sync Meta post-oauth fallo: %s", ex)

    log(f"Sesion Meta creada via OAuth Embedded Signup: WABA={waba_id} phone={phone_number_id}",
        request, "add", obj=sesion.id)

    request.session.pop('meta_oauth_state', None)
    request.session.pop('meta_oauth_user_id', None)

    return _popup_html({
        'ok':        True,
        'sesion_id': sesion.id,
        'numero':    sesion.numero or display_phone,
        'nombre':    sesion.nombre,
    })
