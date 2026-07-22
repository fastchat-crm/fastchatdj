from django.urls import path

from . import views

urlpatterns = [
    path('', views.cotizador_view, name='cotizador'),
    path('api/cotizar/', views.api_cotizar, name='cotizador_api_cotizar'),
    path('api/cliente/<str:cedula>/', views.api_cliente_cedula, name='cotizador_api_cedula'),
]
