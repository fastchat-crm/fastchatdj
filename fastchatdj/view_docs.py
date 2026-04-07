from django.shortcuts import render
from seguridad.models import Configuracion


def docs_view(request):
    confi = Configuracion.get_instancia()
    return render(request, 'docs/index.html', {'confi': confi})
