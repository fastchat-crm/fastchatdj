from core.funciones import WA_SESION_ACTIVA_KEY
from .permisos_sesion import sesiones_visibles


def selector_sesion(request):
    usuario = getattr(request, 'user', None)
    if not usuario or not usuario.is_authenticated:
        return {}
    sesiones = list(
        sesiones_visibles(usuario)
        .only('id', 'nombre', 'numero', 'estado', 'activo', 'proveedor')
        .order_by('nombre')
    )
    activa_id = request.session.get(WA_SESION_ACTIVA_KEY) or 0
    activa = next((s for s in sesiones if s.id == activa_id), None) if activa_id else None
    return {
        'wa_selector_sesiones': sesiones,
        'wa_selector_activa_id': activa_id,
        'wa_selector_activa': activa,
    }
