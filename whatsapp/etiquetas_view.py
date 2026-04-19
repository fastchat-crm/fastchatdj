"""CRUD de etiquetas (tags) para segmentación de contactos."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, paginador, secure_module, log
from .models import EtiquetaContacto, Contacto


@login_required
@secure_module
def etiquetasView(request):
    data = {
        'titulo': 'Etiquetas',
        'descripcion': 'Etiquetas libres para segmentar contactos y campañas',
        'ruta': request.path,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add':
                    nombre = (request.POST.get('nombre') or '').strip()
                    color = (request.POST.get('color') or '#0d6efd').strip()
                    descripcion = (request.POST.get('descripcion') or '').strip()
                    if not nombre:
                        return JsonResponse({'error': True, 'message': 'Nombre obligatorio.'})
                    if EtiquetaContacto.objects.filter(
                        usuario_creacion=request.user, nombre__iexact=nombre, status=True
                    ).exists():
                        return JsonResponse({'error': True, 'message': 'Ya existe una etiqueta con ese nombre.'})
                    et = EtiquetaContacto.objects.create(
                        nombre=nombre, color=color, descripcion=descripcion,
                        usuario_creacion=request.user,
                    )
                    log(f'Etiqueta {et.nombre} creada', request, 'add', obj=et.id)
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'change':
                    pk = int(request.POST['pk'])
                    et = EtiquetaContacto.objects.get(pk=pk, usuario_creacion=request.user)
                    et.nombre = (request.POST.get('nombre') or et.nombre).strip()
                    et.color = (request.POST.get('color') or et.color).strip()
                    et.descripcion = (request.POST.get('descripcion') or '').strip()
                    et.save()
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete':
                    pk = int(request.POST['id'])
                    et = EtiquetaContacto.objects.get(pk=pk, usuario_creacion=request.user)
                    et.status = False
                    et.save()
                    return JsonResponse({'error': False})

                if action == 'asignar_a_contacto':
                    contacto = Contacto.objects.get(pk=int(request.POST['contacto_id']))
                    et = EtiquetaContacto.objects.get(pk=int(request.POST['etiqueta_id']))
                    contacto.etiquetas.add(et)
                    return JsonResponse({'error': False, 'message': 'Etiqueta asignada.'})

                if action == 'quitar_de_contacto':
                    contacto = Contacto.objects.get(pk=int(request.POST['contacto_id']))
                    et = EtiquetaContacto.objects.get(pk=int(request.POST['etiqueta_id']))
                    contacto.etiquetas.remove(et)
                    return JsonResponse({'error': False, 'message': 'Etiqueta quitada.'})

        except EtiquetaContacto.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Etiqueta no encontrada.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    listado = EtiquetaContacto.objects.filter(
        status=True, usuario_creacion=request.user,
    ).order_by('nombre')
    paginador(request, listado, 50, data, '')
    return render(request, 'whatsapp/etiquetas/listado.html', data)
