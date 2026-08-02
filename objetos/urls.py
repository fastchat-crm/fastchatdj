from django.urls import re_path

from .view_objetos import objetosView
from .view_registros import registrosView

objetos_urls = (
    {
        "nombre": "Objetos personalizados",
        "url": '',
        "vista": objetosView,
    },
)

urlpatterns = [re_path(r'^$', objetosView)]

# Los registros de cada objeto cuelgan de su slug: /objetos/propiedades/.
# Es una sola ruta dinámica, no una por entidad — la vista resuelve la metadata
# en runtime. Va al final para no tapar la raíz del diseñador.
urlpatterns.append(
    re_path(r'^(?P<slug>[-a-z0-9]+)/$', registrosView, name='objetos_registros')
)
