from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control


def _get_configuracion():
    try:
        from seguridad.models import Configuracion
        return Configuracion.get_instancia()
    except Exception:
        return None


def _normalizar_iconos(items):
    out = []
    for i in items or []:
        out.append({
            'src': i.get('src'),
            'sizes': i.get('sizes') or i.get('size'),
            'type': i.get('type', 'image/png'),
            **({'purpose': i['purpose']} if i.get('purpose') else {}),
        })
    return out


def _build_icons(confi):
    fallback = _normalizar_iconos(getattr(settings, 'PWA_APP_ICONS_FALLBACK', []))
    if not confi or not confi.logo_sistema:
        return fallback
    logo_url = confi.logo_sistema.url
    return [
        {'src': logo_url, 'sizes': '72x72', 'type': 'image/png'},
        {'src': logo_url, 'sizes': '96x96', 'type': 'image/png'},
        {'src': logo_url, 'sizes': '128x128', 'type': 'image/png'},
        {'src': logo_url, 'sizes': '144x144', 'type': 'image/png'},
        {'src': logo_url, 'sizes': '152x152', 'type': 'image/png'},
        {'src': logo_url, 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
        {'src': logo_url, 'sizes': '384x384', 'type': 'image/png'},
        {'src': logo_url, 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'},
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
