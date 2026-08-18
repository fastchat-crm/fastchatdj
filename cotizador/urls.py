from django.urls import path

from . import views

urlpatterns = [
    path('', views.cotizador_view, name='cotizador'),
    path('documentacion/', views.documentacion_view, name='cotizador_documentacion'),
    path('traza/', views.traza_view, name='cotizador_traza'),
    path('api/traza/', views.api_traza, name='cotizador_api_traza'),
    path('api/traza/<int:cid>/', views.api_traza_detalle, name='cotizador_api_traza_detalle'),
    path('api/cotizar/', views.api_cotizar, name='cotizador_api_cotizar'),
    path('api/cliente/<str:cedula>/', views.api_cliente_cedula, name='cotizador_api_cedula'),
]
