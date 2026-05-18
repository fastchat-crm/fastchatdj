from django.apps import AppConfig


class CrmConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'crm'

    def ready(self):
        from . import funciones_chatbot  # noqa: F401
        from . import funciones_agenda  # noqa: F401
        from . import funciones_cliente  # noqa: F401
