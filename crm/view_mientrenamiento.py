import sys
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect
from django.contrib import messages
from crm.forms import PerfilNegocioIAForm
from crm.models import PerfilNegocioIA
from core.funciones import addData, secure_module, log

@login_required
@secure_module
def entrenamiento_ia_view(request):
    data = {
        'titulo': 'Entrenamiento de IA',
        'descripcion': 'Personalización de mi perfil de IA',
        'ruta': request.path,
    }
    addData(request, data)

    try:
        perfil, creado = PerfilNegocioIA.objects.get_or_create(usuario=request.user)

        if request.method == 'POST':
            form = PerfilNegocioIAForm(request.POST, instance=perfil)
            if form.is_valid():
                with transaction.atomic():
                    form.save()
                    log(f"Usuario actualizó su perfil IA: {form.instance}", request, 'change')
                    messages.success(request, "Información guardada correctamente.")
                    return redirect('/panel/')  # o donde quieras redirigir
            else:
                data['form'] = form
                messages.error(request, "Error en el formulario.")
        else:
            data['form'] = PerfilNegocioIAForm(instance=perfil)

    except Exception as ex:
        error_line = sys.exc_info()[-1].tb_lineno
        messages.error(request, f"Error inesperado: {ex} - Línea {error_line}")
        return redirect('/panel/')

    return render(request, 'crm/entrenamiento/form.html', data)
