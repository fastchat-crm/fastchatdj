import threading
import time
from datetime import datetime
from webpush import send_user_notification

from fastchatdj.settings import URL_GENERAL


class NotificacionPushThread(threading.Thread):
    def __init__(self, user, head, body, url, request=None):
        self.user = user
        self.head = head
        self.body = body
        self.url = url
        self.request = request
        threading.Thread.__init__(self)

    def run(self):
        send_user_notification(
            user=self.user, payload={
                "head": self.head,
                "body": self.body,
                "action": "notificacion",
                "timestamp": time.mktime(datetime.now().timetuple()),
                "url": URL_GENERAL + self.url
            }, ttl=500
        )

def enviar_not_push(user, head, body, url, request=None):
    NotificacionPushThread(user, head, body, url, request).start()