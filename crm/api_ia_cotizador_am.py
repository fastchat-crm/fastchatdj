"""
crm/api_ia_cotizador_am.py

Endpoint puente que permite que un AgentesIA (HerramientaAgente) dispare la
misma función `cotizar_am` que usa el flujo determinístico (seed_cotizador_am).

Las HerramientaAgente solo permiten params planos. Esta vista los recibe,
los traduce a `variables` + `config` esperados por `cotizar_am`, le inyecta
el id_conversacion (vía header X-Conversacion-Id que mete tools_builder) y
delega a `crm.funciones_chatbot.cotizar_am`.

URL: POST /crm/api/ia/cotizador_am/
"""
import json
import logging
from types import SimpleNamespace

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from crm.funciones_chatbot import cotizar_am
from crm.models import EndpointApiChatbot
from whatsapp.models import ConversacionWhatsApp

logger = logging.getLogger(__name__)

ENDPOINT_NOMBRE_DEFAULT = 'Vida Buena — Webhook Cotizador (externo)'


@csrf_exempt
@require_POST
def cotizar_am_ia(request):
    try:
        data = json.loads(request.body or b'{}')
        if not isinstance(data, dict):
            data = {}
    except json.JSONDecodeError:
        data = {k: v for k, v in request.POST.items()}

    edad_titular = data.get('edad_titular')
    if edad_titular in (None, ''):
        return JsonResponse({
            'status': 'error',
            'message': 'Falta edad_titular para cotizar.',
        })

    conv_id_raw = (
        request.META.get('HTTP_X_CONVERSACION_ID')
        or data.get('id_conversacion')
        or ''
    )
    conversacion = None
    try:
        conv_id = int(conv_id_raw) if conv_id_raw else 0
        if conv_id:
            conversacion = ConversacionWhatsApp.objects.filter(id=conv_id).first()
    except (TypeError, ValueError):
        pass

    if conversacion is None:
        return JsonResponse({
            'status': 'error',
            'message': 'No pude identificar la conversación. Reintentá en un momento.',
        })

    variables = {
        'cedula':              (data.get('cedula') or '').strip(),
        'nombres':             (data.get('nombres') or '').strip(),
        'apellidos':           (data.get('apellidos') or '').strip(),
        'fecha_nacimiento':    (data.get('fecha_nacimiento') or '').strip(),
        'sexo_titular':        ((data.get('sexo') or '').strip().upper() or 'unknown'),
        'email':               (data.get('email') or '').strip(),
        'edad_titular':        edad_titular,
        'edades_miembros':     (data.get('edades_dependientes') or '').strip(),
        'budget_intent':       (data.get('budget_intent') or 'equilibrio').strip().lower(),
        'plan_preferido':      (data.get('plan_preferido') or '').strip(),
    }

    config = {
        'body': {
            'cliente': {
                'cedula':           '{{variables.cedula}}',
                'nombres':          '{{variables.nombres}}',
                'apellidos':        '{{variables.apellidos}}',
                'fecha_nacimiento': '{{variables.fecha_nacimiento}}',
                'sexo':             '{{variables.sexo_titular}}',
                'email':            '{{variables.email}}',
            },
            'budget_intent':         '{{variables.budget_intent}}',
            'network_preference':    'desconocido',
            'wants_max_protection':  False,
            'plan_preferido':        '{{variables.plan_preferido}}',
        },
    }

    endpoint = EndpointApiChatbot.objects.filter(nombre=ENDPOINT_NOMBRE_DEFAULT, status=True).first()
    if endpoint is None:
        return JsonResponse({
            'status': 'error',
            'message': 'No hay EndpointApiChatbot configurado para Vida Buena. Avisá al administrador.',
        })

    try:
        resultado = cotizar_am(conversacion, variables, config, endpoint=endpoint)
    except Exception as ex:
        logger.exception('cotizar_am_ia fallo: %s', ex)
        return JsonResponse({
            'status': 'error',
            'message': f'Error interno cotizando: {type(ex).__name__}.',
        })

    etiqueta = (resultado or {}).get('etiqueta', 'error')
    if etiqueta == 'ok':
        return JsonResponse({
            'status': 'ok',
            'message': (
                'Cotización enviada al motor oficial. En los próximos minutos '
                'recibís por WhatsApp y email la recomendación con tarifa '
                'exacta y los planes alternativos. 💚'
            ),
        })
    return JsonResponse({
        'status': 'error',
        'message': (resultado or {}).get('error') or 'No pudimos enviar la cotización. Reintentá en unos minutos.',
    })
