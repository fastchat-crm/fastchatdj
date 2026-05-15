from django.urls import path, re_path

from .views import agendaIndexView
from .view_configuracion import agendaConfiguracionView
from .view_citas import citasView


agenda_urls = (
    {
        'nombre': 'Configuración de agenda',
        'url': 'configuracion/',
        'vista': agendaConfiguracionView,
    },
    {
        'nombre': 'Citas',
        'url': 'citas/',
        'vista': citasView,
    },
)


urlpatterns = [
    path('', agendaIndexView, name='agenda_index'),
]


for u in agenda_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u['url']), u['vista']))
