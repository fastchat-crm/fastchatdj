"""Reglas comentario→DM — CRUD por canal (Instagram y Facebook hoy, TikTok cuando se apruebe)."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, paginador, secure_module, log
from .models import (
    PROVEEDOR_POR_CANAL,
    EtiquetaContacto,
    ReglaComentario,
    SesionWhatsApp,
)

NOMBRES_CANAL = {'instagram': 'Instagram', 'facebook': 'Facebook', 'tiktok': 'TikTok'}


def _aplicar_campos(regla, request):
    regla.nombre = (request.POST.get('nombre') or regla.nombre).strip()
    regla.keywords = (request.POST.get('keywords') or '').strip()
    regla.media_id = (request.POST.get('media_id') or '').strip()
    regla.respuesta_publica = (request.POST.get('respuesta_publica') or '').strip()
    regla.mensaje_dm = (request.POST.get('mensaje_dm') or '').strip()
    regla.etiqueta_id = request.POST.get('etiqueta_id') or None
    regla.activa = request.POST.get('activa') == 'on'
    try:
        regla.orden = max(1, int(request.POST.get('orden') or 1))
    except (TypeError, ValueError):
        regla.orden = 1


def _validar(regla):
    if not (regla.respuesta_publica or regla.mensaje_dm or regla.etiqueta_id):
        return 'La regla necesita al menos una acción: respuesta pública, DM o etiqueta.'
    return ''


def reglasComentariosView(request, canal='instagram'):
    nombre_canal = NOMBRES_CANAL.get(canal, canal)
    data = {
        'titulo': f'Reglas de comentarios {nombre_canal}',
        'descripcion': 'Automatización comentario→DM: responde y convierte comentarios en conversaciones',
        'ruta': request.path,
        'canal': canal,
        'nombre_canal': nombre_canal,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add':
                    nombre = (request.POST.get('nombre') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'Nombre obligatorio.'})
                    sesion = SesionWhatsApp.objects.filter(
                        pk=int(request.POST['sesion_id']), usuario=request.user, status=True,
                    ).first()
                    if not sesion:
                        return JsonResponse({'error': True, 'message': 'Sesión no encontrada.'})
                    regla = ReglaComentario(sesion=sesion, canal=canal)
                    _aplicar_campos(regla, request)
                    error = _validar(regla)
                    if error:
                        return JsonResponse({'error': True, 'message': error})
                    regla.save()
                    log(f'Regla de comentarios {regla.nombre} creada', request, 'add', obj=regla.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    regla = ReglaComentario.objects.get(pk=int(request.POST['pk']), status=True)
                    _aplicar_campos(regla, request)
                    error = _validar(regla)
                    if error:
                        return JsonResponse({'error': True, 'message': error})
                    regla.save()
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    regla = ReglaComentario.objects.get(pk=int(request.POST['id']), status=True)
                    regla.status = False
                    regla.save()
                    return JsonResponse({'error': False})

                if action == 'toggle_activa':
                    regla = ReglaComentario.objects.get(pk=int(request.POST['id']), status=True)
                    regla.activa = not regla.activa
                    regla.save()
                    return JsonResponse({'error': False, 'activa': regla.activa})

        except ReglaComentario.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Regla no encontrada.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    criterio = (request.GET.get('criterio') or '').strip()
    qs = ReglaComentario.objects.filter(
        status=True, canal=canal, sesion__usuario=request.user,
    ).select_related('sesion', 'etiqueta')
    url_vars = ''
    if criterio:
        qs = qs.filter(Q(nombre__icontains=criterio) | Q(keywords__icontains=criterio))
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    listado = qs.order_by('sesion', 'orden', 'id')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['sesiones'] = SesionWhatsApp.objects.filter(
        usuario=request.user, status=True,
        proveedor=PROVEEDOR_POR_CANAL.get(canal, canal),
    ).order_by('nombre')
    data['etiquetas_disponibles'] = EtiquetaContacto.objects.filter(
        status=True, usuario_creacion=request.user,
    ).order_by('nombre')
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'whatsapp/reglas_comentarios/listado.html', data)
