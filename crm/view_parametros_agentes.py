"""Parámetros de agentes IA — `/crm/parametros-agentes/`.

Gobierna **cómo responde** el bot a nivel plataforma: cuánto contexto recupera,
cuántos turnos recuerda, qué largo tiene la respuesta. Es el último nivel de la
cascada antes del default de código, así que un agente que no sobreescribe nada
—y cuyo perfil tampoco— toma estos valores. Ver `crm/ia_config.py`.

El control de gasto vive aparte, en `view_parametros_tokens.py`.
"""
from django.contrib.auth.decorators import login_required

from core.funciones import secure_module

from .parametros_base import render_parametros

GRUPOS = ('comportamiento_ia',)


@login_required
@secure_module
def parametros_agentes_view(request):
    return render_parametros(
        request,
        titulo='Parámetros de agentes IA',
        descripcion='Cómo responde el bot cuando ni el agente ni su perfil definen un valor propio',
        grupos=GRUPOS,
        plantilla='crm/parametros_ia/listado.html',
        extra={
            'icono': 'fa fa-robot',
            'ayuda': (
                'Estos valores son el piso de toda la plataforma. Cada agente puede '
                'sobreescribirlos desde su panel, y cada perfil desde el Centro de IA; '
                'lo que no sobreescriban, lo toman de acá.'
            ),
            'enlace_relacionado': {'url': '/crm/centro-ia/', 'texto': 'Centro de IA'},
        },
    )
