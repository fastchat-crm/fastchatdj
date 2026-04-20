"""
cron_jobs/aprender_conversaciones.py

Extrae pares pregunta→respuesta de conversaciones finalizadas exitosas
(sentimiento positivo o neutral, sin feedback negativo) y los registra como
FaqAgente en estado 'pendiente' para revisión humana.

Se puede ejecutar:
  - Desde el cron: `python cron_jobs/aprender_conversaciones.py` (procesa todos los agentes)
  - Desde el código: `procesar_conversaciones(agente=mi_agente)` (un solo agente)
  - Desde la UI: botón "Aprender ahora" en el modal Ver contexto (view_mientrenamiento)
"""
import os
import sys

try:
    import django
    from django.conf import settings as _settings
    _configured = bool(getattr(_settings, 'configured', False))
except Exception:
    _configured = False

if not _configured:
    # Ejecución como script: bootstrapear Django
    from django.core.wsgi import get_wsgi_application
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
    application = get_wsgi_application()

from django.db.models import Q
from django.utils import timezone

from core.funciones import logCron
from whatsapp.models import ConversacionWhatsApp, MensajeWhatsApp, PerfilContacto

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


def _actualizar_perfil_contacto(conv, ag, log_fn=None) -> bool:
    """Genera un resumen de la conversación y lo anexa al PerfilContacto.

    Devuelve True si se actualizó el perfil. Silencioso ante errores de LLM
    — el resto del ciclo sigue corriendo aunque falle.
    """
    if not conv.contacto_id or not ag:
        return False
    apikey = ag.apikey.filter(estado=True).first()
    if not apikey:
        return False
    # AgenteResumidor sólo soporta provider 2 (gemini) y 3 (openai) hoy.
    # Si es Claude (4) u otro — saltamos sin romper.
    if apikey.proveedor not in (2, 3):
        return False
    try:
        from agents_ai.agente_resumidor import AgenteResumidor
        resumidor = AgenteResumidor(
            provider=apikey.proveedor,
            apikey=apikey.descripcion,
            conversacion=conv,
            apikey_obj=apikey,
            agente_obj=ag,
        )
        resumen = (resumidor.resumir() or '').strip()
        if not resumen:
            return False
        perfil, _creado = PerfilContacto.objects.get_or_create(contacto_id=conv.contacto_id)
        fecha = conv.fecha_fin_conversacion or timezone.now()
        perfil.agregar_resumen(resumen, fecha=fecha)
        return True
    except Exception as exc:
        if log_fn:
            log_fn(f'Error actualizando PerfilContacto conv #{conv.id}: {exc}', exito=False)
        return False


def procesar_conversaciones(agente=None, limite: int = 200, log_fn=None) -> dict:
    """
    Procesa conversaciones elegibles y crea FaqAgente pendientes.

    Args:
        agente: si se pasa, procesa solo conversaciones de ese agente. None = todos.
        limite: máximo de conversaciones a procesar por corrida.
        log_fn: función opcional para loguear progreso. Default: logCron.

    Returns:
        {'procesadas': int, 'faqs_creadas': int, 'total_candidatas': int}
    """
    from crm.models import FaqAgente

    def _log(msg, exito=True):
        if log_fn:
            log_fn(msg, exito)
        else:
            logCron(PROCESO, msg, exito=exito)

    qs = ConversacionWhatsApp.objects.filter(
        Q(conversacion_finalizada=True) | Q(estado_conversacion=1),
        sentimiento__in=SENTIMIENTOS_OK,
        aprendizaje_procesado=False,
        contacto__sesion__agente_ia__isnull=False,
        contacto__sesion__status=True,
    )
    if agente is not None:
        qs = qs.filter(contacto__sesion__agente_ia=agente)

    qs = qs.select_related('contacto__sesion__agente_ia').order_by('-fecha_fin_conversacion')[:limite]
    total = qs.count()

    if total == 0:
        _log('Sin conversaciones nuevas para procesar')
        return {'procesadas': 0, 'faqs_creadas': 0, 'total_candidatas': 0}

    _log(f'{total} conversación(es) a procesar')

    procesadas = 0
    faqs_creadas = 0
    perfiles_actualizados = 0

    for conv in qs:
        ag = conv.contacto.sesion.agente_ia
        if not ag:
            conv.aprendizaje_procesado = True
            conv.save(update_fields=['aprendizaje_procesado'])
            continue

        try:
            # Actualizar memoria persistente del contacto (fase 6: memoria cruzada)
            if _actualizar_perfil_contacto(conv, ag, log_fn=_log):
                perfiles_actualizados += 1

            pares = _extraer_pares(conv)
            for pregunta, respuesta, msg_id in pares:
                existe = FaqAgente.objects.filter(
                    agente=ag, pregunta__iexact=pregunta.strip(),
                ).exists()
                if existe:
                    continue
                try:
                    msg_obj = MensajeWhatsApp.objects.get(pk=msg_id)
                except MensajeWhatsApp.DoesNotExist:
                    msg_obj = None
                FaqAgente.objects.create(
                    agente=ag,
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
                _log(f'Conv #{conv.id}: {len(pares)} FAQ(s) pendiente(s) para "{ag.nombre}"')

        except Exception as ex:
            _log(f'Error procesando conv #{conv.id}: {ex}', exito=False)

    _log(
        f'Finalizado — conversaciones: {procesadas}/{total}, '
        f'FAQs pendientes: {faqs_creadas}, perfiles actualizados: {perfiles_actualizados}'
    )
    return {
        'procesadas': procesadas,
        'faqs_creadas': faqs_creadas,
        'total_candidatas': total,
        'perfiles_actualizados': perfiles_actualizados,
    }


def run():
    """Entry point del cron — procesa todos los agentes."""
    logCron(PROCESO, 'Iniciando extracción de aprendizaje desde conversaciones')
    procesar_conversaciones(agente=None)


if __name__ == '__main__':
    run()
