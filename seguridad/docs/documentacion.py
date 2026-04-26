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
            {'nombre': 'Conectar con plataformas', 'slug': 'conectar-whatsapp-business'},
        ],
    },
    {
        'titulo': 'Gestión de conversaciones',
        'items': [],
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
        ],
    },
    {
        'titulo': 'Para desarrolladores',
        'items': [],
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


HOJAS = {
    'plataforma': _hoja_plataforma,
    'conectar-whatsapp-business': _hoja_conectar_whatsapp_business,
}


@login_required
@secure_module
def documentacionView(request):
    pagina = request.GET.get('pagina', PAGINA_DEFAULT)
    handler = HOJAS.get(pagina, HOJAS[PAGINA_DEFAULT])
    return handler(request)
