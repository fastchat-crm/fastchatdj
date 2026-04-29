import os
import sys
from pathlib import Path

from django.core.wsgi import get_wsgi_application

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fastchatdj.settings")
application = get_wsgi_application()

from core.email_config import send_html_mail
from core.funciones import Dict2Obj


DESTINATARIO_PRUEBA = "cozjosue0@gmail.com"
PLANTILLA = "email/registro_usuario.html"
ASUNTO = "Correo de prueba - FastChatDJ"


def main():
    datos = {
        "sucursal": "FastChatDJ - Prueba de correo",
        "instancia": Dict2Obj(
            {
                "first_name": "Josue",
                "username": "cozjosue0",
                "documento": "PRUEBA-12345",
            }
        ),
        "url": "http://127.0.0.1/",
        "correo": DESTINATARIO_PRUEBA,
    }

    send_html_mail(
        ASUNTO,
        PLANTILLA,
        datos,
        [DESTINATARIO_PRUEBA],
        [],
        [],
    )

    print(f"Solicitud de envío lanzada hacia {DESTINATARIO_PRUEBA} usando {PLANTILLA}")


if __name__ == "__main__":
    main()

