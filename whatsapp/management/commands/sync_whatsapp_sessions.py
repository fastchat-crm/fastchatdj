from django.core.management.base import BaseCommand
import redis
import json
from whatsapp.models import SesionWhatsApp
from django.utils import timezone
from datetime import timedelta
import qrcode
import base64
from io import BytesIO
from whatsapp.redis_publish import enviar_comando_close

class Command(BaseCommand):
    help = 'Sincroniza sesiones de WhatsApp con Node.js y Redis, actualiza QR, estados y elimina sesiones pendientes expiradas.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS("📡 Iniciando sincronización con Redis..."))

        r = redis.Redis(host='localhost', port=6379)
        pubsub = r.pubsub()
        pubsub.subscribe('system_alert')

        # Contador para chequeo periódico de sesiones pendientes
        last_check = timezone.now()

        for message in pubsub.listen():
            print(message)

            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    session_id = data.get('session_id')

                    if not session_id:
                        continue

                    try:
                        sesion = SesionWhatsApp.objects.get(id=session_id, status=True)
                    except SesionWhatsApp.DoesNotExist:
                        self.stdout.write(self.style.WARNING(
                            f"⚠️ Sesión {session_id} no encontrada o inactiva, ignorando evento"))
                        continue

                    # Procesar eventos solo si la sesión está en estado 'pendiente'
                    if sesion.estado == 'pendiente':
                        if data.get('event') == 'QR_CODE':
                            qr_data = data.get('qr')

                            # Convertir QR a imagen base64
                            qr_img = qrcode.make(qr_data)
                            buffer = BytesIO()
                            qr_img.save(buffer, format="PNG")
                            qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

                            sesion.qr_code = qr_base64
                            sesion.save()
                            self.stdout.write(self.style.SUCCESS(f"🔑 QR actualizado para sesión {session_id}"))

                        elif data.get('event') == 'SESSION_CONNECTED':
                            sesion.estado = 'conectado'
                            sesion.numero = data.get('number')
                            sesion.fecha_inicio_sesion = timezone.now()
                            sesion.save()
                            self.stdout.write(self.style.SUCCESS(f"✅ Sesión conectada: {sesion.numero}"))

                    elif data.get('event') == 'DISCONNECTED':
                        sesion.estado = 'desconectado'
                        sesion.save()
                        self.stdout.write(self.style.WARNING(f"⚠️ Sesión desconectada: {session_id}"))

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"❌ Error procesando mensaje: {str(e)}"))

            # === Chequeo cada 60 segundos si hay sesiones pendientes expiradas ===
            now = timezone.now()
            if (now - last_check).total_seconds() > 60:
                expiradas = SesionWhatsApp.objects.filter(
                    estado='pendiente',
                    fecha_registro__lt=now - timedelta(minutes=5),
                    status=True
                )
                for sesion in expiradas:
                    sesion.status = False
                    sesion.save()
                    enviar_comando_close(sesion.id)
                    self.stdout.write(self.style.WARNING(f"🗑️ Sesión {sesion.id} eliminada por timeout (pendiente > 5 min)"))
                last_check = now
