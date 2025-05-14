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

    if request.method == 'POST':
        action = request.POST['action']
        res_json = []
    elif request.method == 'GET':
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']


        if persona.es_administrativo():
            data['PERFIL_EXISTE'] = True
            # VERIFICACIÓN DE PERFIL IA
            mostrar_modal_ia = not hasattr(persona, 'perfil_ia') or not persona.perfil_ia.tiene_datos_basicos()
            data['mostrar_modal_ia'] = mostrar_modal_ia
        else:
            data['PERFIL_EXISTE'] = False
        return render(request, 'seguridad/index.html', data)
