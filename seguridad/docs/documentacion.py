"""Vista unificada de documentación.

Despacha por `?pagina=<slug>` a las distintas hojas:
    - plataforma  (default): visión general de FastChat DJ
    - conectar-whatsapp-business: guía de conexión Meta Cloud API
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.funciones import addData, secure_module
from seguridad.models import Configuracion


DOCS_SIDEBAR = [
    {
        'titulo': 'Inicio',
        'items': [
            {'nombre': 'Plataforma FastChat DJ', 'slug': 'plataforma'},
            {'nombre': 'Novedades', 'slug': 'novedades'},
            {'nombre': 'Conectar con plataformas', 'slug': 'conectar-whatsapp-business'},
        ],
    },
    {
        'titulo': 'Gestión de conversaciones',
        'items': [
            {'nombre': 'Sesiones WhatsApp — guía del número', 'slug': 'sesiones-whatsapp'},
        ],
    },
    {
        'titulo': 'Mensajería Instantánea',
        'items': [
            {'nombre': 'Crear y operar un flujo', 'slug': 'mensajeria-instantanea'},
        ],
    },
    {
        'titulo': 'Estadísticas',
        'items': [],
    },
    {
        'titulo': 'Configuración',
        'items': [],
    },
    {
        'titulo': 'Funciones por plataforma',
        'items': [
            {'nombre': 'WhatsApp Business API', 'slug': 'conectar-whatsapp-business'},
            {'nombre': 'Instagram, Facebook y TikTok — conexión y tokens', 'slug': 'conectar-instagram-tiktok'},
        ],
    },
    {
        'titulo': 'Para desarrolladores',
        'items': [
            {'nombre': 'Webhooks', 'slug': 'webhooks'},
        ],
    },
]


PAGINA_DEFAULT = 'plataforma'


def _ctx_sidebar(request, slug_actual, titulo_pagina):
    data = {
        'titulo': titulo_pagina,
        'modulo': 'Documentación',
        'ruta': request.path,
        'sidebar': DOCS_SIDEBAR,
        'slug_actual': slug_actual,
        'breadcrumb': [
            {'nombre': 'Documentación', 'url': '/seguridad/documentacion/'},
            {'nombre': titulo_pagina, 'url': None},
        ],
    }
    addData(request, data)
    return data


def _hoja_plataforma(request):
    data = _ctx_sidebar(
        request,
        slug_actual='plataforma',
        titulo_pagina='Plataforma FastChat DJ',
    )
    data['confi'] = Configuracion.get_instancia()
    return render(request, 'docs/index.html', data)


def _hoja_conectar_whatsapp_business(request):
    data = _ctx_sidebar(
        request,
        slug_actual='conectar-whatsapp-business',
        titulo_pagina='Conectar WhatsApp Business API',
    )
    return render(request, 'whatsapp/docs/conectar_whatsapp_business.html', data)


def _hoja_mensajeria_instantanea(request):
    """Tutorial de cómo crear y operar un flujo del chatbot tradicional
    (Mensajería Instantánea). Replica la guía del modal in-app del editor."""
    data = _ctx_sidebar(
        request,
        slug_actual='mensajeria-instantanea',
        titulo_pagina='Mensajería Instantánea — Crear y operar un flujo',
    )
    return render(request, 'docs/mensajeria_instantanea.html', data)


def _hoja_sesiones_whatsapp(request):
    """Guía del número: funciones por sesión (plantillas, horarios, agente IA,
    campañas, trazas, consumo) y alta de un número nuevo desde cero."""
    data = _ctx_sidebar(
        request,
        slug_actual='sesiones-whatsapp',
        titulo_pagina='Sesiones WhatsApp — guía del número',
    )
    return render(request, 'docs/sesiones_whatsapp.html', data)


def _hoja_conectar_instagram_tiktok(request):
    """Guía técnica: cómo funciona la integración Instagram/TikTok, cómo obtener
    los tokens de acceso y cómo registrar la cuenta en la plataforma."""
    data = _ctx_sidebar(
        request,
        slug_actual='conectar-instagram-tiktok',
        titulo_pagina='Instagram, Facebook y TikTok — conexión y tokens',
    )
    return render(request, 'docs/conexion_instagram_tiktok.html', data)


def _hoja_webhooks(request):
    """Referencia de webhooks: entrantes (Meta/Baileys/IG/Messenger/heartbeat/trace)
    y saliente (integraciones). Explica la función de cada uno."""
    data = _ctx_sidebar(
        request,
        slug_actual='webhooks',
        titulo_pagina='Webhooks',
    )
    return render(request, 'docs/webhooks.html', data)


def _hoja_novedades(request):
    """Resumen de las funciones nuevas de la plataforma."""
    data = _ctx_sidebar(
        request,
        slug_actual='novedades',
        titulo_pagina='Novedades de la plataforma',
    )
    return render(request, 'docs/novedades.html', data)


HOJAS = {
    'plataforma': _hoja_plataforma,
    'conectar-whatsapp-business': _hoja_conectar_whatsapp_business,
    'conectar-instagram-tiktok': _hoja_conectar_instagram_tiktok,
    'mensajeria-instantanea': _hoja_mensajeria_instantanea,
    'sesiones-whatsapp': _hoja_sesiones_whatsapp,
    'webhooks': _hoja_webhooks,
    'novedades': _hoja_novedades,
}


@login_required
@secure_module
def documentacionView(request):
    pagina = request.GET.get('pagina', PAGINA_DEFAULT)
    handler = HOJAS.get(pagina, HOJAS[PAGINA_DEFAULT])
    return handler(request)
