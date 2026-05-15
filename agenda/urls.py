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
        'nombre': 'Agenda groups',
        'url': 'grupos/',
        'vista': grupoAgendaView,
    },
    {
        'nombre': 'Resources',
        'url': 'recursos/',
        'vista': recursoView,
    },
    {
        'nombre': 'Services',
        'url': 'servicios/',
        'vista': servicioView,
    },
    {
        'nombre': 'Schedule exceptions',
        'url': 'excepciones/',
        'vista': excepcionView,
    },
    {
        'nombre': 'Booking calendar',
        'url': 'calendario/',
        'vista': calendarioView,
    },
    {
        'nombre': 'Appointments',
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
