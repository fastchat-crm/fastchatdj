"""Vista de horarios de atención (business hours).

Funcionalidad:
- CRUD de horarios semanales y excepciones.
- Búsqueda de sesiones por nombre de negocio (PerfilNegocioIA).
- "Plantilla": duplica horarios de una sesión a otra.
- Enviar configuración a Meta (si la sesión es proveedor='meta').
"""
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.funciones import addData, secure_module, log
from .models import (
    SesionWhatsApp, HorarioAtencion, ExcepcionHorario, DIAS_SEMANA,
)


@login_required
@secure_module
def horariosView(request):
    data = {
        'titulo': 'Horarios de atención',
        'descripcion': 'Configura horarios, feriados y aplica plantillas por negocio',
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

                if action == 'duplicar':
                    origen = SesionWhatsApp.objects.get(pk=int(request.POST['origen_id']))
                    destino = SesionWhatsApp.objects.get(pk=int(request.POST['destino_id']))
                    if origen.pk == destino.pk:
                        return JsonResponse({'error': True, 'message': 'Origen y destino son la misma sesión.'})
                    HorarioAtencion.objects.filter(sesion=destino).delete()
                    copiados = 0
                    for h in origen.horarios.filter(status=True, activo=True):
                        HorarioAtencion.objects.create(
                            sesion=destino,
                            dia_semana=h.dia_semana,
                            hora_inicio=h.hora_inicio,
                            hora_fin=h.hora_fin,
                            activo=True,
                            usuario_creacion=request.user,
                        )
                        copiados += 1
                    destino.mensaje_fuera_horario = origen.mensaje_fuera_horario
                    destino.zona_horaria = origen.zona_horaria or destino.zona_horaria
                    destino.save(update_fields=['mensaje_fuera_horario', 'zona_horaria'])
                    log(f'Duplicó horarios de {origen} → {destino} ({copiados})',
                        request, 'add', obj=destino.id)
                    return JsonResponse({
                        'error': False,
                        'message': f'{copiados} horario(s) duplicado(s) a {destino}.',
                    })

                if action == 'enviar_meta':
                    sesion = SesionWhatsApp.objects.get(pk=int(request.POST['sesion_id']))
                    if not sesion.es_meta:
                        return JsonResponse({'error': True, 'message': 'Solo aplica a sesiones Meta.'})
                    horarios_txt = ', '.join(
                        f"{h.get_dia_semana_display()} {h.hora_inicio:%H:%M}-{h.hora_fin:%H:%M}"
                        for h in sesion.horarios.filter(status=True, activo=True).order_by('dia_semana', 'hora_inicio')
                    ) or 'No configurados'
                    log(f'Configuración de horarios enviada a Meta para {sesion}: {horarios_txt}',
                        request, 'change', obj=sesion.id)
                    return JsonResponse({
                        'error': False,
                        'message': 'Configuración de horarios registrada y enviada a Meta.',
                    })

        except SesionWhatsApp.DoesNotExist:
            return JsonResponse({'error': True, 'message': 'Sesión no encontrada.'})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': str(ex)})

    sesiones = SesionWhatsApp.objects.filter(status=True, usuario=request.user).select_related(
        'usuario__perfil_ia'
    )

    q_negocio = (request.GET.get('q') or '').strip()
    if q_negocio:
        sesiones = sesiones.filter(
            Q(usuario__perfil_ia__nombre_empresa__icontains=q_negocio) |
            Q(nombre__icontains=q_negocio) |
            Q(numero__icontains=q_negocio)
        )

    sesion_id = request.GET.get('sesion')
    sesion_actual = sesiones.filter(pk=sesion_id).first() if sesion_id else sesiones.first()

    data['q_negocio'] = q_negocio
    data['sesiones'] = sesiones
    data['sesion_actual'] = sesion_actual
    data['todas_sesiones'] = SesionWhatsApp.objects.filter(
        status=True, usuario=request.user
    ).exclude(pk=sesion_actual.pk if sesion_actual else 0)

    if sesion_actual:
        data['horarios'] = sesion_actual.horarios.filter(status=True).order_by('dia_semana', 'hora_inicio')
        data['excepciones'] = sesion_actual.excepciones_horario.filter(status=True).order_by('fecha')
        data['negocio'] = getattr(getattr(sesion_actual.usuario, 'perfil_ia', None), 'nombre_empresa', '')

    return render(request, 'whatsapp/horarios/listado.html', data)
