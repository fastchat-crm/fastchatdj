"""Tokens y límites de IA — `/crm/parametros-tokens/`.

Gobierna **cuánto puede gastar** la plataforma: topes de tokens por día y por
mes, anti-ráfaga por conversación y aviso de saldo bajo. Un `0` significa sin
tope, que es el valor con el que se siembra: activar un límite es una decisión
explícita, no algo que aparezca solo tras un deploy.

Está separada de los parámetros de comportamiento (`view_parametros_agentes.py`)
porque son decisiones de distinta naturaleza y suelen tomarlas personas
distintas: con dos módulos se le puede dar a cada rol solo lo suyo.
"""
from django.contrib.auth.decorators import login_required

from core.funciones import secure_module

from .parametros_base import render_parametros

GRUPOS = ('limites',)


@login_required
@secure_module
def parametros_tokens_view(request):
    return render_parametros(
        request,
        titulo='Tokens y límites de IA',
        descripcion='Topes de consumo, anti-ráfaga y aviso de saldo bajo',
        grupos=GRUPOS,
        plantilla='crm/parametros_ia/listado.html',
        extra={
            'icono': 'fa fa-gauge-high',
            'ayuda': (
                'Un 0 significa sin tope. Los topes se evalúan sobre el consumo de toda '
                'la plataforma; el detalle por agente y conversación está en el panel de '
                'consumo.'
            ),
            'enlace_relacionado': {'url': '/crm/entrenamiento/', 'texto': 'Consumo por agente'},
        },
    )
