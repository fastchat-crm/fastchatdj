from django.urls import path, re_path

from public.view_login import login_tienda
from .recuperar_clave import recuperar, reset_confirmar
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
        "nombre": "Clientes",
        "url": 'personas/',
        "vista": personasView,
    },
)

urlpatterns = [
    re_path(r'^login/', login_tienda, name='login_url'),
    re_path(r'^logout/', logout_user, name='logout_url'),
    re_path(r'^recuperar/reset/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,32})/$',
            reset_confirmar, name='auth_reset_confirmar'),
    re_path(r'^recuperar/', recuperar, name='auth_recuperar'),
]

for u in autenticacion_urls:
    urlpatterns.append(re_path(r'^{}$'.format(u["url"]), u["vista"]))