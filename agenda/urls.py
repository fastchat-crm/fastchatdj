from django.urls import path, re_path

from .views import agendaIndexView
from .view_grupo import grupoAgendaView
from .view_recurso import recursoView
from .view_servicio import servicioView
from .view_excepcion import excepcionView
from .view_horario import horarioEditorView
from .view_calendario import calendarioView
from .view_turno import turnoView


agenda_urls = (
    {
        'nombre': 'Grupos de agenda',
        'url': 'grupos/',
        'vista': grupoAgendaView,
    },
    {
        'nombre': 'Recursos',
        'url': 'recursos/',
        'vista': recursoView,
    },
    {
        'nombre': 'Servicios',
        'url': 'servicios/',
        'vista': servicioView,
    },
    {
        'nombre': 'Excepciones de agenda',
        'url': 'excepciones/',
        'vista': excepcionView,
    },
    {
        'nombre': 'Calendario de turnos',
        'url': 'calendario/',
        'vista': calendarioView,
    },
    {
        'nombre': 'Turnos',
        'url': 'turnos/',
        'vista': turnoView,
    },
)


urlpatterns = [
    path('', agendaIndexView, name='agenda_index'),
    path('horarios/<int:recurso_id>/', horarioEditorView, name='agenda_horario_editor'),
]


for u in agenda_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u['url']), u['vista']))
