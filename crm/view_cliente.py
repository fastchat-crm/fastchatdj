import sys
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from core.custom_models import FormError
from core.funciones import addData, paginador, secure_module, log

from .forms import ClienteForm
from .models import Cliente


@login_required
@secure_module
def clienteView(request):
    data = {
        'titulo': 'Cliente',
        'modulo': 'CRM',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    model = Cliente
    Formulario = ClienteForm

    if request.method == 'POST':
        res_json = []
        action = request.POST.get('action', '')
        try:
            with transaction.atomic():
                if action == 'add':
                    form = Formulario(request.POST, request=request)
                    if form.is_valid():
                        form.save()
                        log(f"Registró un cliente {form.instance}", request, 'add', obj=form.instance.id)
                        res_json.append({'error': False, 'reload': True})
                    else:
                        raise FormError(form)

                elif action == 'change':
                    filtro = model.objects.get(pk=int(request.POST['pk']))
                    form = Formulario(request.POST, instance=filtro, request=request)
                    if form.is_valid() and filtro:
                        form.save()
                        log(f"Editó un cliente {form.instance}", request, 'change', obj=form.instance.id)
                        res_json.append({'error': False, 'reload': True})
                    else:
                        raise FormError(form)

                elif action == 'delete':
                    filtro = model.objects.get(pk=int(request.POST['id']))
                    filtro.status = False
                    filtro.save(request)
                    log(f"Eliminó un cliente {filtro}", request, 'del', obj=filtro.id)
                    messages.success(request, 'Registro Eliminado')
                    res_json = {'error': False}

        except ValueError as ex:
            res_json.append({'error': True, 'message': str(ex)})
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            line = sys.exc_info()[-1].tb_lineno
            res_json.append({'error': True, 'message': f'{ex} - Line {line}'})
        return JsonResponse(res_json, safe=False)

    addData(request, data)
    if 'action' in request.GET:
        data['action'] = action = request.GET['action']
        if action == 'add':
            try:
                data['form'] = Formulario()
                template = get_template('crm/cliente/form.html')
                return JsonResponse({'result': True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({'result': False, 'message': str(ex)})

        if action == 'change':
            try:
                pk = int(request.GET['id'])
                filtro = model.objects.get(pk=pk)
                data['filtro'] = filtro
                data['form'] = Formulario(instance=filtro)
                template = get_template('crm/cliente/form.html')
                return JsonResponse({'result': True, 'data': template.render(data)})
            except Exception as ex:
                return JsonResponse({'result': False, 'message': str(ex)})

        if action == 'ver':
            pk = int(request.GET['id'])
            filtro = model.objects.get(pk=pk)
            data['pk'] = pk
            data['filtro'] = filtro
            data['form'] = Formulario(instance=filtro, ver=True)
            return render(request, 'crm/cliente/form.html', data)

    criterio = request.GET.get('criterio', '').strip()
    canal = (request.GET.get('canal') or '').strip()
    filtros = Q(status=True)
    url_vars = ''
    if criterio:
        filtros = filtros & (
            Q(cedula__icontains=criterio)
            | Q(nombres__icontains=criterio)
            | Q(apellidos__icontains=criterio)
            | Q(email__icontains=criterio)
        )
        data['criterio'] = criterio
        url_vars += '&criterio=' + criterio
    if canal:
        filtros = filtros & Q(canal_origen=canal)
        data['canal'] = canal
        url_vars += '&canal=' + canal
    listado = model.objects.filter(filtros).select_related(
        'contacto_origen', 'conversacion_origen',
        'sesion_origen', 'departamento_origen',
    )
    data['list_count'] = listado.count()
    data['url_vars'] = url_vars
    data['canales'] = (
        model.objects.filter(status=True)
        .exclude(canal_origen='')
        .values_list('canal_origen', flat=True)
        .distinct()
        .order_by('canal_origen')
    )
    paginador(request, listado.order_by('-fecha_registro'), 20, data, url_vars)
    return render(request, 'crm/cliente/listado.html', data)
