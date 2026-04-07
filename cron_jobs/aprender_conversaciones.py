"""
cron_jobs/aprender_conversaciones.py

Extrae pares pregunta→respuesta de conversaciones finalizadas exitosas
(sentimiento positivo o neutral, sin feedback negativo) y los agrega al
vectorstore del agente IA correspondiente como conocimiento implícito.

Ejecutar: python cron_jobs/aprender_conversaciones.py
Frecuencia sugerida: una vez al día (ej. 02:00 AM)

Solo procesa conversaciones que:
  - Ya están finalizadas (conversacion_finalizada=True o estado_conversacion=1)
  - Tienen sentimiento positivo, muy_positiva o neutral
  - No han sido procesadas aún (aprendizaje_procesado=False)
  - El agente IA tiene vectorstore configurado y apikey activa
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from django.conf import settings
from django.db.models import Q

from core.funciones import logCron
from whatsapp.models import ConversacionWhatsApp, MensajeWhatsApp

PROCESO = 'Aprendizaje desde Conversaciones'

# Sentimientos que indican una interacción exitosa digna de aprender
SENTIMIENTOS_OK = {'muy_positiva', 'positiva', 'neutral'}

# Longitud mínima de una respuesta IA para considerarla útil
MIN_RESPUESTA_CHARS = 30

# Máximo de pares por conversación para no saturar el vectorstore
MAX_PARES_POR_CONV = 6


def _extraer_pares(conversacion) -> list[tuple[str, str]]:
    """
    Extrae pares (pregunta_cliente, respuesta_ia) de una conversación.
    Solo incluye intercambios donde:
      - El mensaje IA no tiene feedback negativo asociado
      - La respuesta tiene sustancia (>MIN_RESPUESTA_CHARS chars)
      - La pregunta del cliente tiene contenido real (>10 chars, no es saludo/ack)
    """
    from crm.models import FeedbackMensajeBot

    mensajes = list(
        MensajeWhatsApp.objects
        .filter(conversacion=conversacion)
        .order_by('fecha')
        .values('id', 'remitente', 'mensaje', 'ia_generado', 'eliminado')
    )

    # IDs con feedback negativo — excluirlos
    negativos = set(
        FeedbackMensajeBot.objects
        .filter(mensaje__conversacion=conversacion, es_correcto=False)
        .values_list('mensaje_id', flat=True)
    )

    sesion_numero = conversacion.sesion.numero if conversacion.sesion else None
    pares = []
    ultima_pregunta = None

    for msg in mensajes:
        if msg['eliminado'] or not msg['mensaje']:
            continue
        texto = msg['mensaje'].strip()
        if not texto:
            continue

        if msg['remitente'] != sesion_numero:
            # Mensaje del cliente
            if len(texto) > 10:
                ultima_pregunta = texto
        else:
            # Mensaje de salida (IA o agente)
            if msg['ia_generado'] and ultima_pregunta and msg['id'] not in negativos:
                if len(texto) >= MIN_RESPUESTA_CHARS:
                    pares.append((ultima_pregunta, texto))
                    ultima_pregunta = None  # consumida

    return pares[:MAX_PARES_POR_CONV]


def run():
    logCron(PROCESO, 'Iniciando extracción de aprendizaje desde conversaciones')

    # Conversaciones finalizadas exitosas no procesadas aún
    conversaciones = ConversacionWhatsApp.objects.filter(
        Q(conversacion_finalizada=True) | Q(estado_conversacion=1),
        sentimiento__in=SENTIMIENTOS_OK,
        aprendizaje_procesado=False,
        contacto__sesion__agente_ia__isnull=False,
        contacto__sesion__status=True,
    ).select_related(
        'contacto__sesion__agente_ia',
    ).order_by('-fecha_fin_conversacion')[:200]  # procesar de a 200 por corrida

    total = conversaciones.count()
    if total == 0:
        logCron(PROCESO, 'Sin conversaciones nuevas para procesar', exito=True)
        return

    logCron(PROCESO, f'{total} conversación(es) a procesar')

    from agents_ai.vectorstore_manager import VectorStoreManager
    from agents_ai.agente_consultor import invalidate_vectorstore_cache

    procesadas = 0
    pares_total = 0

    for conv in conversaciones:
        agente = conv.contacto.sesion.agente_ia
        if not agente.vectorstore_path:
            conv.aprendizaje_procesado = True
            conv.save(update_fields=['aprendizaje_procesado'])
            continue

        apikey_obj = agente.apikey.filter(estado=True).first()
        if not apikey_obj:
            continue

        provider = {2: 'gemini', 3: 'openai'}.get(apikey_obj.proveedor, 'gemini')
        vs_path = os.path.join(settings.MEDIA_ROOT, agente.vectorstore_path)
        storage = os.path.join(settings.MEDIA_ROOT, 'vectorstores')

        try:
            pares = _extraer_pares(conv)
            if pares:
                vsm = VectorStoreManager(storage, provider, apikey_obj.descripcion)
                for pregunta, respuesta in pares:
                    vsm.add_correction(vs_path, pregunta, respuesta)
                    pares_total += 1
                invalidate_vectorstore_cache(vs_path)
                logCron(
                    PROCESO,
                    f'Conv #{conv.id}: {len(pares)} par(es) agregado(s) al vectorstore "{agente.nombre}"',
                    exito=True,
                )

            conv.aprendizaje_procesado = True
            conv.save(update_fields=['aprendizaje_procesado'])
            procesadas += 1

        except Exception as ex:
            logCron(PROCESO, f'Error procesando conv #{conv.id}: {ex}', exito=False)

    logCron(
        PROCESO,
        f'Finalizado — conversaciones: {procesadas}/{total}, pares embebidos: {pares_total}',
        exito=True,
    )


if __name__ == '__main__':
    run()
