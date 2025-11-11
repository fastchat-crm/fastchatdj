from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist

from whatsapp.models import SesionWhatsApp, Contacto, ConversacionWhatsApp, MensajeWhatsApp
from whatsapp.services import WhatsAppService


@api_view(['GET'])
def enviar_mensaje_api(request):
    """
    Endpoint REST (GET) para enviar un mensaje de texto por WhatsApp.
    Ejemplo:
        /api/enviar-mensaje/?idSesion=1&numero=+593987654321&mensaje=Hola
    """
    idSesion = request.GET.get('idSesion')
    numero = request.GET.get('numero')
    mensaje = request.GET.get('mensaje')

    try:
        # --- Validaciones iniciales ---
        if not all([idSesion, numero, mensaje]):
            return Response(
                {"status": "error", "message": "Debe proporcionar idSesion, numero y mensaje."},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # --- Validación de sesión activa ---
            try:
                sesion = SesionWhatsApp.objects.get(pk=idSesion, status=True)
            except ObjectDoesNotExist:
                return Response(
                    {"status": "error", "message": "Sesión no encontrada o inactiva."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # --- Validación de contacto existente ---
            contacto = Contacto.objects.filter(
                status=True, sesion=sesion, contacto_numero=numero
            ).first()

            if not contacto:
                return Response(
                    {
                        "status": "error",
                        "message": f"No existe un contacto activo con {numero}. "
                                   "Debe iniciar primero una conversación antes de enviar mensajes."
                    },
                    status=status.HTTP_400_BAD_REQUEST
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
                return Response(
                    {"status": "error", "message": f"Error al enviar mensaje: {response.get('error', 'Desconocido')}"},
                    status=status.HTTP_400_BAD_REQUEST
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

            return Response(
                {
                    "status": "success",
                    "message": f"Mensaje enviado correctamente a {numero}",
                    "data": response
                },
                status=status.HTTP_200_OK
            )

    except Exception as e:
        return Response(
            {"status": "error", "message": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )