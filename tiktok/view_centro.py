"""Centro TikTok — guía instructiva de los módulos del canal."""
from django.contrib.auth.decorators import login_required

from core.funciones import secure_module
from whatsapp.view_centro import _render_centro


@login_required
@secure_module
def centroTikTokView(request):
    return _render_centro(request, 'tiktok')
