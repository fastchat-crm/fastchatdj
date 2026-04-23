"""Paginas de documentacion para los flujos de conexion.

Estilo sidebar izquierdo + breadcrumb + contenido paginado, inspirado en
la documentacion publica de Pancake.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.funciones import addData, secure_module


DOCS_SIDEBAR = [
    {
        'titulo': 'Inicio',
        'items': [
            {'nombre': 'Conectar con plataformas', 'slug': 'conectar-whatsapp-business', 'activo_default': True},
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


def _ctx_base(request, slug_actual, titulo_pagina):
    data = {
        'titulo': titulo_pagina,
        'modulo': 'Documentación',
        'ruta': request.path,
        'sidebar': DOCS_SIDEBAR,
        'slug_actual': slug_actual,
        'breadcrumb': [
            {'nombre': 'Documentación', 'url': '/whatsapp/docs/conectar-whatsapp-business/'},
            {'nombre': 'Conectar con plataformas', 'url': None},
            {'nombre': titulo_pagina, 'url': None},
        ],
    }
    addData(request, data)
    return data


@login_required
@secure_module
def docs_conectar_whatsapp_business(request):
    data = _ctx_base(
        request,
        slug_actual='conectar-whatsapp-business',
        titulo_pagina='Conectar WhatsApp Business API',
    )
    return render(request, 'whatsapp/docs/conectar_whatsapp_business.html', data)
