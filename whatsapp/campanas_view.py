"""Vista de campañas (broadcasts)."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.funciones import addData, paginador, secure_module, log
from .models import (
    Campana, EnvioCampana, SesionWhatsApp, EtiquetaContacto, PlantillaWhatsApp,
)


@login_required
@secure_module
def campanasView(request):
    data = {
        'titulo': 'Campañas',
        'descripcion': 'Envío masivo segmentado de mensajes WhatsApp / IG / Messenger',
        'ruta': request.path,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add':
                    sesion_id = int(request.POST['sesion'])
                    sesion = SesionWhatsApp.objects.get(pk=sesion_id)
                    camp = Campana.objects.create(
                        nombre=request.POST['nombre'],
                        descripcion=request.POST.get('descripcion', ''),
                        sesion=sesion,
                        tipo=request.POST.get('tipo', 'texto'),
                        mensaje_texto=request.POST.get('mensaje_texto', ''),
                        plantilla_id=int(request.POST['plantilla_id']) if request.POST.get('plantilla_id') else None,
                        throttle_por_minuto=int(request.POST.get('throttle_por_minuto', 20) or 20),
                        canales=request.POST.getlist('canales[]') or [],
                        estado='borrador',
                        usuario_creacion=request.user,
                    )
                    if request.POST.getlist('etiquetas_incluir[]'):
                        camp.etiquetas_incluir.set(request.POST.getlist('etiquetas_incluir[]'))
                    if request.POST.getlist('etiquetas_excluir[]'):
                        camp.etiquetas_excluir.set(request.POST.getlist('etiquetas_excluir[]'))
                    if request.FILES.get('archivo'):
                        camp.archivo = request.FILES['archivo']
                        camp.save(update_fields=['archivo'])
                    log(f'Campaña {camp.nombre} creada', request, 'add', obj=camp.id)
                    return JsonResponse({'error': False, 'campana_id': camp.id, 'reload': True})

                if action == 'programar':
                    pk = int(request.POST['id'])
                    camp = Campana.objects.get(pk=pk)
                    fecha = request.POST.get('programada_para')
                    if fecha:
                        camp.programada_para = fecha
                    camp.estado = 'programada'
                    camp.save(update_fields=['estado', 'programada_para'])
                    return JsonResponse({'error': False, 'message': 'Campaña programada.'})

                if action == 'enviar_ahora':
                    pk = int(request.POST['id'])
                    camp = Campana.objects.get(pk=pk)
                    camp.estado = 'programada'
                    camp.programada_para = timezone.now()
                    camp.save(update_fields=['estado', 'programada_para'])
                    return JsonResponse({
                        'error': False,
                        'message': 'Campaña encolada. El cron la despachará en el próximo tick.',
                    })

                if action == 'pausar':
                    Campana.objects.filter(pk=int(request.POST['id'])).update(estado='pausada')
                    return JsonResponse({'error': False})

                if action == 'cancelar':
                    Campana.objects.filter(pk=int(request.POST['id'])).update(estado='cancelada')
                    return JsonResponse({'error': False})

                if action == 'eliminar':
                    pk = int(request.POST['id'])
                    Campana.objects.filter(pk=pk).update(status=False)
                    return JsonResponse({'error': False})

        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    pk = request.GET.get('pk')
    if pk and request.GET.get('action') == 'detalle':
        camp = Campana.objects.get(pk=pk)
        envios_qs = camp.envios.select_related('contacto').order_by('-fecha_envio', '-id')
        data['campana'] = camp
        data['envios'] = envios_qs[:200]
        return render(request, 'whatsapp/campanas/detalle.html', data)

    listado = Campana.objects.filter(status=True).order_by('-fecha_registro')
    paginador(request, listado, 20, data, '')
    data['sesiones'] = SesionWhatsApp.objects.filter(status=True, usuario=request.user)
    data['etiquetas'] = EtiquetaContacto.objects.filter(status=True)
    data['plantillas'] = PlantillaWhatsApp.objects.filter(status=True, estado_meta='APPROVED')
    return render(request, 'whatsapp/campanas/listado.html', data)
