from django.urls import path

from . import consumers


websocket_urlpatterns = [
    path('ws/voz/twilio/', consumers.VozTwilioConsumer.as_asgi()),
    path('ws/voz/web/', consumers.VozWebConsumer.as_asgi()),
]
