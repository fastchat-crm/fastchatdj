import smtplib
import threading
from django.core.mail import get_connection
from django.core.mail.message import EmailMessage
from django.template.loader import get_template

from core.funciones import Dict2Obj
from fastchatdj.settings import EMAIL_USE_TLS, EMAIL_HOST, EMAIL_PORT, DEFAULT_FROM_EMAIL, EMAIL_HOST_PASSWORD


def conectar_cuenta():
    conectar = get_connection(use_tls=EMAIL_USE_TLS, host=EMAIL_HOST, port=EMAIL_PORT, username=DEFAULT_FROM_EMAIL,
                              password=EMAIL_HOST_PASSWORD)
    return conectar


class EmailThread(threading.Thread):
    def __init__(self, subject, html_content, recipient_list, recipient_list_cc, adjuntosrender, adjuntossave, coneccion):
        self.subject = subject
        self.recipient_list = recipient_list
        self.recipient_list_cc = recipient_list_cc
        self.html_content = html_content
        self.adjuntosrender = adjuntosrender
        self.adjuntossave = adjuntossave
        self.coneccion = coneccion

        threading.Thread.__init__(self)

    def run(self):
        msg = EmailMessage(self.subject, self.html_content, DEFAULT_FROM_EMAIL,
                           self.recipient_list, bcc=self.recipient_list_cc)
        msg.content_subtype = "html"
        if self.adjuntosrender:
            for adjunto in self.adjuntosrender:
                obj = Dict2Obj(adjunto)
                msg.attach(
                    obj.filename,
                    obj.content,
                    adjunto.get("mimetype")
                )
        if self.adjuntossave:
            for adjunto in self.adjuntossave:
                if type(adjunto) is str:
                    msg.attach_file(adjunto)
                else:
                    msg.attach_file(adjunto.file.name)
        try:
            msg.send()
        except smtplib.SMTPServerDisconnected as e:
            print(f"Failed to send email: {e}")


def send_html_mail(subject, html_template, datos, recipient_list, recipient_list_cc, adjuntosrender=None, adjuntossave=None, coneccion=None):
    try:
        if recipient_list.__len__() or recipient_list_cc.__len__():
            template = get_template(html_template)
            d = datos
            html_content = template.render(d)
            EmailThread(subject, html_content, recipient_list, recipient_list_cc, adjuntosrender, adjuntossave, coneccion).start()
    except Exception as ex:
        print(f"Envio de correos {ex}")