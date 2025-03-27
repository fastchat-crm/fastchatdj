# whatsapp/services.py
import requests
from django.conf import settings
import json

class WhatsAppService:
    def __init__(self):
        self.base_url = settings.WHATSAPP_API_URL
        self.headers = {'Content-Type': 'application/json'}

    def get_all_sessions(self):
        response = requests.get(f"{self.base_url}/sessions", headers=self.headers)
        if response.status_code == 200:
            return response.json()['sessions']
        return []

    def check_session_status(self, session_id):
        """
        Verifica si una sesión existe y su estado actual
        """
        response = requests.get(f"{self.base_url}/sessions/{session_id}/status", headers=self.headers)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {'exists': False, 'success': False}

        # Intentar obtener el mensaje de error del JSON
        try:
            error_data = response.json()
            error_message = error_data.get('error', response.text)
        except:
            error_message = response.text

        raise Exception(f"Error al verificar estado de sesión: {error_message}")

    def create_session(self, name):
        data = {'name': name}
        response = requests.post(
            f"{self.base_url}/sessions",
            headers=self.headers,
            data=json.dumps(data)
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Error creating session: {response.text}")

    def get_qr_code(self, session_id):
        response = requests.get(f"{self.base_url}/sessions/{session_id}/qr", headers=self.headers)
        if response.status_code == 200:
            return response.json().get('qrCode')
        return None

    def send_message(self, session_id, number, message, file=None):
        if file:
            # Si hay un archivo, no enviamos headers de Content-Type
            # para que requests pueda establecer el boundary correcto
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
            # Si no hay archivo, usamos JSON como antes
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

        # Intentar obtener el mensaje de error del JSON
        try:
            error_data = response.json()
            error_message = error_data.get('error', response.text)
        except:
            error_message = response.text

        raise Exception(f"Error al enviar mensaje: {error_message}")

    def delete_session(self, session_id):
        response = requests.delete(f"{self.base_url}/sessions/{session_id}", headers=self.headers)
        if response.status_code == 200:
            return True
        return False