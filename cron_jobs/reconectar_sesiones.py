"""
cron_jobs/reconectar_sesiones.py

Reconecta automáticamente sesiones de WhatsApp que se desconectaron
de forma inesperada (ej. caída del servidor Node.js, pérdida de red).

Condiciones para intentar reconectar:
  - status=True (sesión activa en Django)
  - estado='desconectado' o 'error'
  - desconectado_manualmente=False  (el usuario NO la apagó a propósito)

Se ejecuta cada 5 minutos mediante cron / task scheduler.
"""
import os
import sys

from django.core.wsgi import get_wsgi_application

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()

from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from core.funciones import logCron
from whatsapp.models import SesionWhatsApp
from whatsapp.services import WhatsAppService

PROCESO = 'Reconexión Automática de Sesiones'

# URL del webhook Django para que el servidor Node.js envíe eventos
WEBHOOK_URL = settings.URL_GENERAL + '/whatsapp/webhook_handler/'

# Esperar al menos 2 minutos entre intentos de reconexión para la misma sesión
MIN_MINUTOS_ENTRE_INTENTOS = 2


def run():
    logCron(PROCESO, f'Iniciando — webhook destino: {WEBHOOK_URL}')

    sesiones = SesionWhatsApp.objects.filter(
        status=True,
        estado__in=['desconectado', 'error'],
        desconectado_manualmente=False,
    ).select_related('usuario')

    if not sesiones.exists():
        logCron(PROCESO, 'Sin sesiones desconectadas inesperadamente', exito=True)
        return

    service = WhatsAppService()
    reconectadas = 0
    fallidas = 0

    for sesion in sesiones:
        nombre = sesion.nombre or sesion.numero or sesion.session_id
        try:
            logCron(PROCESO, f'Intentando reconectar sesión {sesion.id} ({nombre})')
            result = service.create_session(sesion, WEBHOOK_URL)

            if result.get('success'):
                # La sesión fue enviada al servidor Node. El estado pasará a 'conectado'
                # cuando el webhook 'ready' o 'authenticated' llegue.
                # Por ahora la marcamos 'pendiente' para evitar reconexiones repetidas.
                sesion.estado = 'pendiente'
                sesion.error_mensaje = None
                if result.get('qr_code'):
                    sesion.qr_code = result['qr_code']
                sesion.save(update_fields=['estado', 'error_mensaje', 'qr_code'])
                reconectadas += 1
                logCron(PROCESO, f'Sesión {sesion.id} ({nombre}) enviada al servidor Node — esperando QR/ready', exito=True)

                # Notificar al usuario si hay QR (necesita escanear)
                if result.get('qr_code') and sesion.usuario:
                    try:
                        from seguridad.models import Notificacion
                        Notificacion.objects.create(
                            usuario=sesion.usuario,
                            titulo=f'Sesión "{nombre}" requiere escaneo de QR',
                            mensaje=(
                                f'La sesión <strong>{nombre}</strong> fue reconectada automáticamente '
                                f'pero necesita que escanees el código QR nuevamente.'
                            ),
                            url='/whatsapp/sesiones/',
                            prioridad=1,
                            tipo=4,
                        )
                    except Exception:
                        pass
            else:
                fallidas += 1
                error = result.get('error') or result.get('message') or 'Error desconocido'
                logCron(PROCESO, f'Sesión {sesion.id} ({nombre}) — fallo al reconectar: {error}', exito=False)

                # Notificar al usuario del fallo
                if sesion.usuario:
                    try:
                        from seguridad.models import Notificacion
                        hace_una_hora = timezone.now() - timedelta(hours=1)
                        ya_notificado = Notificacion.objects.filter(
                            usuario=sesion.usuario,
                            titulo__icontains=nombre,
                            fecha_creacion__gte=hace_una_hora,
                        ).exists()
                        if not ya_notificado:
                            Notificacion.objects.create(
                                usuario=sesion.usuario,
                                titulo=f'No se pudo reconectar la sesión "{nombre}"',
                                mensaje=(
                                    f'La sesión <strong>{nombre}</strong> sigue desconectada '
                                    f'y no pudo reconectarse automáticamente. '
                                    f'Ingresa al panel de sesiones para reconectarla manualmente.'
                                ),
                                url='/whatsapp/sesiones/',
                                prioridad=1,
                                tipo=4,
                            )
                    except Exception:
                        pass

        except Exception as ex:
            fallidas += 1
            logCron(PROCESO, f'Error inesperado reconectando sesión {sesion.id}: {ex}', exito=False)

    logCron(PROCESO, f'Finalizado — reconectadas: {reconectadas}, fallidas: {fallidas}', exito=True)


if __name__ == '__main__':
    run()
