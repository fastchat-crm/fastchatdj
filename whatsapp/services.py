# whatsapp/services.py (adaptado a tus modelos)
import requests
from django.conf import settings
import json
from django.utils import timezone

class WhatsAppService:
    def __init__(self):
        self.base_url = settings.WHATSAPP_API_URL
        self.headers = {'Content-Type': 'application/json'}

    def get_all_sessions(self):
        response = requests.get(f"{self.base_url}/sessions", headers=self.headers)
        if response.status_code == 200:
            return response.json()['sessions']
        return []

    def create_session_with_webhooks(self, numero, webhooks):
        """
        Crea una nueva sesión con webhooks
        """
        data = {
            'name': numero,  # Usamos el número como nombre
            'webhooks': webhooks
        }
        response = requests.post(
            f"{self.base_url}/sessions",
            headers=self.headers,
            data=json.dumps(data)
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Error al crear sesión: {response.text}")

    def register_webhooks(self, session_id, webhooks):
        """
        Registra webhooks para una sesión existente
        """
        data = {
            'webhooks': webhooks
        }
        response = requests.post(
            f"{self.base_url}/sessions/{session_id}/webhooks",
            headers=self.headers,
            data=json.dumps(data)
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Error al registrar webhooks: {response.text}")

    def get_qr_code(self, session_id):
        response = requests.get(f"{self.base_url}/sessions/{session_id}/qr", headers=self.headers)
        if response.status_code == 200:
            return response.json().get('qrCode')
        return None

    def check_session_status(self, session_id):
        """
        Verifica si una sesión existe y su estado actual
        """
        response = requests.get(f"{self.base_url}/sessions/{session_id}/status", headers=self.headers)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {'exists': False, 'success': False}

        try:
            error_data = response.json()
            error_message = error_data.get('error', response.text)
        except:
            error_message = response.text

        raise Exception(f"Error al verificar estado de sesión: {error_message}")

    def send_message(self, session_id, number, message, file=None):
        """
        Envía un mensaje a través de WhatsApp
        """
        if file:
            # Si hay un archivo, no enviamos headers de Content-Type
            data = {
                'number': number,
                'message': message
            }
            files = {'file': (file.name, file, file.content_type)}

            response = requests.post(
                f"{self.base_url}/sessions/{session_id}/send",
                data=data,
                files=files
            )
        else:
            # Si no hay archivo, usamos JSON
            data = {
                'number': number,
                'message': message
            }
            response = requests.post(
                f"{self.base_url}/sessions/{session_id}/send",
                headers=self.headers,
                data=json.dumps(data)
            )

        if response.status_code == 200:
            return response.json()

        try:
            error_data = response.json()
            error_message = error_data.get('error', response.text)
        except:
            error_message = response.text

        raise Exception(f"Error al enviar mensaje: {error_message}")

    def get_conversations(self, session_id, limit=50, offset=0, jid=None):
        """
        Obtiene las conversaciones de una sesión
        """
        params = {
            'limit': limit,
            'offset': offset
        }

        if jid:
            params['jid'] = jid

        response = requests.get(
            f"{self.base_url}/sessions/{session_id}/conversations",
            headers=self.headers,
            params=params
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Error al obtener conversaciones: {response.text}")

    def delete_session(self, session_id):
        """
        Elimina una sesión
        """
        response = requests.delete(f"{self.base_url}/sessions/{session_id}", headers=self.headers)
        if response.status_code == 200:
            return True
        return False