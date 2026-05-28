from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.funciones import set_wa_sesion_activa
from .permisos_sesion import sesiones_visibles


@login_required
@require_POST
def set_sesion_activa(request):
    raw = (request.POST.get('sesion_id') or '').strip().lower()
    if raw in ('', '0', 'todas'):
        sid = set_wa_sesion_activa(request, 0)
        return JsonResponse({'result': True, 'sesion_id': sid})
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return JsonResponse({'result': False, 'message': 'Invalid session id.'}, status=400)
    if not sesiones_visibles(request.user).filter(id=sid).exists():
        return JsonResponse({'result': False, 'message': 'Session not allowed.'}, status=403)
    set_wa_sesion_activa(request, sid)
    return JsonResponse({'result': True, 'sesion_id': sid})
