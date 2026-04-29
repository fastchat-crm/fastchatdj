from django.urls import path

from .views import voice_webhook, demo_web


voz_urls = ()

urlpatterns = [
    path('twilio/webhook/', voice_webhook, name='voz_twilio_webhook'),
    path('demo/', demo_web, name='voz_demo'),
]
