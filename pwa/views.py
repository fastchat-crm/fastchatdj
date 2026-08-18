import json
import mimetypes
import os

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST


def _get_configuracion():
    try:
        from seguridad.models import Configuracion
        return Configuracion.get_instancia()
    except Exception:
        return None


def _detect_mime(path_or_url):
    if not path_or_url:
        return 'image/png'
    ext = os.path.splitext(path_or_url.split('?')[0])[1].lower()
    mapping = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
        '.svg': 'image/svg+xml',
        '.gif': 'image/gif',
        '.ico': 'image/x-icon',
    }
    if ext in mapping:
        return mapping[ext]
    guessed, _ = mimetypes.guess_type(path_or_url)
    return guessed or 'image/png'


def _normalizar_iconos(items):
    out = []
    for i in items or []:
        src = i.get('src')
        out.append({
            'src': src,
            'sizes': i.get('sizes') or i.get('size'),
            'type': i.get('type') or _detect_mime(src),
            **({'purpose': i['purpose']} if i.get('purpose') else {}),
        })
    return out


def _build_icons(confi):
    fallback = _normalizar_iconos(getattr(settings, 'PWA_APP_ICONS_FALLBACK', []))
    if not confi or not confi.logo_sistema:
        return fallback
    logo_url = confi.logo_sistema.url
    mime = _detect_mime(logo_url)
    if mime == 'image/svg+xml':
        return [
            {'src': logo_url, 'sizes': 'any', 'type': mime, 'purpose': 'any'},
            {'src': logo_url, 'sizes': 'any', 'type': mime, 'purpose': 'maskable'},
        ] + [i for i in fallback if i.get('sizes') in ('192x192', '512x512')]
    return [
        {'src': logo_url, 'sizes': '72x72', 'type': mime},
        {'src': logo_url, 'sizes': '96x96', 'type': mime},
        {'src': logo_url, 'sizes': '128x128', 'type': mime},
        {'src': logo_url, 'sizes': '144x144', 'type': mime},
        {'src': logo_url, 'sizes': '152x152', 'type': mime},
        {'src': logo_url, 'sizes': '192x192', 'type': mime, 'purpose': 'any'},
        {'src': logo_url, 'sizes': '192x192', 'type': mime, 'purpose': 'maskable'},
        {'src': logo_url, 'sizes': '384x384', 'type': mime},
        {'src': logo_url, 'sizes': '512x512', 'type': mime, 'purpose': 'any'},
        {'src': logo_url, 'sizes': '512x512', 'type': mime, 'purpose': 'maskable'},
    ]


@cache_control(max_age=300, public=True)
def manifest(request):
    confi = _get_configuracion()
    nombre = (confi.nombre_empresa if confi else None) or getattr(settings, 'PWA_APP_NAME', 'fastchat')
    short = ((confi.alias if confi else None) or getattr(settings, 'PWA_APP_SHORT_NAME', nombre))[:12] or 'app'
    descripcion = (confi.descripcion if confi else None) or getattr(settings, 'PWA_APP_DESCRIPTION', '')

    payload = {
        'name': nombre,
        'short_name': short,
        'description': descripcion,
        'start_url': getattr(settings, 'PWA_APP_START_URL', '/panel/'),
        'display': getattr(settings, 'PWA_APP_DISPLAY', 'standalone'),
        'scope': getattr(settings, 'PWA_APP_SCOPE', '/'),
        'orientation': getattr(settings, 'PWA_APP_ORIENTATION', 'any'),
        'background_color': getattr(settings, 'PWA_APP_BACKGROUND_COLOR', '#ffffff'),
        'theme_color': getattr(settings, 'PWA_APP_THEME_COLOR', '#2874A6'),
        'lang': getattr(settings, 'PWA_APP_LANG', 'es-ES'),
        'dir': getattr(settings, 'PWA_APP_DIR', 'auto'),
        'icons': _build_icons(confi),
    }
    return JsonResponse(payload)


def service_worker(request):
    response = render(request, 'pwa/service_worker.js')
    response['Content-Type'] = 'application/javascript'
    return response


def offline(request):
    return render(request, 'pwa/offline.html')


@require_POST
def push_subscription_status(request):
    if not getattr(request.user, 'is_authenticated', False):
        return JsonResponse({'registered': False, 'authenticated': False})
    endpoint = ''
    try:
        body = json.loads((request.body or b'').decode('utf-8') or '{}')
        endpoint = (body.get('endpoint') or '').strip()
    except Exception:
        endpoint = ''
    if not endpoint:
        return JsonResponse({'registered': False})
    try:
        from webpush.models import PushInformation
        registered = PushInformation.objects.filter(
            user=request.user,
            subscription__endpoint=endpoint,
        ).exists()
    except Exception:
        registered = True
    return JsonResponse({'registered': registered})
