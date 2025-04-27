
from datetime import date, datetime
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Count, F
from django.forms import model_to_dict
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template


from core.custom_models import FormError
from core.funciones import addData, paginador,log
from django.contrib import messages

from seguridad.models import Empresa
from seguridad.templatetags.templatefunctions import encrypt
from ..forms import TicketForm
from ..funciones import load_responsables
from ..models import TicketAtencion, ProcesoAtencion


@login_required
# @secure_module
def indicatorsView(request):
    data = {
        'titulo': 'Panel de indicadores de tickets',
        'descripcion': 'Visualizar los indicadores de tickets',
        'modulo': 'Tickets',
        'ruta': request.path,
        'fecha': str(date.today()),
    }
    addData(request, data)
    model = TicketAtencion
    Formulario = TicketForm

    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        try:
            with transaction.atomic():
                pass
        except ValueError as ex:
            res_json.append({'error': True,
                             "message": str(ex)
                             })
        except FormError as ex:
            res_json.append(ex.dict_error)
        except Exception as ex:
            res_json.append({'error': True,
                             "message": f"Intente Nuevamente {ex}"
                             })
        return JsonResponse(res_json, safe=False)
    elif request.method == 'GET':
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']

        filtros = Q(status=True)
        # Realizar la consulta optimizada
        indicador_general = TicketAtencion.objects.filter(filtros).aggregate(
            total=Count('id'),
            pendientes=Count('id', filter=Q(estado__in=[1, 2])),
            en_proceso=Count('id', filter=Q(estado=3)),
            finalizados=Count('id', filter=Q(estado=4)),
            vigentes_pendientes = Count('id', filter=Q(fecha_vigencia__gte=datetime.now(), estado__in=[1, 2])),
            vencidos_pendientes = Count('id', filter=Q(fecha_vigencia__lt=datetime.now(), ffinactividad__isnull=True, estado__in=[1, 2])),
            sin_fecha_vigencia_pendientes = Count('id', filter=Q(fecha_vigencia__isnull=True, estado__in=[1, 2])),

            vigentes_en_proceso = Count('id', filter=Q(fecha_vigencia__gte=datetime.now(), estado=3)),
            vencidos_en_proceso = Count('id', filter=Q(fecha_vigencia__lt=datetime.now(), ffinactividad__isnull=True, estado=3)),
            sin_fecha_vigencia_en_proceso = Count('id', filter=Q(fecha_vigencia__isnull=True, estado=3)),

            vigentes = Count('id', filter=Q(fecha_vigencia__gte=datetime.now())),
            vencidos = Count('id', filter=Q(fecha_vigencia__lt=datetime.now()), ffinactividad__isnull=True),
            sin_fecha_vigencia=Count('id', filter=Q(fecha_vigencia__isnull=True)),

            finalizado_retraso = Count('id', filter=Q(fecha_vigencia__lt=F('ffinactividad'), estado=4)),
            finalizado_a_tiempo = Count('id', filter=Q(fecha_vigencia__gte=F('ffinactividad'), estado=4)),
            finalizado_sin_fecha_vigencia = Count('id', filter=Q(fecha_vigencia__isnull=True, estado=4)),
        )
        # Agrupar por año y mes para obtener la cantidad de tickets receptados
        tickets_por_mes = (
            TicketAtencion.objects.filter(filtros)
            .annotate(year=F('fecha_registro__year'), month=F('fecha_registro__month'))
            .values('year', 'month')
            .annotate(count=Count('id'))
            .order_by('year', 'month')
        )

        # Formatear los datos en un diccionario
        data['tickets_por_mes'] = {
            year: {month: 0 for month in range(1, 13)} for year in set(t['year'] for t in tickets_por_mes)
        }
        for t in tickets_por_mes:
            data['tickets_por_mes'][t['year']][t['month']] = t['count']
        anios = TicketAtencion.objects.filter(filtros).values('fecha_registro__year').distinct().order_by(
            'fecha_registro__year')

        # Crear una lista con los años
        anios = [a['fecha_registro__year'] for a in anios]
        data['anios'] = anios
        data['responsables'] = load_responsables()
        data['indicador'] = indicador_general
        data['empresas'] = Empresa.objects.filter(filtros).order_by('nombre')
        return render(request, 'ticket/panel.html', data)
