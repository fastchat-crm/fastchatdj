"""
cron_jobs/aprender_conversaciones.py

Extrae pares pregunta→respuesta de conversaciones finalizadas exitosas
(sentimiento positivo o neutral, sin feedback negativo) y los registra como
FaqAgente en estado 'pendiente' para revisión humana.

El cliente puede aprobar/desactivar cada entrada desde el tab de
Preguntas Frecuentes del agente. Las aprobadas se inyectan en el prompt
(top-N por prioridad) y opcionalmente al FAISS.

Ejecutar: python cron_jobs/aprender_conversaciones.py
Frecuencia sugerida: una vez al día (ej. 02:00 AM)

Solo procesa conversaciones que:
  - Ya están finalizadas (conversacion_finalizada=True o estado_conversacion=1)
  - Tienen sentimiento positivo, muy_positiva o neutral
  - No han sido procesadas aún (aprendizaje_procesado=False)
  - La sesión tiene un agente_ia configurado
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from django.db.models import Q

from core.funciones import logCron
from whatsapp.models import ConversacionWhatsApp, MensajeWhatsApp

PROCESO = 'Aprendizaje desde Conversaciones'

SENTIMIENTOS_OK = {'muy_positiva', 'positiva', 'neutral'}
MIN_RESPUESTA_CHARS = 30
MAX_PARES_POR_CONV = 6


def _extraer_pares(conversacion) -> list[tuple[str, str, int]]:
    """
    Extrae tuplas (pregunta_cliente, respuesta_ia, mensaje_ia_id) de una
    conversación. Solo pares donde:
      - El mensaje IA no tiene feedback negativo
      - La respuesta tiene sustancia (>MIN_RESPUESTA_CHARS chars)
      - La pregunta del cliente tiene contenido real (>10 chars)
    """
    from crm.models import FeedbackMensajeBot

    mensajes = list(
        MensajeWhatsApp.objects
        .filter(conversacion=conversacion)
        .order_by('fecha')
        .values('id', 'remitente', 'mensaje', 'ia_generado', 'eliminado')
    )

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
            if len(texto) > 10:
                ultima_pregunta = texto
        else:
            if msg['ia_generado'] and ultima_pregunta and msg['id'] not in negativos:
                if len(texto) >= MIN_RESPUESTA_CHARS:
                    pares.append((ultima_pregunta, texto, msg['id']))
                    ultima_pregunta = None

    return pares[:MAX_PARES_POR_CONV]


def run():
    from crm.models import FaqAgente

    logCron(PROCESO, 'Iniciando extracción de aprendizaje desde conversaciones')

    conversaciones = ConversacionWhatsApp.objects.filter(
        Q(conversacion_finalizada=True) | Q(estado_conversacion=1),
        sentimiento__in=SENTIMIENTOS_OK,
        aprendizaje_procesado=False,
        contacto__sesion__agente_ia__isnull=False,
        contacto__sesion__status=True,
    ).select_related('contacto__sesion__agente_ia').order_by('-fecha_fin_conversacion')[:200]

    total = conversaciones.count()
    if total == 0:
        logCron(PROCESO, 'Sin conversaciones nuevas para procesar', exito=True)
        return

    logCron(PROCESO, f'{total} conversación(es) a procesar')

    procesadas = 0
    faqs_creadas = 0

    for conv in conversaciones:
        agente = conv.contacto.sesion.agente_ia
        if not agente:
            conv.aprendizaje_procesado = True
            conv.save(update_fields=['aprendizaje_procesado'])
            continue

        try:
            pares = _extraer_pares(conv)
            for pregunta, respuesta, msg_id in pares:
                # Evitar duplicados exactos por pregunta dentro del mismo agente
                existe = FaqAgente.objects.filter(
                    agente=agente, pregunta__iexact=pregunta.strip(),
                ).exists()
                if existe:
                    continue
                try:
                    msg_obj = MensajeWhatsApp.objects.get(pk=msg_id)
                except MensajeWhatsApp.DoesNotExist:
                    msg_obj = None
                FaqAgente.objects.create(
                    agente=agente,
                    pregunta=pregunta.strip()[:2000],
                    respuesta=respuesta.strip()[:4000],
                    origen='conversacion',
                    estado='pendiente',
                    conversacion_origen=conv,
                    mensaje_origen=msg_obj,
                )
                faqs_creadas += 1

            conv.aprendizaje_procesado = True
            conv.save(update_fields=['aprendizaje_procesado'])
            procesadas += 1

            if pares:
                logCron(
                    PROCESO,
                    f'Conv #{conv.id}: {len(pares)} FAQ(s) pendiente(s) para "{agente.nombre}"',
                    exito=True,
                )

        except Exception as ex:
            logCron(PROCESO, f'Error procesando conv #{conv.id}: {ex}', exito=False)

    logCron(
        PROCESO,
        f'Finalizado — conversaciones: {procesadas}/{total}, FAQs pendientes creadas: {faqs_creadas}',
        exito=True,
    )


if __name__ == '__main__':
    run()
