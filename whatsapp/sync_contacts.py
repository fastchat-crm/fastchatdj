import requests
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from fastchatdj import settings
from whatsapp.models import SesionWhatsApp
from whatsapp.services import WhatsAppService


# En views.py
@login_required
@csrf_exempt
def sync_contacts_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método no permitido'}, status=405)

    try:
        session_id = request.POST.get('session_id')
        if not session_id:
            return JsonResponse({'success': False, 'message': 'ID de sesión requerido'}, status=400)

        sesion = get_object_or_404(SesionWhatsApp, id=session_id)

        # sync_contacts pide a Node la libreta de WhatsApp Web. En Meta no existe
        # ese concepto: los contactos solo aparecen cuando te escriben (no hay
        # "agenda" expuesta por la API).
        if not sesion.es_baileys:
            return JsonResponse({
                'success': False,
                'message': 'Sincronizar contactos solo esta disponible para sesiones Baileys. En Meta los contactos se registran cuando inician una conversacion.',
            })

        # Llamar al servicio para sincronizar contactos
        service = WhatsAppService()
        response = service.sync_contacts(sesion)

        return JsonResponse({'success': True, 'message': 'Sincronización iniciada'})

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)