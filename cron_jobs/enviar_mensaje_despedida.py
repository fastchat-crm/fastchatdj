"""
cron_jobs/enviar_mensaje_despedida.py

Cierra conversaciones que han superado su tiempo de expiración (fecha_hora_expira < now).

Lógica de cierre por prioridad:
  1. Si la sesión / agente tiene ReglaFinConversacion activa → ejecutar_acciones_fin()
  2. Fallback: si la sesión tiene mensaje_despedida antiguo configurado → enviarlo directamente
  3. Si el agente humano está asignado a la conversación → NO cerrar automáticamente
  4. Siempre: resumir_conversacion() (sentimiento + resumen) y guardar fecha_fin / duración
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from django.utils import timezone

from core.funciones import logCron
from crm.acciones_fin import ejecutar_acciones_fin
from crm.models import ReglaFinConversacion
from whatsapp.models import ConversacionWhatsApp
from whatsapp.services import WhatsAppService

PROCESO = 'Cierre Automático de Conversaciones'


def _contexto_fin(conversacion) -> dict:
    sesion = conversacion.contacto.sesion
    agente = getattr(sesion, 'agente_ia', None)
    return {
        'nombre_contacto': conversacion.contacto.contacto_nombre or conversacion.contacto.from_number,
        'numero': conversacion.contacto.from_number,
        'sesion': sesion.nombre if hasattr(sesion, 'nombre') else str(sesion),
        'sesion_id': sesion.session_id,
        'resumen': conversacion.resumen_conversacion or '',
        'agente': agente.nombre if agente else '',
    }


def _cerrar_conversacion(conversacion, whatsapp_service: WhatsAppService) -> None:
    sesion = conversacion.contacto.sesion
    agente = getattr(sesion, 'agente_ia', None)

    # ── 1. No cerrar si hay agente humano asignado ───────────────────────
    if conversacion.asignado_a_id:
        logCron(
            PROCESO,
            f'Conversación #{conversacion.id} omitida — asignada a agente humano ({conversacion.asignado_a})',
            exito=True,
        )
        return

    # ── 2. Resumir y analizar sentimiento ANTES de ejecutar acciones ─────
    conversacion.resumir_conversacion()

    # ── 3. Registrar fechas de cierre ────────────────────────────────────
    ahora = timezone.now()
    conversacion.fecha_fin_conversacion = ahora
    if conversacion.fecha_registro:
        conversacion.duracion_conversacion = ahora - conversacion.fecha_registro

    # ── 4. Intentar con ReglaFinConversacion (nuevo sistema) ─────────────
    regla = ReglaFinConversacion.para_sesion(sesion)
    if regla:
        contexto = _contexto_fin(conversacion)
        ejecutar_acciones_fin(regla, contexto)
        logCron(
            PROCESO,
            f'Conversación #{conversacion.id} cerrada por expiración — acciones ReglaFin ejecutadas',
            exito=True,
        )

    # ── 5. Fallback: mensaje_despedida clásico (solo si no hay regla) ─────
    elif getattr(sesion, 'mensaje_despedida', None):
        from_number = conversacion.contacto.from_number
        try:
            whatsapp_service.send_text_message(
                sesion.session_id,
                from_number,
                sesion.mensaje_despedida,
                conversacion_id=conversacion.id,
                simularEscritura=True,
            )
            logCron(
                PROCESO,
                f'Conversación #{conversacion.id} cerrada — mensaje_despedida clásico enviado a {from_number}',
                exito=True,
            )
        except Exception as e:
            logCron(PROCESO, f'Conversación #{conversacion.id} — error enviando despedida clásica: {e}', exito=False)
    else:
        logCron(
            PROCESO,
            f'Conversación #{conversacion.id} cerrada por expiración — sin mensaje configurado',
            exito=True,
        )

    # ── 6. Marcar como finalizada ────────────────────────────────────────
    conversacion.despedida_enviado = True
    conversacion.conversacion_finalizada = True
    # resumir_conversacion() ya guardó resumen/sentimiento; aquí solo los campos de cierre
    conversacion.save(update_fields=[
        'despedida_enviado',
        'conversacion_finalizada',
        'fecha_fin_conversacion',
        'duracion_conversacion',
    ])


# ── Main ─────────────────────────────────────────────────────────────────────

# Solo conversaciones expiradas por tiempo real (fecha_hora_expira < now),
# no por estado ni por conversacion_finalizada — esos son otros flujos.
conversaciones = ConversacionWhatsApp.objects.filter(
    despedida_enviado=False,
    conversacion_finalizada=False,
    fecha_hora_expira__lt=timezone.now(),
).select_related(
    'contacto',
    'contacto__sesion',
    'contacto__sesion__agente_ia',
    'asignado_a',
)

whatsapp_service = WhatsAppService()
total = conversaciones.count()

if total == 0:
    logCron(PROCESO, 'Sin conversaciones expiradas pendientes de cerrar', exito=True)
else:
    logCron(PROCESO, f'Procesando {total} conversación(es) expirada(s)', exito=True)
    for conversacion in conversaciones:
        try:
            _cerrar_conversacion(conversacion, whatsapp_service)
        except Exception as e:
            logCron(
                PROCESO,
                f'Error al cerrar conversación #{conversacion.id}: {e}',
                exito=False,
            )
