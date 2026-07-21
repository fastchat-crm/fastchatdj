from django.db.models import Q

from .models import SesionWhatsApp


def sesiones_visibles(usuario):
    qs = SesionWhatsApp.objects.filter(status=True, activo=True)
    return qs.filter(
        Q(usuario=usuario)
        | Q(perfilsesionwhatsapp__usuario=usuario, perfilsesionwhatsapp__status=True)
    ).distinct()


def sesiones_visibles_activas(usuario):
    return sesiones_visibles(usuario)


def sesiones_vista_completa(usuario):
    qs = SesionWhatsApp.objects.filter(status=True, activo=True)
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


def puede_asignar_masivo(usuario, sesion):
    """Permiso por sesión para repartir de golpe las conversaciones sin asesor.

    No basta con ser supervisor: el perfil de la sesión debe tener marcado
    `puede_asignar_masivo_asesores`. El superusuario siempre puede.
    """
    if getattr(usuario, 'is_superuser', False):
        return True
    if not sesion:
        return False
    from .models import PerfilSesionWhatsApp
    return PerfilSesionWhatsApp.objects.filter(
        sesion=sesion, usuario=usuario, status=True,
        puede_asignar_masivo_asesores=True,
    ).exists()


def filtro_conversaciones_por_rol(usuario, sesion):
    rol = rol_en_sesion(usuario, sesion)
    if rol in ('superuser', 'supervisor'):
        return Q()
    if rol == 'asesor':
        return Q(asignado_a=usuario) | Q(asignado_a__isnull=True)
    return Q(pk__in=[])


def puede_ver_conversacion(usuario, conv):
    if getattr(usuario, 'is_superuser', False):
        return True
    sesion = getattr(conv, 'sesion', None)
    rol = rol_en_sesion(usuario, sesion)
    if rol == 'supervisor':
        return True
    if rol == 'asesor':
        return conv.asignado_a_id == usuario.id or conv.asignado_a_id is None
    return False
