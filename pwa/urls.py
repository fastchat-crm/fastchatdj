from django.urls import path

from .views import manifest, offline, service_worker, push_subscription_status


urlpatterns = [
    path('manifest.json', manifest, name='pwa_manifest'),
    path('serviceworker.js', service_worker, name='pwa_service_worker'),
    path('offline/', offline, name='pwa_offline'),
    path('pwa/push-estado/', push_subscription_status, name='pwa_push_estado'),
]
