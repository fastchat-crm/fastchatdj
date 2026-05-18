import json
from datetime import date, time

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from core.custom_models import FormError
from core.funciones import addData, log, secure_module

from .forms import (
    ExcepcionAgendaForm,
    GrupoAgendaForm,
    RecursoForm,
    ServicioForm,
)
from .models import (
    EXCEPTION_TYPE_CHOICES,
    ExcepcionAgenda,
    GrupoAgenda,
    HorarioLaboral,
    Recurso,
    Servicio,
    WEEKDAY_CHOICES,
)


SUB_LISTADOS = ('recursos', 'servicios', 'excepciones', 'horarios')
CRUD_GET_ACTIONS = ('add', 'change')


def _parse_time(value):
    parts = (value or '').split(':')
    if len(parts) < 2:
        return None
    try:
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, TypeError):
        return None


def _resolver_grupo(request):
    raw = request.POST.get('grupo_id') or request.GET.get('grupo_id') or ''
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return GrupoAgenda.objects.get(pk=int(raw), status=True)
    except (GrupoAgenda.DoesNotExist, ValueError):
        return None


@login_required
@secure_module
def agendaConfiguracionView(request):
    data = {
        'titulo': 'Configuración de agenda',
        'modulo': 'Agenda',
        'ruta': request.path,
        'fecha': str(date.today()),
        'tipos_excepcion': EXCEPTION_TYPE_CHOICES,
        'weekday_choices': WEEKDAY_CHOICES,
    }
    addData(request, data)

    if request.method == 'POST':
        res_json = []
        action = request.POST.get('action', '')
        entity = request.POST.get('entity', '')
        try:
            with transaction.atomic():

                if entity == 'grupo':
                    if action == 'add':
                        form = GrupoAgendaForm(request.POST, request=request)
                        if form.is_valid():
                            form.save()
                            log(f"Creó grupo de agenda {form.instance}", request, 'add', obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'change':
                        filtro = GrupoAgenda.objects.get(pk=int(request.POST['pk']))
                        form = GrupoAgendaForm(request.POST, request=request, instance=filtro)
                        if form.is_valid():
                            form.save()
                            log(f"Editó grupo de agenda {form.instance}", request, 'change', obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'delete':
                        filtro = GrupoAgenda.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request=request)
                        log(f"Eliminó grupo de agenda {filtro}", request, 'del', obj=filtro.id)
                        res_json.append({'error': False, 'reload': True})

                elif entity == 'recurso':
                    if action == 'add':
                        form = RecursoForm(request.POST, request=request)
                        if form.is_valid():
                            form.save()
                            log(f"Creó recurso {form.instance}", request, 'add', obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'change':
                        filtro = Recurso.objects.get(pk=int(request.POST['pk']))
                        form = RecursoForm(request.POST, request=request, instance=filtro)
                        if form.is_valid():
                            form.save()
                            log(f"Editó recurso {form.instance}", request, 'change', obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'delete':
                        filtro = Recurso.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request=request)
                        log(f"Eliminó recurso {filtro}", request, 'del', obj=filtro.id)
                        res_json.append({'error': False, 'reload': True})
                    elif action == 'reorder':
                        ids = request.POST.getlist('ids[]') or request.POST.get('ids', '').split(',')
                        for pos, pk in enumerate(ids):
                            if not pk:
                                continue
                            Recurso.objects.filter(pk=int(pk), status=True).update(orden=pos)
                        res_json.append({'error': False})

                elif entity == 'servicio':
                    if action == 'add':
                        grupo_id = request.POST.get('grupo_id') or None
                        form = ServicioForm(request.POST, request=request, grupo_id=grupo_id)
                        if form.is_valid():
                            form.save()
                            log(f"Creó servicio {form.instance}", request, 'add', obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'change':
                        filtro = Servicio.objects.get(pk=int(request.POST['pk']))
                        form = ServicioForm(request.POST, request=request, instance=filtro)
                        if form.is_valid():
                            form.save()
                            log(f"Editó servicio {form.instance}", request, 'change', obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'delete':
                        filtro = Servicio.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request=request)
                        log(f"Eliminó servicio {filtro}", request, 'del', obj=filtro.id)
                        res_json.append({'error': False, 'reload': True})
                    elif action == 'reorder':
                        ids = request.POST.getlist('ids[]') or request.POST.get('ids', '').split(',')
                        for pos, pk in enumerate(ids):
                            if not pk:
                                continue
                            Servicio.objects.filter(pk=int(pk), status=True).update(orden=pos)
                        res_json.append({'error': False})

                elif entity == 'excepcion':
                    if action == 'add':
                        grupo_id = request.POST.get('grupo_id') or None
                        form = ExcepcionAgendaForm(request.POST, request=request, grupo_id=grupo_id)
                        if form.is_valid():
                            form.save()
                            log(f"Creó excepción {form.instance}", request, 'add', obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'change':
                        filtro = ExcepcionAgenda.objects.get(pk=int(request.POST['pk']))
                        form = ExcepcionAgendaForm(request.POST, request=request, instance=filtro)
                        if form.is_valid():
                            form.save()
                            log(f"Editó excepción {form.instance}", request, 'change', obj=form.instance.id)
                            res_json.append({'error': False, 'reload': True})
                        else:
                            raise FormError(form)
                    elif action == 'delete':
                        filtro = ExcepcionAgenda.objects.get(pk=int(request.POST['id']))
                        filtro.status = False
                        filtro.save(request=request)
                        log(f"Eliminó excepción {filtro}", request, 'del', obj=filtro.id)
                        res_json.append({'error': False, 'reload': True})

                elif entity == 'horario':
                    if action == 'load':
                        recurso_id = int(request.POST.get('recurso_id') or 0)
                        rec = Recurso.objects.filter(pk=recurso_id, status=True).first()
                        if not rec:
                            return JsonResponse({'error': True, 'message': 'Recurso no encontrado.'})
                        horarios = HorarioLaboral.objects.filter(
                            recurso=rec, status=True
                        ).order_by('dia_semana', 'hora_inicio')
                        blocks = [
                            {
                                'id': h.id,
                                'day': h.dia_semana,
                                'start': h.hora_inicio.strftime('%H:%M'),
                                'end': h.hora_fin.strftime('%H:%M'),
                                'slot_min': h.duracion_slot_min,
                            }
                            for h in horarios
                        ]
                        default_slot = horarios.first().duracion_slot_min if horarios.exists() else 30
                        return JsonResponse({'error': False, 'blocks': blocks, 'default_slot_min': default_slot})

                    if action == 'save':
                        recurso_id = int(request.POST.get('recurso_id') or 0)
                        rec = Recurso.objects.filter(pk=recurso_id, status=True).first()
                        if not rec:
                            return JsonResponse({'error': True, 'message': 'Recurso no encontrado.'})
                        raw = request.POST.get('blocks') or '[]'
                        blocks = json.loads(raw)
                        slot_min_default = int(request.POST.get('slot_min') or 30)
                        HorarioLaboral.objects.filter(recurso=rec, status=True).update(status=False)
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
                                recurso=rec, dia_semana=dia,
                                hora_inicio=hi, hora_fin=hf, duracion_slot_min=slot_min,
                            )
                            h.save(request=request)
                            creados += 1
                        log(f"Actualizó horario de {rec.nombre} ({creados} bloques)",
                            request, 'change', obj=rec.id)
                        return JsonResponse({'error': False, 'count': creados})

                if not res_json:
                    res_json.append({'error': True, 'message': 'Acción no reconocida.'})

        except (GrupoAgenda.DoesNotExist, Recurso.DoesNotExist,
                Servicio.DoesNotExist, ExcepcionAgenda.DoesNotExist):
            res_json.append({'error': True, 'message': 'Registro no encontrado.'})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except ValueError as ex:
            res_json.append({'error': True, 'message': str(ex)})
        except Exception as ex:
            res_json.append({'error': True, 'message': f'Intente nuevamente: {ex}'})
        return JsonResponse(res_json, safe=False)

    action_param = request.GET.get('action', '')

    if action_param in CRUD_GET_ACTIONS:
        entity = request.GET.get('entity', '')
        data['entity'] = entity
        data['action'] = action_param
        grupo = _resolver_grupo(request)
        data['grupo'] = grupo
        data['grupo_id'] = grupo.id if grupo else ''
        try:
            if entity == 'grupo':
                if action_param == 'add':
                    data['form'] = GrupoAgendaForm()
                    template = get_template('agenda/configuracion/grupo_form.html')
                    return JsonResponse({'result': True, 'data': template.render(data)})
                if action_param == 'change':
                    data['pk'] = pk = int(request.GET['id'])
                    data['filtro'] = filtro = GrupoAgenda.objects.get(pk=pk)
                    data['form'] = GrupoAgendaForm(initial=model_to_dict(filtro), instance=filtro)
                    template = get_template('agenda/configuracion/grupo_form.html')
                    return JsonResponse({'result': True, 'data': template.render(data)})

            elif entity == 'recurso':
                if action_param == 'add':
                    initial = {}
                    if grupo:
                        initial['grupo_agenda'] = grupo.id
                    data['form'] = RecursoForm(initial=initial)
                    template = get_template('agenda/configuracion/recurso_form.html')
                    return JsonResponse({'result': True, 'data': template.render(data)})
                if action_param == 'change':
                    data['pk'] = pk = int(request.GET['id'])
                    data['filtro'] = filtro = Recurso.objects.get(pk=pk)
                    data['form'] = RecursoForm(initial=model_to_dict(filtro), instance=filtro)
                    template = get_template('agenda/configuracion/recurso_form.html')
                    return JsonResponse({'result': True, 'data': template.render(data)})

            elif entity == 'servicio':
                if action_param == 'add':
                    initial = {}
                    if grupo:
                        initial['grupo_agenda'] = grupo.id
                    data['form'] = ServicioForm(
                        initial=initial,
                        grupo_id=(grupo.id if grupo else None),
                    )
                    template = get_template('agenda/configuracion/servicio_form.html')
                    return JsonResponse({'result': True, 'data': template.render(data)})
                if action_param == 'change':
                    data['pk'] = pk = int(request.GET['id'])
                    data['filtro'] = filtro = Servicio.objects.get(pk=pk)
                    initial = model_to_dict(filtro)
                    initial['recursos'] = filtro.recursos.values_list('id', flat=True)
                    data['form'] = ServicioForm(initial=initial, instance=filtro)
                    template = get_template('agenda/configuracion/servicio_form.html')
                    return JsonResponse({'result': True, 'data': template.render(data)})

            elif entity == 'excepcion':
                if action_param == 'add':
                    data['form'] = ExcepcionAgendaForm(
                        grupo_id=(grupo.id if grupo else None),
                    )
                    template = get_template('agenda/configuracion/excepcion_form.html')
                    return JsonResponse({'result': True, 'data': template.render(data)})
                if action_param == 'change':
                    data['pk'] = pk = int(request.GET['id'])
                    data['filtro'] = filtro = ExcepcionAgenda.objects.get(pk=pk)
                    data['form'] = ExcepcionAgendaForm(initial=model_to_dict(filtro), instance=filtro)
                    template = get_template('agenda/configuracion/excepcion_form.html')
                    return JsonResponse({'result': True, 'data': template.render(data)})

        except (GrupoAgenda.DoesNotExist, Recurso.DoesNotExist,
                Servicio.DoesNotExist, ExcepcionAgenda.DoesNotExist):
            return JsonResponse({'result': False, 'message': 'Registro no encontrado.'})
        except Exception as ex:
            return JsonResponse({'result': False, 'message': str(ex)})

        return JsonResponse({'result': False, 'message': 'Acción no soportada.'})

    if action_param in SUB_LISTADOS:
        grupo = _resolver_grupo(request)
        if not grupo:
            data['error_message'] = 'Selecciona un grupo desde el listado principal.'
            data['agenda_grupos'] = GrupoAgenda.objects.filter(status=True).order_by('nombre')
            return render(request, 'agenda/configuracion/listado.html', data)

        criterio = (request.GET.get('criterio') or '').strip()
        data['grupo'] = grupo
        data['filtro'] = grupo
        data['criterio'] = criterio
        data['seccion'] = action_param
        data['url_vars'] = (
            f'&action={action_param}&grupo_id={grupo.id}'
            + (f'&criterio={criterio}' if criterio else '')
        )

        if action_param == 'recursos':
            listado = Recurso.objects.filter(
                grupo_agenda=grupo, status=True
            ).select_related('grupo_agenda', 'usuario')
            if criterio:
                listado = listado.filter(
                    Q(nombre__icontains=criterio) | Q(descripcion__icontains=criterio)
                )
            data['listado_recursos'] = listado.order_by('orden', 'nombre')
            return render(request, 'agenda/configuracion/recurso_listado.html', data)

        if action_param == 'servicios':
            listado = Servicio.objects.filter(
                grupo_agenda=grupo, status=True
            ).select_related('grupo_agenda').prefetch_related('recursos')
            if criterio:
                listado = listado.filter(
                    Q(nombre__icontains=criterio) | Q(descripcion__icontains=criterio)
                )
            data['listado_servicios'] = listado.order_by('orden', 'nombre')
            return render(request, 'agenda/configuracion/servicio_listado.html', data)

        if action_param == 'excepciones':
            listado = ExcepcionAgenda.objects.filter(
                recurso__grupo_agenda=grupo, status=True,
            ).select_related('recurso', 'recurso__grupo_agenda')
            if criterio:
                listado = listado.filter(
                    Q(motivo__icontains=criterio) | Q(recurso__nombre__icontains=criterio)
                )
            data['listado_excepciones'] = listado.order_by('-fecha', 'recurso__nombre')
            return render(request, 'agenda/configuracion/excepcion_listado.html', data)

        if action_param == 'horarios':
            recursos_qs = Recurso.objects.filter(
                grupo_agenda=grupo, status=True,
            ).order_by('orden', 'nombre')
            data['recursos_para_horario'] = recursos_qs
            recurso_param = request.GET.get('recurso', '')
            if not recurso_param:
                primero = recursos_qs.first()
                recurso_param = str(primero.id) if primero else ''
            data['recurso_inicial'] = recurso_param
            data['day_start_inicial'] = request.GET.get('day_start', '') or '06:00'
            data['day_end_inicial'] = request.GET.get('day_end', '') or '22:00'
            data['slot_inicial'] = request.GET.get('slot', '') or '30'
            return render(request, 'agenda/configuracion/horario_panel.html', data)

    criterio = (request.GET.get('criterio') or '').strip()
    grupos_qs = GrupoAgenda.objects.filter(status=True).order_by('nombre')
    if criterio:
        grupos_qs = grupos_qs.filter(
            Q(nombre__icontains=criterio) | Q(descripcion__icontains=criterio)
        )
    data['criterio'] = criterio
    data['url_vars'] = f'&criterio={criterio}' if criterio else ''
    data['agenda_grupos'] = grupos_qs
    data['listado_grupos'] = grupos_qs
    data['count_grupos'] = grupos_qs.count()
    return render(request, 'agenda/configuracion/listado.html', data)
