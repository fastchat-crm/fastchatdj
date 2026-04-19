"""Vista de horarios de atención (business hours)."""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, secure_module
from .models import (
    SesionWhatsApp, HorarioAtencion, ExcepcionHorario, DIAS_SEMANA,
)


@login_required
@secure_module
def horariosView(request):
    data = {
        'titulo': 'Horarios de atención',
        'descripcion': 'Configura horarios y feriados por sesión',
        'ruta': request.path,
        'dias_semana': DIAS_SEMANA,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'add_horario':
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    HorarioAtencion.objects.create(
                        sesion=sesion,
                        dia_semana=int(request.POST['dia_semana']),
                        hora_inicio=request.POST['hora_inicio'],
                        hora_fin=request.POST['hora_fin'],
                        activo=True,
                        usuario_creacion=request.user,
                    )
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete_horario':
                    HorarioAtencion.objects.filter(pk=int(request.POST['id'])).delete()
                    return JsonResponse({'error': False})

                if action == 'add_excepcion':
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    ExcepcionHorario.objects.update_or_create(
                        sesion=sesion,
                        fecha=request.POST['fecha'],
                        defaults={
                            'abierto': request.POST.get('abierto') == 'true',
                            'hora_inicio': request.POST.get('hora_inicio') or None,
                            'hora_fin': request.POST.get('hora_fin') or None,
                            'motivo': request.POST.get('motivo', ''),
                            'usuario_creacion': request.user,
                        }
                    )
                    return JsonResponse({'error': False, 'reload': True})

                if action == 'delete_excepcion':
                    ExcepcionHorario.objects.filter(pk=int(request.POST['id'])).delete()
                    return JsonResponse({'error': False})

                if action == 'guardar_mensaje_fuera_horario':
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    sesion.mensaje_fuera_horario = request.POST.get('mensaje', '')
                    sesion.zona_horaria = request.POST.get('zona_horaria') or sesion.zona_horaria
                    sesion.save(update_fields=['mensaje_fuera_horario', 'zona_horaria'])
                    return JsonResponse({'error': False})

        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    sesion_id = request.GET.get('sesion')
    sesiones = SesionWhatsApp.objects.filter(status=True, usuario=request.user)
    sesion_actual = sesiones.filter(pk=sesion_id).first() if sesion_id else sesiones.first()
    data['sesiones'] = sesiones
    data['sesion_actual'] = sesion_actual
    if sesion_actual:
        data['horarios'] = sesion_actual.horarios.filter(status=True).order_by('dia_semana', 'hora_inicio')
        data['excepciones'] = sesion_actual.excepciones_horario.filter(status=True).order_by('fecha')
    return render(request, 'whatsapp/horarios/listado.html', data)
