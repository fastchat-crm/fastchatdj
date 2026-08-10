"""Resume las conversaciones cerradas que quedaron sin resumen.

Cadencia sugerida: 1 vez por noche, ANTES de `aprender_conversaciones.py` y de
`aprender_weaviate.py`. Es el primer eslabón de la cadena de aprendizaje.

Por qué existe: `resumir_conversacion()` corre una sola vez, al cerrar la
conversación. Si en ese momento la API del proveedor estaba caída, la key sin
saldo o el agente sin key activa, la conversación se quedaba sin resumen y sin
sentimiento — y nadie volvía a intentarlo nunca.

El efecto es en cadena y no se ve hasta que se mide:

    sin resumen  →  sin sentimiento
                 →  `aprender_conversaciones` la descarta (filtra por sentimiento)
                 →  `aprender_weaviate` no tiene qué indexar
                 →  el agente nunca aprende de lo que ya conversó

Medido antes de este cron: de 951 conversaciones cerradas, solo 68 tenían un
resumen útil y apenas 31 tenían sentimiento cargado.

Este cron busca las que quedaron con el campo vacío y reintenta. Es idempotente:
`resumir_conversacion()` no hace nada si ya hay resumen, y las conversaciones
demasiado cortas se marcan con `SIN_CONTENIDO` para no volver a mirarlas.
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from django.db.models import Count, Q

from core.funciones import logCron
from whatsapp.models import ConversacionWhatsApp

# Tope por corrida. Cada conversación cuesta una llamada al LLM, así que una
# acumulación vieja se procesa en varias noches en vez de dispararse de golpe.
MAX_POR_CORRIDA = 60


def pendientes():
    """Conversaciones cerradas, con material suficiente y sin resumen."""
    return (
        ConversacionWhatsApp.objects
        .filter(status=True, conversacion_finalizada=True,
                contacto__sesion__agente_ia__isnull=False,
                contacto__sesion__status=True)
        .filter(Q(resumen_conversacion__isnull=True) | Q(resumen_conversacion=''))
        .annotate(n_mensajes=Count('mensajes'))
        .filter(n_mensajes__gte=ConversacionWhatsApp.MIN_MENSAJES_PARA_RESUMIR)
        .select_related('contacto__sesion__agente_ia')
        .order_by('-fecha_fin_conversacion')
    )


def procesar():
    total = pendientes().count()
    resueltas = 0
    fallidas = 0

    for conv in pendientes()[:MAX_POR_CORRIDA]:
        try:
            conv.resumir_conversacion()
            conv.refresh_from_db()
            if (conv.resumen_conversacion or '').strip():
                resueltas += 1
            else:
                # `resumir_conversacion` ya dejó el motivo en el log de la app.
                fallidas += 1
        except Exception:
            fallidas += 1

    return total, resueltas, fallidas


try:
    total, resueltas, fallidas = procesar()
    if total:
        detalle = (f'{resueltas} resumida(s), {fallidas} sin resolver, '
                   f'{max(0, total - MAX_POR_CORRIDA)} en cola para la próxima corrida')
        logCron('resumir_pendientes', detalle, exito=fallidas == 0)
except Exception as ex:
    logCron('resumir_pendientes', f'Error: {ex}', exito=False)
    raise
