"""Contactos de TikTok: reusa el módulo de contactos de whatsapp
(`whatsapp.view_contacto.contactoView`) acotado al proveedor tiktok vía
`canal_fijo`. Los contactos nacen del webhook (open_id); no hay alta manual ni
importación en este canal — el template oculta esos botones con canal_fijo."""
from whatsapp.view_contacto import contactoView


def contactosTikTokView(request):
    return contactoView(request, canal_fijo='tiktok')
