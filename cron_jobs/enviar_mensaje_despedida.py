"""
cron_jobs/enviar_mensaje_despedida.py

Cierra conversaciones en dos modos:

1. EXPIRACIÓN CLÁSICA (sesiones con min_sesion > 0): fecha_hora_expira < now
   → cierra CON despedida, como siempre.
2. CIERRE HIGIÉNICO (sesiones con min_sesion = 0, fecha_hora_expira = None):
   la conversación solo la termina el asesor, pero tras N días sin mensajes
   (Configuracion.dias_cierre_higienico, default 3; 0 = nunca) se cierra SIN
   despedida — así corren el resumen, el sentimiento y las reglas de fin, y el
   inbox no acumula conversaciones zombie.

La lógica de cierre vive en ConversacionWhatsApp.cerrar() — aquí sólo se
seleccionan las candidatas y se delega el cierre con los flags del cron.
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from datetime import timedelta

from django.db.models import Max, Q
from django.utils import timezone

from core.funciones import logCron
from whatsapp.models import ConversacionWhatsApp

PROCESO = 'Cierre Automático de Conversaciones'

_SELECT_RELATED = (
    'contacto',
    'contacto__sesion',
    'contacto__sesion__agente_ia',
    'asignado_a',
)


def _cerrar_lote(conversaciones, motivo, enviar_despedida, respetar_asignacion=True):
    cerradas = 0
    for conversacion in conversaciones:
        try:
            cerrada = conversacion.cerrar(
                enviar_despedida=enviar_despedida,
                respetar_asignacion_humana=respetar_asignacion,
                respetar_bloqueo_cierre=True,
            )
            if cerrada:
                cerradas += 1
                logCron(PROCESO, f'Conversación #{conversacion.id} cerrada por {motivo}', exito=True)
            else:
                logCron(
                    PROCESO,
                    f'Conversación #{conversacion.id} omitida (asignada a humano, bloqueada o ya cerrada)',
                    exito=True,
                )
        except Exception as e:
            logCron(PROCESO, f'Error al cerrar conversación #{conversacion.id}: {e}', exito=False)
    return cerradas


# ── 1. Expiración clásica (min_sesion > 0) ─────────────────────────────
expiradas = ConversacionWhatsApp.objects.filter(
    despedida_enviado=False,
    conversacion_finalizada=False,
    fecha_hora_expira__lt=timezone.now(),
    contacto__sesion__activo=True,
).select_related(*_SELECT_RELATED)

total_exp = expiradas.count()
if total_exp:
    logCron(PROCESO, f'Procesando {total_exp} conversación(es) expirada(s)', exito=True)
    _cerrar_lote(expiradas, 'expiración', enviar_despedida=True)

# ── 2. Cierre higiénico (min_sesion = 0 → fecha_hora_expira = None) ────
from seguridad.models import Configuracion

_confi = Configuracion.get_instancia()
_dias = int(getattr(_confi, 'dias_cierre_higienico', 3) or 0)

total_hig = 0
if _dias > 0:
    _limite = timezone.now() - timedelta(days=_dias)
    higienicas = (
        ConversacionWhatsApp.objects.filter(
            conversacion_finalizada=False,
            estado_conversacion=0,
            fecha_hora_expira__isnull=True,
            contacto__sesion__activo=True,
            status=True,
        )
        .annotate(ultimo_msg=Max('mensajes__fecha'))
        .filter(
            Q(ultimo_msg__lt=_limite)
            | Q(ultimo_msg__isnull=True, fecha_registro__lt=_limite)
        )
        .select_related(*_SELECT_RELATED)
    )
    total_hig = higienicas.count()
    if total_hig:
        logCron(
            PROCESO,
            f'Cierre higiénico: {total_hig} conversación(es) con más de {_dias} día(s) sin mensajes',
            exito=True,
        )
        _cerrar_lote(higienicas, f'inactividad de {_dias} día(s) (higiénico, sin despedida)',
                     enviar_despedida=False, respetar_asignacion=False)

if not total_exp and not total_hig:
    logCron(PROCESO, 'Sin conversaciones pendientes de cerrar', exito=True)
