"""Cifrado simetrico (Fernet) para secretos en BD.

Clave derivada del SECRET_KEY de Django — mismo secreto que firma cookies.
Si el SECRET_KEY rota, los tokens cifrados ya guardados dejan de poder
descifrarse; en ese caso `decrypt_text` devuelve el valor tal cual (legacy /
fallback) para no romper el flujo y un log de warning.

Uso:
    from core.crypto import encrypt_text, decrypt_text, EncryptedTextField

    # En un model:
    access_token = EncryptedTextField(...)
    # Escrituras y lecturas son transparentes: en BD se guarda cifrado,
    # en Python se ve plaintext.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

_FERNET: Fernet | None = None


def _fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        digest = hashlib.sha256(settings.SECRET_KEY.encode('utf-8')).digest()
        key = base64.urlsafe_b64encode(digest)
        _FERNET = Fernet(key)
    return _FERNET


def _looks_fernet(value: str) -> bool:
    """Heuristica: un token Fernet empieza con 'gAAAAA' (version byte 0x80
    codificado en base64url). Evita cifrar dos veces el mismo valor."""
    return isinstance(value, str) and value.startswith('gAAAAA') and len(value) > 50


def encrypt_text(plain: str) -> str:
    if plain in (None, ''):
        return plain
    if _looks_fernet(plain):
        return plain
    return _fernet().encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt_text(cipher: str) -> str:
    if cipher in (None, ''):
        return cipher
    if not _looks_fernet(cipher):
        # Legacy / plaintext — devolver tal cual sin log (es el caso normal
        # antes de la migracion que cifra datos existentes).
        return cipher
    try:
        return _fernet().decrypt(cipher.encode('ascii')).decode('utf-8')
    except InvalidToken:
        logger.warning("decrypt_text: InvalidToken — SECRET_KEY roto? Devuelvo raw.")
        return cipher


class EncryptedTextField(models.TextField):
    """TextField que cifra transparente con Fernet en BD.

    - Escritura: `get_prep_value` cifra (idempotente — no re-cifra).
    - Lectura:   `from_db_value` descifra (tolerante — devuelve raw si no
      es un token Fernet, para soportar filas legacy sin cifrar).
    - Usar en filtros `.filter(campo=...)` NO funciona porque el cifrado
      no es determinista. Este campo es solo para secretos (tokens, keys).
    """
    description = "TextField cifrado con Fernet."

    def from_db_value(self, value, expression, connection):
        return decrypt_text(value)

    def to_python(self, value):
        # Ya llega descifrado desde from_db_value; a traves del form es plaintext.
        return value

    def get_prep_value(self, value):
        if value is None:
            return value
        return encrypt_text(str(value))
