import redis
import json
from django.conf import settings

# Cliente Redis Publisher
redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT)

# Enviar comando para iniciar sesión
def enviar_comando_start(numero):
    message = {
        "action": "start_session",
        "session_id": numero
    }
    redis_client.publish('control_channel', json.dumps(message))

# Enviar comando para cerrar sesión
def enviar_comando_close(numero):
    message = {
        "action": "close_session",
        "session_id": numero
    }
    redis_client.publish('control_channel', json.dumps(message))

# Enviar mensaje desde Django al cliente
def enviar_mensaje(numero_sesion, destino, texto):
    message = {
        "action": "send_message",
        "session_id": numero_sesion,
        "to": destino,
        "body": texto
    }
    redis_client.publish('control_channel', json.dumps(message))
