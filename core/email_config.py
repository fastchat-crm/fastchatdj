"""Envío de correo HTML en segundo plano.

Cada `send_html_mail` levanta un hilo que arma el `EmailMessage` y lo despacha.
Dos cuidados que no son obvios:

1. **Concurrencia acotada.** El mailing masivo (`seguridad/view_mailing.py`)
   llama a esta función dentro de un bucle, un correo por destinatario. Sin
   tope, eso abre una conexión SMTP simultánea por destinatario y el servidor
   empieza a cortarlas: son los `Connection unexpectedly closed` y
   `please run connect() first` que aparecían en los logs. El semáforo limita
   cuántos envíos hablan con el SMTP a la vez.

2. **Reintento con conexión nueva.** Cuando el servidor corta a mitad de la
   sesión, reusar la misma conexión vuelve a fallar con
   `please run connect() first`. El reintento descarta la conexión y abre una
   limpia.
"""
import logging
import smtplib
import threading

from django.core.mail import get_connection
from django.core.mail.message import EmailMessage
from django.template.loader import get_template

from core.funciones import Dict2Obj
from fastchatdj.settings import EMAIL_USE_TLS, EMAIL_HOST, EMAIL_PORT, DEFAULT_FROM_EMAIL, EMAIL_HOST_PASSWORD, \
    BASE_URL_PRODUCCION

logger = logging.getLogger(__name__)

# Cuántos envíos pueden estar hablando con el servidor SMTP al mismo tiempo.
# Los proveedores suelen cortar por encima de unas pocas conexiones paralelas.
MAX_ENVIOS_SIMULTANEOS = 3
_semaforo_smtp = threading.BoundedSemaphore(MAX_ENVIOS_SIMULTANEOS)

# Errores que justifican reintentar con una conexión nueva: el servidor cortó
# la sesión a mitad de camino.
_ERRORES_RECONECTABLES = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    ConnectionResetError,
    BrokenPipeError,
    TimeoutError,
)


def _configuracion_incompleta():
    """Motivo por el que el SMTP no puede funcionar, o '' si está bien.

    Sin esto, un `EMAIL_HOST` vacío hace que Django intente conectarse a
    localhost y falle con `please run connect() first` en CADA correo — un
    mensaje que no dice nada sobre la causa real. Pasó exactamente eso: al mover
    la config del proveedor a `credenciales.json` no se cargó `EMAIL_HOST`, y
    los avisos de conversación asignada fallaron en silencio durante días.
    """
    if not (EMAIL_HOST or '').strip():
        return ('falta EMAIL_HOST en credenciales.json — sin servidor SMTP no se '
                'puede enviar nada')
    if not (DEFAULT_FROM_EMAIL or '').strip():
        return 'falta DEFAULT_FROM_EMAIL en credenciales.json'
    return ''


def conectar_cuenta():
    """Conexión SMTP reutilizable para despachar un lote de correos.

    Pasala como `coneccion=` a `send_html_mail` cuando mandes varios seguidos:
    así el lote entero usa una sola sesión SMTP en vez de abrir una por correo.
    """
    return get_connection(use_tls=EMAIL_USE_TLS, host=EMAIL_HOST, port=EMAIL_PORT, username=DEFAULT_FROM_EMAIL,
                          password=EMAIL_HOST_PASSWORD)


class EmailThread(threading.Thread):
    def __init__(self, subject, html_content, recipient_list, recipient_list_cc, adjuntosrender, adjuntossave, coneccion):
        self.subject = subject
        self.recipient_list = recipient_list
        self.recipient_list_cc = recipient_list_cc
        self.html_content = html_content
        self.adjuntosrender = adjuntosrender
        self.adjuntossave = adjuntossave
        self.coneccion = coneccion

        threading.Thread.__init__(self, daemon=True)

    def _armar_mensaje(self, coneccion):
        msg = EmailMessage(self.subject, self.html_content, DEFAULT_FROM_EMAIL,
                           self.recipient_list, bcc=self.recipient_list_cc,
                           connection=coneccion)
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
        return msg

    def _destinatarios(self):
        return ', '.join((self.recipient_list or []) + (self.recipient_list_cc or [])) or 'sin destinatarios'

    def run(self):
        # El semáforo evita que un mailing masivo abra decenas de sesiones SMTP
        # en paralelo y el servidor empiece a cortarlas.
        with _semaforo_smtp:
            try:
                self._enviar(self.coneccion)
            except _ERRORES_RECONECTABLES as e:
                # El servidor cortó la sesión. Con una conexión nueva suele salir.
                logger.warning(
                    'El servidor SMTP cortó la conexión al enviar "%s" a %s (%s). Reintentando con una conexión nueva.',
                    self.subject, self._destinatarios(), e,
                )
                try:
                    self._enviar(conectar_cuenta())
                except Exception as e2:
                    logger.error(
                        'No se pudo enviar el correo "%s" a %s tras reintentar: %s',
                        self.subject, self._destinatarios(), e2,
                    )
            except Exception as e:
                # Sin este catch amplio, cualquier otro fallo (autenticación,
                # destinatario rechazado, DNS) moría dentro del hilo sin dejar
                # rastro y el correo se perdía en silencio.
                logger.error(
                    'No se pudo enviar el correo "%s" a %s: %s',
                    self.subject, self._destinatarios(), e,
                )

    def _enviar(self, coneccion):
        self._armar_mensaje(coneccion).send()


def send_html_mail(subject, html_template, datos, recipient_list, recipient_list_cc, adjuntosrender=None, adjuntossave=None, coneccion=None):
    """Renderiza `html_template` con `datos` y lo envía en segundo plano.

    `coneccion` es opcional: si mandás varios correos seguidos, creala una vez
    con `conectar_cuenta()` y pasala en todas las llamadas para reusar la misma
    sesión SMTP. Si no la pasás, cada correo abre y cierra la suya.
    """
    motivo = _configuracion_incompleta()
    if motivo:
        # Un solo aviso claro por correo perdido, en vez de dos lineas cripticas
        # del SMTP. No se reintenta: sin configuración no hay nada que reintentar.
        logger.error('Correo "%s" NO enviado: %s', subject, motivo)
        return

    try:
        if recipient_list.__len__() or recipient_list_cc.__len__():
            template = get_template(html_template)
            datos['BASE_URL_PRODUCCION'] = BASE_URL_PRODUCCION
            d = datos
            html_content = template.render(d)
            EmailThread(subject, html_content, recipient_list, recipient_list_cc, adjuntosrender, adjuntossave, coneccion).start()
    except Exception as ex:
        logger.exception('No se pudo preparar el correo "%s": %s', subject, ex)
