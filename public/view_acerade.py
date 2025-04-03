from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import get_template
from core.funciones import addData
from seguridad.models import *


def acercade(request):
    data = {
        'titulo': 'Acerca de',
        'ruta': request.path,
        'fecha': datetime.now(),
    }
    addData(request, data)

    if request.method == 'POST':
        pass
    elif request.method == 'GET':
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
    return render(request, 'public/landing/acercade.html', data)
