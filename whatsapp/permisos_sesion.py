from django.db.models import Q

from .models import SesionWhatsApp


def sesiones_visibles(usuario):
    qs = SesionWhatsApp.objects.filter(status=True)
    if getattr(usuario, 'is_superuser', False):
        return qs
    return qs.filter(
        Q(usuario=usuario)
        | Q(perfilsesionwhatsapp__usuario=usuario, perfilsesionwhatsapp__status=True)
    ).distinct()


def sesiones_vista_completa(usuario):
    qs = SesionWhatsApp.objects.filter(status=True)
    if getattr(usuario, 'is_superuser', False):
        return qs
    return qs.filter(
        Q(usuario=usuario)
        | Q(perfilsesionwhatsapp__usuario=usuario, perfilsesionwhatsapp__status=True,
            perfilsesionwhatsapp__rol='supervisor')
    ).distinct()


def rol_en_sesion(usuario, sesion):
    if getattr(usuario, 'is_superuser', False):
        return 'superuser'
    if not sesion:
        return None
    return sesion.rol_de_usuario(usuario)


def es_vista_completa(usuario, sesion):
    return rol_en_sesion(usuario, sesion) in ('superuser', 'supervisor')


def filtro_conversaciones_por_rol(usuario, sesion):
    rol = rol_en_sesion(usuario, sesion)
    if rol in ('superuser', 'supervisor'):
        return Q()
    if rol == 'asesor':
        return Q(asignado_a=usuario)
    return Q(pk__in=[])


def puede_ver_conversacion(usuario, conv):
    if getattr(usuario, 'is_superuser', False):
        return True
    sesion = getattr(conv, 'sesion', None)
    rol = rol_en_sesion(usuario, sesion)
    if rol == 'supervisor':
        return True
    if rol == 'asesor':
        return conv.asignado_a_id == usuario.id
    return False
