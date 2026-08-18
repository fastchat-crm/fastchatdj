"""Tests del webhook Meta: validación de firma HMAC y traducción de payload."""
import hashlib
import hmac
import json

from django.test import SimpleTestCase

from whatsapp.meta_webhook_view import (
    _extraer_phone_number_id,
    _extraer_tipo_evento,
    _meta_a_evento_interno,
    _validar_firma_hmac,
)


def _payload_mensaje(phone_number_id='123456', texto='hola'):
    return {
        'entry': [{
            'changes': [{
                'field': 'messages',
                'value': {
                    'metadata': {'phone_number_id': phone_number_id},
                    'contacts': [{'wa_id': '593999111222', 'profile': {'name': 'Ana'}}],
                    'messages': [{
                        'id': 'wamid.ABC',
                        'from': '593999111222',
                        'timestamp': '1700000000',
                        'type': 'text',
                        'text': {'body': texto},
                    }],
                },
            }],
        }],
    }


class FirmaHmacTest(SimpleTestCase):
    def test_firma_valida(self):
        secret = 'mi_app_secret'
        body = b'{"a":1}'
        firma = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(_validar_firma_hmac(body, firma, secret))

    def test_firma_invalida(self):
        self.assertFalse(_validar_firma_hmac(b'{"a":1}', 'sha256=deadbeef', 'mi_app_secret'))

    def test_sin_app_secret_es_permisivo(self):
        self.assertTrue(_validar_firma_hmac(b'x', '', ''))

    def test_con_secret_pero_sin_firma_falla(self):
        self.assertFalse(_validar_firma_hmac(b'x', '', 'mi_app_secret'))


class ExtractoresPayloadTest(SimpleTestCase):
    def test_extraer_phone_number_id(self):
        self.assertEqual(_extraer_phone_number_id(_payload_mensaje('999')), '999')

    def test_extraer_phone_number_id_ausente(self):
        self.assertIsNone(_extraer_phone_number_id({'entry': []}))

    def test_extraer_tipo_evento(self):
        self.assertEqual(_extraer_tipo_evento(_payload_mensaje()), 'messages')

    def test_extraer_tipo_evento_desconocido(self):
        self.assertEqual(_extraer_tipo_evento({}), 'unknown')


class TraduccionMensajeTextoTest(SimpleTestCase):
    def test_texto_a_shape_interno(self):
        payload = _payload_mensaje(texto='quiero info')
        value = payload['entry'][0]['changes'][0]['value']
        msg_meta = value['messages'][0]
        evento = _meta_a_evento_interno(msg_meta, value, sesion=None)
        self.assertIsNotNone(evento)
        self.assertEqual(evento['message'], {'conversation': 'quiero info'})
        self.assertEqual(evento['from'], '593999111222@s.whatsapp.net')
        self.assertEqual(evento['pushName'], 'Ana')
        self.assertFalse(evento['fromMe'])
        self.assertEqual(evento['_canal'], 'whatsapp')

    def test_from_vacio_devuelve_none(self):
        value = {'messages': [{'type': 'text', 'text': {'body': 'x'}}]}
        evento = _meta_a_evento_interno({'type': 'text', 'from': '', 'text': {'body': 'x'}}, value, sesion=None)
        self.assertIsNone(evento)
