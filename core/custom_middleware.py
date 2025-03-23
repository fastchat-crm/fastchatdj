from django.utils.functional import SimpleLazyObject

from core.funciones import get_client_ip


class InitialDataApp(object):
    def __call__(self, request):
        self.process_request(request)
        response = self.get_response(request)
        return response

    def __init__(self, get_response=None):
        if get_response is not None:
            self.get_response = get_response

    # def __call__(self, request):
    #     self.process_request(request)
    #     return self.get_response(request)

    def process_request(self, request):
        from seguridad.models import Configuracion
        request.is_ajax = (request.headers.get('X-Requested-With') or "").lower().replace(" ", "") == 'XMLHttpRequest'.lower()
        request.config = Configuracion.get_instancia()
        request.ipAdd = get_client_ip(request)