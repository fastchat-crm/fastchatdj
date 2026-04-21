"""
crm/acciones_fin.py

Ejecuta las acciones configuradas en AccionFinConversacion cuando el agente
detecta que una conversación ha llegado a su fin.
"""
import logging

import requests
from django.conf import settings

from core.correos_background import enviar_correo_html

logger = logging.getLogger(__name__)


def ejecutar_acciones_fin(regla, contexto: dict) -> None:
    """
    Recorre todas las AccionFinConversacion activas de `regla` y las ejecuta.

    contexto esperado:
        nombre_contacto  — nombre del contacto (str)
        numero           — número de teléfono del contacto (str)
        sesion           — nombre o ID de la sesión WhatsApp (str)
        sesion_id        — session_id técnico para enviar por WA (str)
        resumen          — resumen de la conversación (str, puede estar vacío)
        agente           — nombre del agente IA (str)
    """
    for accion in regla.acciones.filter(status=True):
        try:
            mensaje = accion.render_mensaje(contexto)
            if accion.tipo == 'email' and accion.destino:
                _enviar_email(accion.destino, mensaje, contexto)
            elif accion.tipo == 'whatsapp' and accion.destino:
                _enviar_whatsapp(accion.destino, mensaje, contexto)
            elif accion.tipo == 'webhook' and accion.destino:
                _llamar_webhook(accion.destino, contexto)
            # 'ninguna' → solo se marcó la conversación; nada más que hacer
        except Exception:
            logger.exception("Error ejecutando AccionFinConversacion id=%s tipo=%s", accion.id, accion.tipo)


# ---------------------------------------------------------------------------
# Ejecutores internos
# ---------------------------------------------------------------------------

def _enviar_email(destinatario: str, mensaje: str, contexto: dict) -> None:
    nombre = contexto.get('nombre_contacto') or contexto.get('numero') or 'Contacto'
    asunto = f"Conversación finalizada — {nombre}"
    html = "<p>" + mensaje.replace("\n", "<br>") + "</p>"
    datos = {
        'subject': asunto,
        'plain_message': mensaje,
        'from_email': settings.DEFAULT_FROM_EMAIL,
        'to': [destinatario],
        'html_message': html,
    }
    enviar_correo_html(datos)
    logger.info("Email de fin enviado a %s", destinatario)


def _enviar_whatsapp(numero_destino: str, mensaje: str, contexto: dict) -> None:
    from whatsapp.services import get_whatsapp_service
    from whatsapp.models import SesionWhatsApp
    sesion_id = contexto.get('sesion_id')
    if not sesion_id:
        logger.warning("AccionFinConversacion whatsapp: no hay sesion_id en contexto, se omite.")
        return
    sesion = SesionWhatsApp.objects.filter(session_id=sesion_id).first()
    numero_fmt = numero_destino.strip().lstrip('+')
    to = f"{numero_fmt}@s.whatsapp.net" if '@' not in numero_fmt else numero_fmt
    resultado = get_whatsapp_service(sesion).send_text_message(sesion_id, to, mensaje)
    if not resultado or not resultado.get('success'):
        logger.warning(
            "AccionFinConversacion whatsapp FALLO a %s vía sesión %s: %s",
            numero_destino, sesion_id, (resultado or {}).get('error', 'respuesta vacia'),
        )
        return
    logger.info("Mensaje WA de fin enviado a %s vía sesión %s", numero_destino, sesion_id)


def _llamar_webhook(url: str, contexto: dict) -> None:
    resp = requests.post(url, json=contexto, timeout=10)
    logger.info("Webhook fin llamado: %s → HTTP %s", url, resp.status_code)
