from django.urls import path, re_path

from .view_acerade import acercade
from .view_changepass import changepass
from .view_registro import registro
from .view_restaurar import restaurar
from .view_login import login_tienda, logout_tienda
from .view_recordarusername import recordarusername
from .view_terminoscondiciones import terminosycondiciones

urlpatterns = [
    # path('', index),
    re_path(r'^acercade/', acercade),
    re_path(r'^register/', registro),
    re_path(r'^login/', login_tienda),
    re_path(r'^logout/', logout_tienda),
    re_path(r'^restorepass/', restaurar),
    re_path(r'^restoreusername/', recordarusername),
    re_path(r'^changepass/', changepass),
    path('terminosycondiciones/', terminosycondiciones),

]
