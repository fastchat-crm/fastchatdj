import json
from datetime import time

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render

from core.funciones import addData, log, secure_module

from .models import HorarioLaboral, Recurso, WEEKDAY_CHOICES


def _parse_time(value):
    parts = (value or '').split(':')
    if len(parts) < 2:
        return None
    try:
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, TypeError):
        return None


@login_required
@secure_module
def horarioEditorView(request, recurso_id):
    try:
        recurso = Recurso.objects.select_related('grupo_agenda').get(pk=recurso_id, status=True)
    except Recurso.DoesNotExist:
        raise Http404('Resource not found.')

    data = {
        'titulo': f'Schedule · {recurso.nombre}',
        'descripcion': 'Drag on the grid to add working blocks. Drag a block to move or its edges to resize.',
        'ruta': request.path,
        'recurso': recurso,
        'weekday_choices': WEEKDAY_CHOICES,
    }
    addData(request, data)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            with transaction.atomic():
                if action == 'save':
                    raw = request.POST.get('blocks') or '[]'
                    blocks = json.loads(raw)
                    slot_min_default = int(request.POST.get('slot_min') or 30)
                    HorarioLaboral.objects.filter(recurso=recurso, status=True).update(status=False)
                    creados = 0
                    for b in blocks:
                        dia = int(b.get('day'))
                        hi = _parse_time(b.get('start'))
                        hf = _parse_time(b.get('end'))
                        slot_min = int(b.get('slot_min') or slot_min_default)
                        if hi is None or hf is None or hi >= hf:
                            continue
                        if dia < 0 or dia > 6:
                            continue
                        h = HorarioLaboral(
                            recurso=recurso, dia_semana=dia,
                            hora_inicio=hi, hora_fin=hf, duracion_slot_min=slot_min,
                        )
                        h.save(request=request)
                        creados += 1
                    log(f'Schedule for resource {recurso.nombre} updated ({creados} blocks)',
                        request, 'change', obj=recurso.id)
                    return JsonResponse({'error': False, 'count': creados})
        except Exception as ex:
            return JsonResponse({'error': True, 'message': f'Error: {ex}'})

    horarios = HorarioLaboral.objects.filter(recurso=recurso, status=True).order_by('dia_semana', 'hora_inicio')
    blocks_seed = [
        {
            'id': h.id,
            'day': h.dia_semana,
            'start': h.hora_inicio.strftime('%H:%M'),
            'end': h.hora_fin.strftime('%H:%M'),
            'slot_min': h.duracion_slot_min,
        }
        for h in horarios
    ]
    data['blocks_seed'] = json.dumps(blocks_seed)
    data['default_slot_min'] = horarios.first().duracion_slot_min if horarios.exists() else 30
    return render(request, 'agenda/horario/editor.html', data)
