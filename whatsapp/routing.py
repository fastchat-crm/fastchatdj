from django.urls import re_path, path
from . import consumers

websocket_urlpatterns = [
    path('ws/chat/<int:conversacion_id>/', consumers.ChatConsumer.as_asgi()),
    path('ws/session/<int:session_id>/', consumers.SessionConsumer.as_asgi()),
]