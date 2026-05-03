from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render

from core.custom_forms import FormError
from core.funciones import addData, paginador, secure_module, log, redirectAfterPostGet

from .forms import TarifaPlantillaMetaForm
from .models import TarifaPlantillaMeta, CATEGORIAS_PLANTILLA


CATEGORIA_INFO = {
    'UTILITY': {
        'titulo': 'Utility (Utilidad)',
        'objetivo': 'Mensajes transaccionales que el cliente espera recibir.',
        'fines': [
            'Confirmaciones de cita, reserva o pedido',
            'Recordatorios (examen, vencimientos, pagos)',
            'Estados de envio o tracking',
            'Recibos y facturas',
            'Actualizaciones de cuenta',
        ],
        'ejemplo': 'Tu examen psicosensometrico esta agendado para el 15/05 a las 10:00.',
        'costo': 'Bajo. Gratis si el cliente escribio en las ultimas 24h (ventana de servicio).',
        'color': 'success',
    },
    'MARKETING': {
        'titulo': 'Marketing',
        'objetivo': 'Mensajes promocionales o comerciales para captar y fidelizar.',
        'fines': [
            'Promociones y descuentos',
            'Lanzamientos de cursos o productos',
            'Invitaciones a eventos',
            'Encuestas de satisfaccion',
            'Reactivacion de clientes inactivos',
        ],
        'ejemplo': 'Inscribete hoy en el curso de licencia tipo C con 20% de descuento.',
        'costo': 'Mas alto. Se cobra cada envio, sin importar la ventana de 24h.',
        'color': 'warning',
    },
    'AUTHENTICATION': {
        'titulo': 'Authentication (Autenticacion)',
        'objetivo': 'Envio de codigos de verificacion (OTP) y 2FA.',
        'fines': [
            'Codigos de un solo uso (OTP)',
            'Verificacion de telefono al registrarse',
            'Recuperacion de contrasena',
            'Confirmacion de transacciones bancarias',
        ],
        'ejemplo': 'Tu codigo de verificacion es 482910. No lo compartas.',
        'costo': 'Medio. Formato fijo, no permite texto libre adicional.',
        'color': 'info',
    },
}


@login_required
@secure_module
def tarifasView(request):
    data = {
        'titulo': 'Tarifas Meta',
        'descripcion': 'Costos vigentes por categoria de plantilla y pais',
        'ruta': request.path,
        'categoria_info': CATEGORIA_INFO,
    }
    addData(request, data)

    if request.method == 'POST':
        return _manejar_post(request)

    action = request.GET.get('action')
    data['action'] = action

    if action == 'add':
        data['form'] = TarifaPlantillaMetaForm(initial={
            'pais': 'EC', 'moneda': 'USD', 'vigencia_desde': date.today(),
        })
        return render(request, 'whatsapp/tarifas/form.html', data)

    if action == 'change':
        pk = request.GET.get('pk')
        tarifa = TarifaPlantillaMeta.objects.filter(id=pk, status=True).first()
        if not tarifa:
            return render(request, 'whatsapp/tarifas/listado.html', data)
        data['instance'] = tarifa
        data['form'] = TarifaPlantillaMetaForm(instance=tarifa)
        return render(request, 'whatsapp/tarifas/form.html', data)

    if action == 'simulador':
        return _vista_simulador(request, data)

    filtros = Q(status=True)
    criterio = (request.GET.get('criterio') or '').strip()
    pais_filtro = (request.GET.get('pais') or '').strip().upper()
    categoria_filtro = (request.GET.get('categoria') or '').strip()

    url_vars = ''
    if criterio:
        filtros &= Q(pais__icontains=criterio) | Q(notas__icontains=criterio)
        data['criterio'] = criterio
        url_vars += f'&criterio={criterio}'
    if pais_filtro:
        filtros &= Q(pais=pais_filtro)
        data['pais_sel'] = pais_filtro
        url_vars += f'&pais={pais_filtro}'
    if categoria_filtro:
        filtros &= Q(categoria=categoria_filtro)
        data['categoria_sel'] = categoria_filtro
        url_vars += f'&categoria={categoria_filtro}'

    listado = TarifaPlantillaMeta.objects.filter(filtros).order_by(
        'pais', 'categoria', '-vigencia_desde'
    )

    data['url_vars'] = url_vars
    data['list_count'] = listado.count()
    data['categorias'] = CATEGORIAS_PLANTILLA
    data['categoria_info'] = CATEGORIA_INFO
    data['hoy'] = date.today()
    data['paises_disponibles'] = TarifaPlantillaMeta.objects.filter(
        status=True
    ).values_list('pais', flat=True).distinct().order_by('pais')

    paginador(request, listado, 30, data, url_vars)

    hoy = data['hoy']
    for t in data.get('listado') or []:
        info_cat = CATEGORIA_INFO.get(t.categoria, {})
        t.cat_color = info_cat.get('color', 'secondary')
        t.cat_titulo = info_cat.get('titulo', t.get_categoria_display())
        try:
            t.costo_mil = (t.precio * Decimal(1000)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError):
            t.costo_mil = None
        if t.vigencia_desde > hoy:
            t.estado_vigencia = 'futura'
        elif t.vigencia_hasta and t.vigencia_hasta < hoy:
            t.estado_vigencia = 'expirada'
        else:
            t.estado_vigencia = 'vigente'
    return render(request, 'whatsapp/tarifas/listado.html', data)


