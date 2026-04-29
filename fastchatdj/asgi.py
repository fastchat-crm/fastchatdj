import os
import django
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')
django.setup()

# Importar después de configurar Django
import whatsapp.routing  # Ajusta según el nombre de tu app
import voz.routing

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                whatsapp.routing.websocket_urlpatterns
                + voz.routing.websocket_urlpatterns
            )
        )
    ),
})