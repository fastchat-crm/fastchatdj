import os, sys
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fastchatdj.settings')

application = get_wsgi_application()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from django.core import mail
import threading


class EmailThread(threading.Thread):
    def __init__(self, datos):
        self.datos = datos
        threading.Thread.__init__(self)

    def run(self):
        datos = self.datos
        msg = mail.EmailMultiAlternatives(datos["subject"], datos["plain_message"], datos["from_email"], datos["to"])
        msg.mixed_subtype = 'related'
        msg.attach_alternative(datos["html_message"], "text/html")
        msg.send(fail_silently=False)


def enviar_correo_html(datos):
    EmailThread(datos=datos).start()
