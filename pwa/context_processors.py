from django.conf import settings


def pwa_settings(request):
    webpush = getattr(settings, 'WEBPUSH_SETTINGS', {}) or {}
    return {
        'pwa_install_cooldown_hours': getattr(settings, 'PWA_INSTALL_COOLDOWN_HOURS', 10),
        'vapid_key': webpush.get('VAPID_PUBLIC_KEY', ''),
    }
