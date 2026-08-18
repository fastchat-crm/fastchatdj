"""Monitoreo de webhooks del canal Facebook/Messenger."""
from django.contrib.auth.decorators import login_required

from core.funciones import secure_module
from whatsapp.view_monitoreo_social import monitoreo_webhook_canal


@login_required
@secure_module
def monitoreoFacebookView(request):
    return monitoreo_webhook_canal(request, 'messenger')
