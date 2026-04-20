from django.db.models import Manager, Exists, OuterRef, Subquery, Case, BooleanField, When, Q
from django.db.models.functions import Coalesce
from django.db.models import IntegerField
from django.utils import timezone

from core.custom_models import CustomValueDb


class ContactoManager(Manager):
    def get_queryset(self):
        return super().get_queryset().annotate(
            tiene_mensaje=Case(
                When(Q(ultimo_mensaje__isnull=True) | Q(ultimo_mensaje__iexact=''), then=CustomValueDb(1)),
                default=CustomValueDb(0)
            )
        )


class ConversacionWhatsAppManager(Manager):
    def get_queryset(self):
        return super().get_queryset().annotate(
            expirado=Case(
                When(Q(fecha_hora_expira__lt=timezone.now()), then=CustomValueDb(True)),
                default=CustomValueDb(False)
            )
        )

    @property
    def sin_expirar(self):
        return self.get_queryset().filter(
            expirado=False,
            conversacion_finalizada=False,
            estado_conversacion=0,
        )

    @property
    def expirado(self):
        # Fuente de verdad: estado_conversacion=1. Evita que conversaciones
        # con conversacion_finalizada=True pero estado_conversacion=0
        # (estado inconsistente) aparezcan como finalizadas.
        return self.get_queryset().filter(estado_conversacion=1)
