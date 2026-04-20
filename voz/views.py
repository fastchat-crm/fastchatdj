"""Vistas app voz: webhook Twilio + demo WebRTC browser."""
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


def _public_ws_host(request) -> str:
    """Host para la URL wss:// del Stream. Configurable via settings.VOZ_PUBLIC_HOST."""
    host = getattr(settings, 'VOZ_PUBLIC_HOST', '') or request.get_host()
    return host.replace('https://', '').replace('http://', '').rstrip('/')


@csrf_exempt
@require_http_methods(['POST', 'GET'])
def voice_webhook(request):
    host = _public_ws_host(request)
    ws_url = f'wss://{host}/ws/voz/twilio/'

    saludo = 'Hola, soy tu asistente de inteligencia artificial. En que te puedo ayudar?'
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="es-MX" voice="Polly.Lupe">{saludo}</Say>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="from" value="{{{{From}}}}" />
            <Parameter name="to" value="{{{{To}}}}" />
        </Stream>
    </Connect>
</Response>"""
    return HttpResponse(twiml, content_type='application/xml')


def demo_web(request):
    """Pagina demo: habla con IA desde el browser (sin telefono).

    Expone un selector de AgentesIA — el demo usa el agente elegido via query
    param `agente_id` pasado al WebSocket.
    """
    from crm.models import AgentesIA
    # Evitamos cualquier instanciacion de modelo: usamos values_list con los
    # campos planos que necesitamos y precomputamos el label en Python. En el
    # template solo iteramos tuplas primitivas (id, label) — cero chance de que
    # el resolver de Django dispare descriptores/ABC checks que recursionen.
    agentes = []
    try:
        filas = list(
            AgentesIA.objects
            .filter(status=True)
            .values_list('id', 'nombre', 'perfil__nombre_empresa')
            .order_by('nombre')
        )
        for _id, nombre, empresa in filas:
            label = (nombre or '').strip()
            if empresa:
                label = f"{label} · {empresa}"
            agentes.append({'id': _id, 'label': label})
    except Exception:
        agentes = []
    return render(request, 'voz/demo.html', {'agentes': agentes})
