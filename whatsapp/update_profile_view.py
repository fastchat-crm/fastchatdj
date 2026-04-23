from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from whatsapp.models import SesionWhatsApp
from whatsapp.services import WhatsAppService


@login_required
@csrf_exempt
def update_profile_view(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método no permitido'}, status=405)

    try:
        session_id = request.POST.get('session_id')
        if not session_id:
            return JsonResponse({'success': False, 'message': 'ID de sesión requerido'}, status=400)

        sesion = get_object_or_404(SesionWhatsApp, id=session_id)

        # update_profile solo aplica al transporte Baileys (es la foto del perfil
        # del WhatsApp Web vinculado). En Meta el perfil se gestiona desde el
        # Business Manager, no por API desde la app.
        if not sesion.es_baileys:
            return JsonResponse({
                'success': False,
                'message': 'Actualizar el perfil solo esta disponible para sesiones Baileys. En Meta gestiona el perfil desde Meta Business Manager.',
            })

        # Llamar al servicio para actualizar el perfil
        service = WhatsAppService()
        response = service.update_profile(sesion.session_id)

        if response.get('success'):
            from .models import ConfigBaileys
            cb, _ = ConfigBaileys.objects.get_or_create(sesion=sesion)
            # Si la respuesta incluye la foto de perfil, actualizarla directamente
            if response.get('profile_picture_base64'):
                cb.foto = response.get('profile_picture_base64')
                cb.save(update_fields=['foto'])

            return JsonResponse({
                'success': True,
                'message': 'Perfil actualizado correctamente',
                'foto': cb.foto or ''
            })
        else:
            return JsonResponse({'success': False, 'message': response.get('message', 'Error desconocido')})

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)