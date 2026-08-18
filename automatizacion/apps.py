from django.apps import AppConfig


class AutomatizacionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'automatizacion'
    verbose_name = 'Automatizaciones'

    def ready(self):
        # Los emisores por señal (etiqueta_agregada, conversacion_iniciada,
        # cita_creada, registro_creado) se registran acá. Ver signals.py para
        # por qué esos cuatro van por señal y los otros se disparan a mano.
        from . import signals  # noqa: F401
