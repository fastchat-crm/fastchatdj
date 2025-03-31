# whatsapp/views.py (crear_sesion adaptado a tus modelos)
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from .models import SesionWhatsApp, WhatsAppWebhook
from .services import WhatsAppService

whatsapp_service = WhatsAppService()

def crear_sesion(request):
    if request.method == 'POST':
        numero = request.POST.get('numero')
        try:
            # Crear webhooks para esta sesión
            webhook_url = request.build_absolute_uri(reverse('webhook_handler'))

            webhooks = [
                {'url': webhook_url, 'type': 'qr_code'},
                {'url': webhook_url, 'type': 'ready'},
                {'url': webhook_url, 'type': 'authenticated'},
                {'url': webhook_url, 'type': 'auth_failure'},
                {'url': webhook_url, 'type': 'disconnected'},
                {'url': webhook_url, 'type': 'message'},
                {'url': webhook_url, 'type': 'message_sent'}
            ]

            # Crear sesión en la API con webhooks
            result = whatsapp_service.create_session_with_webhooks(numero, webhooks)

            # Guardar en la base de datos local
            sesion = SesionWhatsApp.objects.create(
                session_id=result['sessionId'],
                numero=numero,
                estado='pendiente'
            )

            # Guardar los webhooks en la base de datos local
            for webhook in webhooks:
                WhatsAppWebhook.objects.create(
                    session=sesion,
                    url=webhook['url'],
                    type=webhook['type']
                )

            messages.success(request, f"Sesión para {numero} creada correctamente")
            return redirect('detalle_sesion', session_id=sesion.session_id)
        except Exception as e:
            messages.error(request, f"Error al crear sesión: {str(e)}")
            return redirect('lista_sesiones')

    return render(request, 'whatsapp/crear_sesion.html')