def _manejar_post(request):
    action = request.POST.get('action')
    res_json = []
    try:
        with transaction.atomic():
            if action == 'add':
                form = TarifaPlantillaMetaForm(request.POST)
                if not form.is_valid():
                    raise FormError(form)
                tarifa = form.save(commit=False)
                tarifa.pais = (tarifa.pais or '').upper()
                tarifa.moneda = (tarifa.moneda or 'USD').upper()
                tarifa.save(request=request)
                log(f'Tarifa {tarifa} creada', request, 'add', obj=tarifa.id)
                res_json.append({'error': False, 'to': redirectAfterPostGet(request)})
                return JsonResponse(res_json, safe=False)

            if action == 'change':
                pk = int(request.POST.get('pk'))
                tarifa = TarifaPlantillaMeta.objects.filter(id=pk, status=True).first()
                if not tarifa:
                    return JsonResponse({'error': True, 'message': 'Tarifa no encontrada.'})
                form = TarifaPlantillaMetaForm(request.POST, instance=tarifa)
                if not form.is_valid():
                    raise FormError(form)
                tarifa = form.save(commit=False)
                tarifa.pais = (tarifa.pais or '').upper()
                tarifa.moneda = (tarifa.moneda or 'USD').upper()
                tarifa.save(request=request)
                log(f'Tarifa {tarifa} modificada', request, 'change', obj=tarifa.id)
                res_json.append({'error': False, 'to': redirectAfterPostGet(request)})
                return JsonResponse(res_json, safe=False)

            if action == 'delete':
                pk = int(request.POST.get('id'))
                tarifa = TarifaPlantillaMeta.objects.filter(id=pk, status=True).first()
                if not tarifa:
                    return JsonResponse({'error': True, 'message': 'Tarifa no encontrada.'})
                tarifa.status = False
                tarifa.save(request=request)
                log(f'Tarifa {pk} eliminada', request, 'del', obj=pk)
                return JsonResponse({'error': False, 'message': 'Tarifa eliminada.'})

            if action == 'simular':
                return _calcular_simulacion(request)

            return JsonResponse({'error': True, 'message': f'Accion desconocida: {action}'})

    except FormError as ex:
        res_json.append(ex.dict_error)
    except Exception as ex:
        res_json.append({'error': True, 'message': f'Error: {str(ex)}'})
    return JsonResponse(res_json, safe=False)


def _vista_simulador(request, data):
    pais_default = 'EC'
    tarifas = TarifaPlantillaMeta.objects.filter(
        status=True, pais=pais_default, vigencia_desde__lte=date.today()
    ).filter(
        Q(vigencia_hasta__isnull=True) | Q(vigencia_hasta__gte=date.today())
    ).order_by('categoria', '-vigencia_desde')

    vigentes = {}
    for t in tarifas:
        if t.categoria not in vigentes:
            vigentes[t.categoria] = t

    data['pais_default'] = pais_default
    data['tarifas_vigentes'] = vigentes
    data['categorias'] = CATEGORIAS_PLANTILLA
    data['categoria_info'] = CATEGORIA_INFO
    data['paises_disponibles'] = TarifaPlantillaMeta.objects.filter(
        status=True
    ).values_list('pais', flat=True).distinct().order_by('pais')
    return render(request, 'whatsapp/tarifas/simulador.html', data)


def _calcular_simulacion(request):
    pais = (request.POST.get('pais') or 'EC').upper()
    try:
        cant_marketing = int(request.POST.get('cant_marketing') or 0)
        cant_utility = int(request.POST.get('cant_utility') or 0)
        cant_authentication = int(request.POST.get('cant_authentication') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'error': True, 'message': 'Cantidades invalidas.'})

    if cant_marketing < 0 or cant_utility < 0 or cant_authentication < 0:
        return JsonResponse({'error': True, 'message': 'Las cantidades deben ser positivas.'})

    detalle = []
    total = Decimal('0')
    moneda_general = 'USD'

    for cat, cantidad in [
        ('MARKETING', cant_marketing),
        ('UTILITY', cant_utility),
        ('AUTHENTICATION', cant_authentication),
    ]:
        tarifa = TarifaPlantillaMeta.vigente(pais, cat)
        if not tarifa:
            detalle.append({
                'categoria': cat,
                'cantidad': cantidad,
                'precio_unitario': None,
                'subtotal': None,
                'moneda': '',
                'sin_tarifa': True,
            })
            continue
        try:
            subtotal = (tarifa.precio * Decimal(cantidad)).quantize(Decimal('0.000001'))
        except InvalidOperation:
            subtotal = Decimal('0')
        total += subtotal
        moneda_general = tarifa.moneda
        detalle.append({
            'categoria': cat,
            'cantidad': cantidad,
            'precio_unitario': str(tarifa.precio),
            'subtotal': str(subtotal),
            'moneda': tarifa.moneda,
            'sin_tarifa': False,
        })

    tarifas_pais = {}
    for cat in ('MARKETING', 'UTILITY', 'AUTHENTICATION'):
        t = TarifaPlantillaMeta.vigente(pais, cat)
        if t:
            tarifas_pais[cat] = {'precio': str(t.precio), 'moneda': t.moneda}

    return JsonResponse({
        'error': False,
        'pais': pais,
        'moneda': moneda_general,
        'total': str(total.quantize(Decimal('0.0001'))),
        'detalle': detalle,
        'tarifas_pais': tarifas_pais,
    })
