"""Monitoreo de webhooks del canal WhatsApp Cloud.

Wrapper del monitor compartido `view_monitoreo_social.monitoreo_webhook_canal`
(mismo patrón que instagram/facebook/tiktok): lista los `EventoMetaRecibido`
del canal WhatsApp (todos los eventos SIN prefijo de canal social) con stats,
filtros por estado y detalle de payload — auditoría/diagnóstico del webhook.
"""
from django.contrib.auth.decorators import login_required

from core.funciones import secure_module
from .view_monitoreo_social import monitoreo_webhook_canal


@login_required
@secure_module
def monitoreoWhatsAppView(request):
    return monitoreo_webhook_canal(request, 'whatsapp')
