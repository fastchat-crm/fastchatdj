from django.urls import re_path

from .view_centro import centroTikTokView
from .view_comentarios import comentariosTikTokView
from .view_conversaciones import conversacionesTikTokView
from .view_cuentas import cuentasView
from .view_monitoreo import monitoreoTikTokView
from .webhook_view import tiktok_webhook

tiktok_urls = (
    {
        "nombre": "Centro TikTok",
        "url": 'centro/',
        "vista": centroTikTokView,
    },
    {
        "nombre": "Sesiones TikTok",
        "url": 'sesiones/',
        "vista": cuentasView,
    },
    {
        "nombre": "Conversaciones TikTok",
        "url": 'conversaciones/',
        "vista": conversacionesTikTokView,
    },
    {
        "nombre": "Comentarios TikTok",
        "url": 'comentarios/',
        "vista": comentariosTikTokView,
    },
    {
        "nombre": "Monitoreo TikTok",
        "url": 'monitoreo/',
        "vista": monitoreoTikTokView,
    },
)

urlpatterns = [
    re_path(r'^webhook/$', tiktok_webhook, name='tiktok_webhook'),
]
for u in tiktok_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))
