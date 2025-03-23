from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template

from django.db.models import Value, Count, Sum, F, FloatField
from django.db.models.functions import Coalesce
from autenticacion.models import PerfilPersona
from core.funciones import addData, secure_module
from public.models import VisitaEntorno
from seguridad.models import *
from seguridad.templatetags.templatefunctions import encrypt


@login_required
@secure_module
def index(request):
    data = {
        'titulo': 'Inicio',
        'modulo': 'Menu',
        'ruta': '/',
        'fecha': datetime.now(),
    }
    addData(request, data)
    persona = request.user
    empresa = data['empresa']

    if request.method == 'POST':
        action = request.POST['action']
        res_json = []
        if action == 'changeempresa':
            try:
                id_ = int(encrypt(request.POST['id']))
                empresa_ = Empresa.objects.filter(pk=id_, status=True).order_by('-id').first()
                request.session['empresa_selected'] = empresa_
                # persona.empresa = empresa_
                # persona.save(request)
                response = JsonResponse({'resp': True}, safe=False)
            except Exception as ex:
                response = JsonResponse({'resp': False, 'mensaje': ex}, safe=False)
            return response
    elif request.method == 'GET':
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']

        return render(request, 'seguridad/index.html', data)
