from django.urls import path, re_path

from public.view_login import login_tienda
from .recuperar_clave import recuperar
from .view_login import logout_user
from .view_usuario import usuarioView
from .view_persona import personasView

autenticacion_urls = (
    {
        "nombre": "Administrativos",
        "url": 'usuario/',
        "vista": usuarioView,
    },
    {
        "nombre": "Personas",
        "url": 'personas/',
        "vista": personasView,
    },
)

urlpatterns = [
    re_path(r'^login/', login_tienda, name='login_url'),
    re_path(r'^logout/', logout_user, name='logout_url'),
    re_path(r'^recuperar/', recuperar),
]

for u in autenticacion_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))