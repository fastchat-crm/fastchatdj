from datetime import date
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from core.funciones import addData, secure_module
from .models import *


@login_required
@secure_module
def databaseBackupView(request):
    data = {
        'titulo': 'Backups de la base de datos',
        'modulo': 'Seguridad',
        'ruta': request.path,
        'fecha': str(date.today())
    }
    addData(request, data)
    if request.method == 'POST':
        res_json = []
        action = request.POST['action']
        pass
    elif request.method == 'GET':
        data['dia_actual'] = datetime.now().isoweekday()
        data['dias'] = range(1, 8)
        return render(request, 'seguridad/databasebackup/listado.html', data)