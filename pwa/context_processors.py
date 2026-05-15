from django.conf import settings


def pwa_settings(request):
    return {
        'pwa_install_cooldown_hours': getattr(settings, 'PWA_INSTALL_COOLDOWN_HOURS', 10),
    }
