"""Enlaces de captación (growth links) — CRUD y métricas de uso."""
import re
import unicodedata

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, paginador, secure_module, log
from .models import EnlaceCrecimiento, EtiquetaContacto, SecuenciaWhatsApp, SesionWhatsApp


def _slug(texto):
    texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    texto = re.sub(r'[^a-z0-9]+', '-', texto.lower()).strip('-')
    return texto[:36] or 'enlace'


def _codigo_unico(base, excluir_pk=None):
    codigo = base
    sufijo = 1
    qs = EnlaceCrecimiento.objects.all()
    if excluir_pk:
        qs = qs.exclude(pk=excluir_pk)
    while qs.filter(codigo=codigo).exists():
        sufijo += 1
        codigo = f'{base[:33]}-{sufijo}'
    return codigo


def _aplicar_campos(enlace, request):
    enlace.nombre = (request.POST.get('nombre') or enlace.nombre).strip()
    enlace.descripcion = (request.POST.get('descripcion') or '').strip()
    enlace.texto_prellenado = (request.POST.get('texto_prellenado') or '¡Hola! Quiero más información.').strip()
    enlace.mensaje_respuesta = (request.POST.get('mensaje_respuesta') or '').strip()
    enlace.activo = request.POST.get('activo') == 'on'
    enlace.etiqueta_id = request.POST.get('etiqueta_id') or None
    enlace.secuencia_id = request.POST.get('secuencia_id') or None


@login_required
@secure_module
def growthView(request):
    data = {
        'titulo': 'Enlaces de captación',
        'descripcion': 'Links wa.me con seguimiento: etiquetan, inscriben en secuencias y miden cada canal de captación',
        'ruta': request.path,
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
                    if not ''.join(ch for ch in (sesion.numero or '') if ch.isdigit()):
                        return JsonResponse({'error': True, 'message': 'La sesión no tiene número registrado; conéctala primero.'})
                    enlace = EnlaceCrecimiento(sesion=sesion, codigo=_codigo_unico(_slug(nombre)))
                    _aplicar_campos(enlace, request)
                    enlace.save()
                    log(f'Enlace de captación {enlace.nombre} creado', request, 'add', obj=enlace.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    enlace = EnlaceCrecimiento.objects.get(pk=int(request.POST['pk']), status=True)
                    _aplicar_campos(enlace, request)
                    enlace.save()
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    enlace = EnlaceCrecimiento.objects.get(pk=int(request.POST['id']), status=True)
                    enlace.status = False
                    enlace.save()
                    return JsonResponse({'error': False})

                if action == 'toggle_activo':
                    enlace = EnlaceCrecimiento.objects.get(pk=int(request.POST['id']), status=True)
                    enlace.activo = not enlace.activo
                    enlace.save()
                    return JsonResponse({'error': False, 'activo': enlace.activo})

        except EnlaceCrecimiento.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Enlace no encontrado.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    criterio = (request.GET.get('criterio') or '').strip()
    qs = EnlaceCrecimiento.objects.filter(status=True, sesion__usuario=request.user).select_related(
        'sesion', 'etiqueta', 'secuencia',
    )
    url_vars = ''
    if criterio:
        qs = qs.filter(Q(nombre__icontains=criterio) | Q(codigo__icontains=criterio))
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    listado = qs.order_by('nombre')
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['sesiones'] = SesionWhatsApp.objects.filter(
        usuario=request.user, status=True, proveedor__in=('baileys', 'meta'),
    ).order_by('nombre')
    data['etiquetas_disponibles'] = EtiquetaContacto.objects.filter(
        status=True, usuario_creacion=request.user,
    ).order_by('nombre')
    data['secuencias_disponibles'] = SecuenciaWhatsApp.objects.filter(status=True).order_by('nombre')
    paginador(request, listado, 50, data, url_vars)
    return render(request, 'whatsapp/growth/listado.html', data)
