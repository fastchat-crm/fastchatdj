import redis
import json
from django.conf import settings
from whatsapp.models import SesionWhatsApp
from django.utils import timezone
from django.db import transaction

# Configurar cliente Redis
redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
pubsub = redis_client.pubsub()
pubsub.subscribe('system_alert')

print("📡 Escuchando eventos desde Node.js...")

def escuchar_eventos():
    for message in pubsub.listen():
        if message['type'] != 'message':
            continue

        try:
            data = json.loads(message['data'])
            session_id = data.get('session_id')  # ID de la sesión Django enviada por Node
            evento = data.get('event')

            sesion = SesionWhatsApp.objects.get(id=session_id)

            with transaction.atomic():
                if evento == "QR_CODE":
                    sesion.qr_code = data.get('qr')
                    sesion.estado = 'pendiente'
                    print(f"🔑 QR actualizado para sesión {sesion.id}")

                elif evento == "SESSION_CONNECTED":
                    sesion.estado = 'conectado'
                    sesion.numero = data.get('numero')
                    sesion.ultima_conexion = timezone.now()
                    print(f"✅ Sesión conectada: {sesion.numero}")

                elif evento == "DISCONNECTED" or evento == "AUTH_FAILURE":
                    sesion.estado = 'desconectado'
                    sesion.error_mensaje = data.get('details')
                    print(f"❌ Sesión {sesion.id} desconectada o con error")

                sesion.save()

        except Exception as e:
            print(f"❌ Error procesando evento: {e}")
