"""Contactos de Instagram DM: reusa el módulo de contactos de whatsapp
(`whatsapp.view_contacto.contactoView`) acotado al proveedor instagram vía
`canal_fijo`. Los contactos nacen del webhook (IGSID); no hay alta manual ni
importación en este canal — el template oculta esos botones con canal_fijo."""
from whatsapp.view_contacto import contactoView


def contactosInstagramView(request):
    return contactoView(request, canal_fijo='instagram')
