from django.db.models import Manager, Exists, OuterRef, Subquery, Case, BooleanField, When, Q
from django.db.models.functions import Coalesce
from django.db.models import IntegerField

from core.custom_models import CustomValueDb

class ConversacionWhatsAppManager(Manager):
    def get_queryset(self):
        return super().get_queryset().annotate(
            tiene_mensaje=Case(
                When(Q(ultimo_mensaje__isnull=True) | Q(ultimo_mensaje__iexact=''), then=CustomValueDb(1)),
                default=CustomValueDb(0)
            )
        )