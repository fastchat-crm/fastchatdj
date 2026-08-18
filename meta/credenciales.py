"""Lectura de credenciales Meta desde la BD (singleton CredencialMetaApp)
con fallback a settings (credenciales.json).

Movido desde `whatsapp/common_meta.py` (que ahora re-exporta de acá para
no romper imports legacy).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_meta_app_credentials():
    """Devuelve `(app_id, app_secret)` de la Meta App de la organización.

    Lee desde `CredencialMetaApp` (singleton via OneToOne con `Configuracion`).
    Fallback a `settings.META_APP_ID` / `META_APP_SECRET` si no hay registro
    aún (permite bootstrap antes de que el admin llene el form).
    """
    from django.conf import settings
    try:
        from seguridad.models import Configuracion, CredencialMetaApp
        confi = Configuracion.get_instancia()
        if confi and confi.pk:
            cred = CredencialMetaApp.objects.filter(configuracion=confi).first()
            if cred and cred.app_id:
                return cred.app_id, (cred.app_secret or '')
    except Exception as ex:
        logger.debug("CredencialMetaApp no disponible: %s", ex)
    return (
        getattr(settings, 'META_APP_ID', '') or '',
        getattr(settings, 'META_APP_SECRET', '') or '',
    )


def get_meta_app_secret() -> str:
    """Shortcut: solo el `app_secret`, para firmar/validar HMAC."""
    return get_meta_app_credentials()[1]


def get_meta_app_secrets() -> list:
    """Todos los app_secrets aceptados para validar HMAC de webhooks.

    Necesario cuando la instalación usa más de una Meta App (ej. una app para
    WhatsApp Cloud y otra para Messenger/Instagram): cada app firma sus
    webhooks con su propio secret y con uno solo el resto se rechazaba como
    firma inválida. Fuentes, en orden:
      1. `CredencialMetaApp.app_secret` (principal, UI /seguridad/credencial-meta/).
      2. `CredencialMetaApp.app_secrets_extra` (uno por línea o coma, misma UI).
      3. `META_APP_SECRETS_EXTRA` de credenciales.json (fallback/bootstrap).
    """
    from django.conf import settings
    secretos = [get_meta_app_secret()]
    try:
        from seguridad.models import Configuracion, CredencialMetaApp
        confi = Configuracion.get_instancia()
        if confi and confi.pk:
            cred = CredencialMetaApp.objects.filter(configuracion=confi).first()
            crudo = (getattr(cred, 'app_secrets_extra', '') or '') if cred else ''
            for linea in crudo.replace(',', '\n').splitlines():
                secretos.append(linea)
    except Exception as ex:
        logger.debug("app_secrets_extra no disponible: %s", ex)
    extra = getattr(settings, 'META_APP_SECRETS_EXTRA', []) or []
    if isinstance(extra, str):
        extra = [extra]
    secretos.extend(extra)
    vistos, unicos = set(), []
    for s in secretos:
        s = (s or '').strip()
        if s and s not in vistos:
            vistos.add(s)
            unicos.append(s)
    return unicos


def get_meta_config_id() -> str:
    """Devuelve el `config_id` del Embedded Signup de WhatsApp Business.

    Prioriza `CredencialMetaApp.config_id` (BD); si no hay, cae a
    `settings.META_CONFIG_ID` (credenciales.json) — esto permite bootstrap
    antes de que el admin lo cargue desde la UI.
    """
    from django.conf import settings
    try:
        from seguridad.models import Configuracion, CredencialMetaApp
        confi = Configuracion.get_instancia()
        if confi and confi.pk:
            cred = CredencialMetaApp.objects.filter(configuracion=confi).first()
            if cred and cred.config_id:
                return cred.config_id
    except Exception as ex:
        logger.debug("CredencialMetaApp no disponible: %s", ex)
    return getattr(settings, 'META_CONFIG_ID', '') or ''
