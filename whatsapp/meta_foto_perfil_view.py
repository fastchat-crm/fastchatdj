"""Cambiar foto de perfil de una sesión Meta Cloud API.

Recibe un archivo de imagen del operador, lo manda a Meta vía Resumable
Upload + business_profile, y cachea el data URL base64 en
`ConfigMeta.foto_perfil` para que el avatar del card lo muestre sin
volver a pegarle a Meta.

URL: POST /whatsapp/sesiones/<sesion_id>/profile-picture/
"""
from __future__ import annotations

import base64
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.funciones import secure_module

from .models import SesionWhatsApp
from .services_meta import MetaWhatsAppService

logger = logging.getLogger(__name__)

ALLOWED_MIME = {'image/jpeg', 'image/png'}
MAX_BYTES = 5 * 1024 * 1024  # Meta: 5MB


@login_required
@secure_module
@require_POST
def meta_actualizar_foto_perfil(request, sesion_id: int):
    """Endpoint AJAX que sube una nueva foto a Meta y la cachea localmente."""
    sesion = SesionWhatsApp.objects.filter(
        id=sesion_id, proveedor='meta', usuario=request.user,
    ).first()
    if not sesion:
        return JsonResponse({'success': False, 'message': 'Sesión Meta no encontrada.'}, status=404)

    config = getattr(sesion, 'config_meta', None)
    if not config:
        return JsonResponse({'success': False, 'message': 'La sesión no tiene ConfigMeta cargada.'})

    archivo = request.FILES.get('foto')
    if not archivo:
        return JsonResponse({'success': False, 'message': 'No se recibió ningún archivo (campo "foto").'})

    mime = (archivo.content_type or '').lower()
    if mime not in ALLOWED_MIME:
        return JsonResponse({
            'success': False,
            'message': f'Formato no soportado ({mime or "desconocido"}). Usa JPG o PNG.',
        })

    if archivo.size > MAX_BYTES:
        return JsonResponse({
            'success': False,
            'message': f'La imagen pesa {archivo.size // 1024} KB. Máximo permitido: 5 MB.',
        })

    file_bytes = archivo.read()

    service = MetaWhatsAppService()
    resultado = service.actualizar_foto_perfil(
        session_id=sesion.session_id,
        file_bytes=file_bytes,
        mime_type=mime,
    )

    if not resultado.get('success'):
        return JsonResponse({
            'success': False,
            'message': resultado.get('message') or 'Meta rechazó la foto.',
        })

    # Cachear data URL base64 para mostrar en el avatar del card sin volver a
    # pegarle a Meta (Meta no devuelve la foto en consultas normales).
    try:
        b64 = base64.b64encode(file_bytes).decode('ascii')
        data_url = f'data:{mime};base64,{b64}'
        config.foto_perfil = data_url
        config.ultima_sincronizacion = timezone.now()
        config.save(update_fields=['foto_perfil', 'ultima_sincronizacion'])
    except Exception:
        logger.exception("Error cacheando foto_perfil para ConfigMeta %s", config.id)

    return JsonResponse({
        'success': True,
        'message': 'Foto actualizada en Meta y guardada localmente.',
        'foto_perfil': config.foto_perfil or '',
    })
