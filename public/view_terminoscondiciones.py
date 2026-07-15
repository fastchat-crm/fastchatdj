from django.shortcuts import render
from core.funciones import addData
from seguridad.models import *


def terminosycondiciones(request):
    es_privacidad = 'privacidad' in request.path
    data = {
        'titulo': 'Política de Privacidad' if es_privacidad else 'Términos y Condiciones',
        'ruta': request.path,
        'fecha': datetime.now(),
    }
    addData(request, data)

    if request.method == 'POST':
        pass
    elif request.method == 'GET':
        if 'action' in request.GET:
            data["action"] = action = request.GET['action']
    return render(request, 'public/terminosycondiciones.html', data)
