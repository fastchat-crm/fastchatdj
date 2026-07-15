"""Shim de compatibilidad — el receiver TikTok se movió a la app `tiktok`.

La implementación canónica vive en `tiktok/webhook_view.py` y se sirve bajo
`/tiktok/webhook/`. Este módulo se mantiene sólo para no romper la URL legacy
`/whatsapp/tiktok_webhook/` (dashboards ya configurados). Re-exporta la vista.
"""
from tiktok.webhook_view import tiktok_webhook  # noqa: F401
