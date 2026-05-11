from django.shortcuts import render

from core.funciones import addData
from seguridad.view_index import index


def landing_view(request):
    data = {
        'titulo': 'MensajerIA',
        'url_auth': True,
    }
    addData(request, data)
    return render(request, 'public/landing/landing.html', data)


def home_view(request):
    if request.user.is_authenticated:
        return index(request)
    return landing_view(request)
