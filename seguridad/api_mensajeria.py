from django.http import JsonResponse
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

from whatsapp.models import SesionWhatsApp, Contacto, ConversacionWhatsApp, MensajeWhatsApp
from whatsapp.services import WhatsAppService


def enviar_mensaje_view(request):
    """
    Endpoint GET para enviar un mensaje de texto por WhatsApp.
    Ejemplo:
        /api/enviar-mensaje/?idSesion=1&numero=593987654321&mensaje=Hola
    """
    try:
        idSesion = request.GET.get("idSesion")
        numero = request.GET.get("numero")
        mensaje = request.GET.get("mensaje")

        # --- Validaciones iniciales ---
        if not all([idSesion, numero, mensaje]):
            return JsonResponse(
                {"status": "error", "message": "Debe proporcionar idSesion, numero y mensaje."},
                status=400
            )

        with transaction.atomic():
            # --- Validación de sesión activa ---
            try:
                sesion = SesionWhatsApp.objects.get(pk=idSesion, status=True)
            except ObjectDoesNotExist:
                return JsonResponse(
                    {"status": "error", "message": "Sesión no encontrada o inactiva."},
                    status=404
                )

            # --- Validación de contacto existente ---
            contacto = Contacto.objects.filter(
                status=True, sesion=sesion, contacto_numero=numero
            ).first()
            if not contacto:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": f"No existe un contacto activo con {numero}. "
                                   f"Inicie primero una conversación antes de enviar mensajes."
                    },
                    status=400
                )

            # --- Obtiene o crea la conversación ---
            conversacion, _ = ConversacionWhatsApp.objects.get_or_create(
                status=True,
                contacto=contacto,
                defaults={"status": True}
            )

            # --- Envío del mensaje ---
            service = WhatsAppService()
            response = service.send_text_message(
                conversacion.sesion.session_id, conversacion.from_number, mensaje
            )

            if not response.get("success"):
                return JsonResponse(
                    {"status": "error", "message": f"Error al enviar mensaje: {response.get('error', 'Desconocido')}"},
                    status=400
                )

            # --- Registro del mensaje enviado ---
            MensajeWhatsApp.objects.create(
                mensaje_id_externo=response.get("message_id"),
                conversacion=conversacion,
                remitente=conversacion.sesion.numero,
                mensaje=mensaje,
                tipo="texto",
                archivo_url=None,
                fecha=timezone.now(),
                leido=True,
                fecha_leido=timezone.now(),
            )

            return JsonResponse(
                {
                    "status": "success",
                    "message": f"Mensaje enviado correctamente a {numero}",
                    "data": response
                },
                status=200
            )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)